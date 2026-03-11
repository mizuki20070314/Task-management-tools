from flask import Flask, render_template, request, redirect, url_for, session
from ftplib import FTP
from io import BytesIO
# import webview
from threading import Thread

app = Flask(__name__)
app.secret_key = 'dev-secret-key'

FTP_HOST = ''
FTP_USER = ''
FTP_PASS = ''


def ftp_connect():
    ftp = FTP(FTP_HOST)
    ftp.login(user=FTP_USER, passwd=FTP_PASS)
    return ftp


def load_tasks(username):
    tasks = []
    ftp = ftp_connect()
    path = f'tasks/{username}.txt'

    try:
        bio = BytesIO()
        ftp.retrbinary(f'RETR {path}', bio.write)

        content = bio.getvalue().decode('utf-8')
        for line in content.splitlines():
            parts = line.split(',', 4)
            if len(parts) < 5:
                continue

            done, name, date, time, detail = parts
            tasks.append({
                'name': name,
                'date': date,
                'time': time,
                'detail': detail,
                'done': done == '1'
            })

    except Exception:
        # ファイルが無ければ作成
        ftp.storbinary(f'STOR {path}', BytesIO(b''))

    finally:
        ftp.quit()

    return tasks



def save_tasks(username, tasks):
    ftp = ftp_connect()
    path = f'tasks/{username}.txt'

    lines = []
    for t in tasks:
        line = f"{1 if t['done'] else 0},{t['name']},{t['date']},{t['time']},{t['detail']}"
        lines.append(line)

    data = '\n'.join(lines) + '\n'
    bio = BytesIO(data.encode('utf-8'))
    ftp.storbinary(f'STOR {path}', bio)

    ftp.quit()


def user_exists(username):
    ftp = ftp_connect()
    exists = False

    try:
        lines = []
        ftp.retrlines('RETR userlist/list.txt', lines.append)

        for line in lines:
            u, _ = line.strip().split(',', 1)
            if u == username:
                exists = True
                break
    finally:
        ftp.quit()

    return exists

def add_user(username, password):
    ftp = ftp_connect()

    # 既存リスト取得
    lines = []
    ftp.retrlines('RETR userlist/list.txt', lines.append)

    # 追記
    lines.append(f'{username},{password}')

    data = '\n'.join(lines) + '\n'
    bio = BytesIO(data.encode('utf-8'))
    ftp.storbinary('STOR userlist/list.txt', bio)

    # タスクファイル作成
    bio = BytesIO(b'')
    ftp.storbinary(f'STOR tasks/{username}.txt', bio)

    ftp.quit()

@app.route('/register', methods=['GET', 'POST'])
def register():
    message = ''

    if request.method == 'POST':
        username = request.form['username'].strip()
        password = request.form['password'].strip()

        if not username or not password:
            message = 'Username and password are required.'
        elif user_exists(username):
            message = 'This username is already taken.'
        else:
            add_user(username, password)
            return redirect(url_for('login'))

    return render_template('register.html', message=message)



@app.route('/', methods=['GET', 'POST'])
def login():
    message = ''

    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        ftp = ftp_connect()

        try:
            lines = []
            ftp.retrlines('RETR userlist/list.txt', lines.append)

            for line in lines:
                u, p = line.strip().split(',', 1)
                if u == username and p == password:
                    session['username'] = username
                    return redirect(url_for('dashboard'))

            message = 'Please check your username and password!'

        finally:
            ftp.quit()

    return render_template('login.html', message=message)


@app.route('/dashboard')
def dashboard():
    if 'username' not in session:
        return redirect(url_for('login'))

    username = session['username']
    tasks = load_tasks(username)

    return render_template(
        'dashboard.html',
        username=username,
        tasks=tasks
    )


@app.route('/add', methods=['POST'])
def add_task():
    if 'username' not in session:
        return redirect(url_for('login'))

    username = session['username']

    name = request.form['name'].strip()
    date = request.form['date']
    time = request.form['time']
    detail = request.form['detail'].strip()

    if name:
        tasks = load_tasks(username)
        tasks.append({
            'name': name,
            'date': date,
            'time': time,
            'detail': detail,
            'done': False
        })
        save_tasks(username, tasks)

    return redirect(url_for('dashboard'))


@app.route('/toggle/<int:index>')
def toggle_task(index):
    if 'username' not in session:
        return redirect(url_for('login'))

    username = session['username']
    tasks = load_tasks(username)

    if 0 <= index < len(tasks):
        tasks[index]['done'] = not tasks[index]['done']
        save_tasks(username, tasks)

    return redirect(url_for('dashboard'))


@app.route('/delete/<int:index>')
def delete_task(index):
    if 'username' not in session:
        return redirect(url_for('login'))

    username = session['username']
    tasks = load_tasks(username)

    if 0 <= index < len(tasks):
        tasks.pop(index)
        save_tasks(username, tasks)

    return redirect(url_for('dashboard'))


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/chat/get')
def get_chat():
    if 'username' not in session:
        return {"messages": []}
    
    ftp = ftp_connect()
    messages = []
    try:
        lines = []
        # chat/global.txt というファイルに全ユーザーの会話を保存する例
        ftp.retrlines('RETR chat/global.txt', lines.append)
        for line in lines[-50:]: # 直近50件
            parts = line.strip().split(',', 2)
            if len(parts) == 3:
                messages.append({'user': parts[0], 'time': parts[1], 'text': parts[2]})
    except:
        pass # ファイルがない場合は空
    finally:
        ftp.quit()
    return {"messages": messages}

@app.route('/chat/send', methods=['POST'])
def send_chat():
    if 'username' not in session:
        return "Unauthorized", 401
    
    username = session['username']
    text = request.form.get('text', '').strip().replace(',', ' ') # カンマを置換
    if not text:
        return "Empty", 400

    import datetime
    jst = datetime.timezone(datetime.timedelta(hours=9))
    timestamp = datetime.datetime.now(jst).strftime('%H:%M')
    new_line = f"{username},{timestamp},{text}\n"

    ftp = ftp_connect()
    try:
        # 既存ログを取得して追記
        lines = []
        try:
            ftp.retrlines('RETR chat/global.txt', lines.append)
        except:
            pass
        
        lines.append(new_line.strip())
        data = '\n'.join(lines) + '\n'
        bio = BytesIO(data.encode('utf-8'))
        ftp.storbinary('STOR chat/global.txt', bio)
    finally:
        ftp.quit()
    return "OK"

def run_flask():
    app.run(host='0.0.0.0', port=5000, debug=False)

if __name__ == '__main__':
    # Flaskを別スレッドで起動
    t = Thread(target=run_flask)
    t.daemon = True
    t.start()
    t.join()

    # ウィンドウを表示
    # webview.create_window('PyWebView', 'http://127.0.0.1:5000')
    # webview.start()
