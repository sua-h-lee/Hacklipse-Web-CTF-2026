from contextlib import closing, contextmanager
import hashlib
import json
import os
import secrets
import sqlite3
import time
from pathlib import Path
from urllib.error import URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

import click
from flask import Flask, abort, flash, redirect, render_template, request, session, url_for

ROOT = Path(__file__).resolve().parent
DATA = Path(os.environ.get("CTF_DATA", ROOT / "instance"))
DATA.mkdir(exist_ok=True, parents=True)
app = Flask(__name__)
key = DATA / "session.key"
if not key.exists():
    try:
        with os.fdopen(os.open(key, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), "w") as stream:
            stream.write(secrets.token_hex(32))
    except FileExistsError:
        pass
app.config.update(SECRET_KEY=os.environ.get("SECRET_KEY") or key.read_text(),
                  SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax",
                  SESSION_COOKIE_SECURE=os.getenv("CTF_HTTPS") == "1", MAX_CONTENT_LENGTH=8192)
flags = json.loads(os.getenv("CTF_FLAGS_JSON", "[]"))
if flags and (not isinstance(flags, list) or len(flags) != 15 or
              not all(isinstance(f, str) and f.strip() == f and f for f in flags) or len(set(flags)) != 15):
    raise ValueError("Configure 15 distinct flags")
catalog = [{"title": f"문제 {n:02}", "description": "문제 설명을 준비하고 있습니다.", "points": 100}
           for n in range(1, 16)]
if os.getenv("CTF_CATALOG"):
    catalog = json.loads(Path(os.environ["CTF_CATALOG"]).read_text())
    if len(catalog) != 15 or any(not isinstance(p["points"], int) or p["points"] < 0 or
                                 not all(isinstance(p[k], str) for k in ("title", "description")) for p in catalog):
        raise ValueError("Invalid challenge catalog")


@contextmanager
def database():
    with closing(sqlite3.connect(DATA / "progress.sqlite3", timeout=20)) as connection:
        with connection:
            yield connection


with database() as db:
    db.executescript("""
        CREATE TABLE IF NOT EXISTS players (digest TEXT PRIMARY KEY, player TEXT UNIQUE NOT NULL);
        CREATE TABLE IF NOT EXISTS player_names (player TEXT PRIMARY KEY, name TEXT UNIQUE NOT NULL);
        CREATE TABLE IF NOT EXISTS solves (player TEXT, flag_id INTEGER, PRIMARY KEY(player, flag_id));
        CREATE TABLE IF NOT EXISTS environments (player TEXT PRIMARY KEY, problem INTEGER, url TEXT, expires REAL);
    """)


@app.cli.command("issue-code")
@click.option("--name", help="Player display name")
def issue_code(name):
    code = secrets.token_urlsafe(18)
    with database() as db:
        player = secrets.token_hex(24)
        if name:
            if not db.execute("INSERT OR IGNORE INTO player_names VALUES (?,?)", (player, name)).rowcount:
                raise click.ClickException("Player name already exists")
        db.execute("INSERT INTO players VALUES (?,?)", (hashlib.sha256(code.encode()).hexdigest(), player))
    click.echo(code)


@app.before_request
def protect():
    if request.endpoint == "static":
        return
    if "csrf" not in session:
        session["csrf"] = secrets.token_hex(24)
    if request.method == "POST" and not secrets.compare_digest(request.form.get("csrf", "").encode(), session["csrf"].encode()):
        abort(403)
    if request.endpoint not in ("login", "static") and "account" not in session:
        return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        digest = hashlib.sha256(request.form.get("code", "").strip().encode()).hexdigest()
        with database() as db:
            row = db.execute("SELECT player,name FROM players LEFT JOIN player_names USING(player) WHERE digest=?", (digest,)).fetchone()
        if row:
            session.clear()
            session.update(account=row[0], name=row[1] or "player", csrf=secrets.token_hex(24))
            return redirect(url_for("intro"))
        flash("참가 코드를 확인해 주세요.")
    return render_template("platform.html", login=True)


@app.post("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


def validate_problem(n):
    if not 1 <= n <= len(catalog):
        abort(404)


@app.get("/intro")
def intro():
    return render_template("intro.html")


@app.get("/")
@app.get("/problems/<int:n>")
def home(n=1):
    validate_problem(n)
    player = session["account"]
    with database() as db:
        solved = {i + 1 for i, in db.execute("SELECT flag_id FROM solves WHERE player=?", (player,))}
        env = db.execute("SELECT problem,url FROM environments WHERE player=? AND expires>?", (player,time.time())).fetchone()
    return render_template("platform.html", catalog=catalog, n=n, solved=solved, env=env,
                           score=sum(catalog[i-1]["points"] for i in solved))


@app.post("/problems/<int:n>/submit")
def submit(n):
    validate_problem(n)
    if not flags:
        flash("정답 설정 대기 중입니다.")
    elif secrets.compare_digest(request.form.get("flag","").strip().encode(), flags[n-1].encode()):
        with database() as db:
            fresh = db.execute("INSERT OR IGNORE INTO solves VALUES (?,?)", (session["account"], n-1)).rowcount
        flash(f"ACCEPTED · +{catalog[n-1]['points']}점" if fresh else "이미 해결한 문제입니다.")
    else:
        flash("INCORRECT · 다시 시도해 주세요.")
    return redirect(url_for("home", n=n))


class RunnerRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


runner_client = build_opener(RunnerRedirectHandler())


@app.after_request
def security_headers(response):
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; object-src 'none'; base-uri 'none'; "
        "frame-ancestors 'none'; form-action 'self'"
    )
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    if request.endpoint != "static":
        response.headers["Cache-Control"] = "no-store"
    return response


@app.post("/problems/<int:n>/start")
def start(n):
    validate_problem(n)
    base, token = os.getenv("CTF_RUNNER_URL"), os.getenv("CTF_RUNNER_TOKEN")
    if not base or not token:
        flash("문제 실행 서버 연결 대기 중입니다.")
        return redirect(url_for("home", n=n))
    player = session["account"]
    try:
        with database() as db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute("SELECT problem FROM environments WHERE player=? AND expires>?", (player,time.time())).fetchone()
            if old and old[0] == n:
                return redirect(url_for("home", n=n))
            if old and request.form.get("replace") != str(old[0]):
                flash("현재 실행 중인 환경을 확인해 주세요.")
                return redirect(url_for("home", n=n))
            endpoint = urlsplit(base)
            if endpoint.scheme != "https" and not (endpoint.scheme == "http" and endpoint.hostname in ("127.0.0.1", "::1", "localhost")):
                raise ValueError("Runner connection requires HTTPS")
            req = Request(base.rstrip("/") + "/environments/" + player, method="PUT",
                          data=json.dumps({"problem": n, "ttl_seconds": 1800}).encode(),
                          headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"})
            with runner_client.open(req, timeout=5) as response:
                payload = response.read(8193)
                if len(payload) > 8192:
                    raise ValueError("Invalid runner response size")
                result = json.loads(payload)
            link, expires = result["url"], float(result["expires"])
            if urlsplit(link).scheme not in ("http","https") or not urlsplit(link).hostname or not time.time() < expires < time.time()+1810:
                raise ValueError()
            db.execute("INSERT OR REPLACE INTO environments VALUES (?,?,?,?)", (player,n,link,expires))
    except (URLError, OSError, ValueError, TypeError, KeyError, sqlite3.OperationalError):
        flash("환경을 준비하지 못했습니다. 잠시 후 다시 시도해 주세요.")
    return redirect(url_for("home", n=n))
