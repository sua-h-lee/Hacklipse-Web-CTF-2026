import json
import os
import secrets
import sqlite3
from pathlib import Path
from flask import Flask, jsonify, render_template, request, session
from waitress import serve

ROOT = Path(__file__).parent
app = Flask(__name__, instance_relative_config=True)
Path(app.instance_path).mkdir(exist_ok=True)
key = Path(app.instance_path) / 'session.key'
if not key.exists():
    key.write_text(secrets.token_hex(32))
    key.chmod(0o600)
app.config.update(SECRET_KEY=os.environ.get('SECRET_KEY') or key.read_text(), SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Lax', MAX_CONTENT_LENGTH=4096)
DB = Path(app.instance_path) / 'progress.sqlite3'
with sqlite3.connect(DB) as db:
    db.execute('CREATE TABLE IF NOT EXISTS solves (player TEXT, flag_id INTEGER, PRIMARY KEY(player, flag_id))')
FLAGS = json.loads(os.environ.get('CTF_FLAGS_JSON', '[]'))
if FLAGS and (len(FLAGS) != 15 or not all(isinstance(f, str) and f and f.strip() == f for f in FLAGS) or len(set(FLAGS)) != 15):
    raise ValueError('Configure exactly 15 distinct nonempty flags')
PARTS = json.loads((ROOT / 'passage.json').read_text())


def state():
    with sqlite3.connect(DB) as db:
        count = db.execute('SELECT COUNT(*) FROM solves WHERE player=?', (session['player'],)).fetchone()[0]
    attribution = 'The Moon and Sixpence\nW. Somerset Maugham' if count == 15 else None
    return dict(count=count, parts=PARTS[:count], attribution=attribution)


@app.get('/')
@app.get('/submit')
def index():
    session.setdefault('player', secrets.token_hex(24))
    session.setdefault('csrf', secrets.token_hex(24))
    session.permanent = True
    logo = (ROOT / 'ending_assets' / 'hacklipse_logo.txt').read_text(encoding='utf-8')
    return render_template('submit.html', initial=state(), csrf=session['csrf'], logo=logo)


@app.post('/submit')
def submit():
    if 'player' not in session or not secrets.compare_digest(request.headers.get('X-CSRF-Token', ''), session.get('csrf', 'missing')):
        return jsonify(message='페이지를 새로고침해주세요.'), 403
    if state()['count'] == 15:
        return jsonify(message='Recovery complete. Submissions are closed.'), 409
    if not FLAGS:
        return jsonify(message='서버의 정답 플래그 설정 대기 중입니다.'), 503
    data = request.get_json(silent=True) or {}
    flag = data.get('flag') if isinstance(data, dict) else None
    if not isinstance(flag, str) or not flag.strip() or len(flag) > 1024:
        return jsonify(message='플래그를 입력해주세요. (최대 1024자)'), 400
    matched = next((i for i, expected in enumerate(FLAGS) if secrets.compare_digest(flag.strip().encode(), expected.encode())), None)
    if matched is None:
        return jsonify(message='INCORRECT — 다시 시도해주세요.'), 400
    with sqlite3.connect(DB) as db:
        result = db.execute('INSERT OR IGNORE INTO solves VALUES (?, ?)', (session['player'], matched))
        fresh = result.rowcount == 1
    return jsonify(**state(), fresh=fresh, message='ACCEPTED — 기록을 복구했습니다.' if fresh else 'ALREADY RECOVERED — 이미 제출한 플래그입니다.')


if __name__ == '__main__':
    serve(app, host='0.0.0.0', port=8000)
