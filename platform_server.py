from contextlib import closing, contextmanager
import hashlib
import json
import os
import re
import secrets
import sqlite3
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

import click
from flask import Flask, Response, abort, flash, redirect, render_template, request, session, url_for

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
pilot = os.getenv("CTF_PILOT") == "1"
flags = [f"HKL{{testflag{n}}}" for n in range(1, 16)] if pilot else json.loads(os.getenv("CTF_FLAGS_JSON", "[]"))
if not pilot and flags and (not isinstance(flags, list) or len(flags) != 15 or
              not all(isinstance(f, str) and re.fullmatch(r"HKL\{[^{}\r\n]+\}", f) for f in flags) or len(set(flags)) != 15):
    raise ValueError("Configure 15 distinct HKL{...} flags")
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
        env = db.execute("SELECT problem,url,expires FROM environments WHERE player=? AND expires>?", (player,time.time())).fetchone()
    return render_template("platform.html", catalog=catalog, n=n, solved=solved, env=env,
                           pilot=pilot, now=time.time(), active_sample=flags[n-1] if pilot and env and env[0]==n else None, score=sum(catalog[i-1]["points"] for i in solved))


def stop_environment(db, player, n, expected=None):
    row = db.execute("SELECT url FROM environments WHERE player=? AND problem=?", (player, n)).fetchone()
    if not row or (expected is not None and row[0] != expected):
        return
    base = os.getenv("CTF_RUNNER_URL", "").rstrip("/")
    token = os.getenv("CTF_RUNNER_TOKEN")
    if not token or not base.startswith("https://"):
        raise ValueError("Invalid runner configuration")
    req = Request(f"{base}/environments/{player}/{n}", method="DELETE",
                  headers={"Authorization": "Bearer " + token})
    with runner_client.open(req, timeout=15) as response:
        if response.status != 204:
            raise ValueError("Runner did not confirm termination")
    db.execute("DELETE FROM environments WHERE player=? AND problem=?", (player, n))


@app.post("/problems/<int:n>/stop")
def stop(n):
    validate_problem(n)
    try:
        with database() as db:
            db.execute("BEGIN IMMEDIATE")
            stop_environment(db, session["account"], n, request.form.get("instance", ""))
    except (OSError, ValueError):
        flash("인스턴스를 종료하지 못했습니다. 다시 시도해 주세요.")
    return redirect(url_for("home", n=n), code=303)


@app.post("/problems/<int:n>/submit")
def submit(n):
    validate_problem(n)
    if not flags:
        flash("정답 설정 대기 중입니다.")
    elif secrets.compare_digest(request.form.get("flag","").strip().encode(), flags[n-1].encode()):
        with database() as db:
            fresh = db.execute("INSERT OR IGNORE INTO solves VALUES (?,?)", (session["account"], n-1)).rowcount
            try:
                stop_environment(db, session["account"], n)
            except (OSError, ValueError):
                flash("인스턴스 자동 종료에 실패했습니다. 종료하기를 눌러 다시 시도해 주세요.")
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
    if request.endpoint == "club_site":
        response.headers["Content-Security-Policy"] = "sandbox; default-src 'none'; style-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    if request.endpoint != "static":
        response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/problems/1/site/<instance>/<asset>")
def club_site(instance, asset):
    if not pilot or asset not in ("index.html", "style.css"):
        abort(404)
    base = os.environ["CTF_RUNNER_URL"].rstrip("/")
    player = session["account"]
    with database() as db:
        active = db.execute(
            "SELECT 1 FROM environments WHERE player=? AND problem=1 AND url=? AND expires>?",
            (player, instance, time.time()),
        ).fetchone()
    if not active:
        abort(404)
    req = Request(f"{base}/environments/{player}/site/{asset}",
                  headers={"Authorization": "Bearer " + os.environ["CTF_RUNNER_TOKEN"]})
    try:
        with runner_client.open(req, timeout=5) as upstream:
            data = upstream.read(65537)
            if len(data) > 65536:
                abort(502)
    except HTTPError as error:
        if error.code == 410:
            with database() as db:
                db.execute("DELETE FROM environments WHERE player=? AND problem=1 AND url=?", (player, instance))
            flash("환경이 종료되었습니다. 접속하기를 눌러 다시 시작하세요.")
            return redirect(url_for("home", n=1))
        abort(502)
    except OSError:
        abort(503)
    return Response(data, mimetype="text/css" if asset == "style.css" else "text/html")


@app.post("/problems/<int:n>/start")
def start(n):
    validate_problem(n)
    base, token = os.getenv("CTF_RUNNER_URL"), os.getenv("CTF_RUNNER_TOKEN")
    if not base or not token:
        if pilot:
            return {"error": "테스트 실행 서버 연결 대기 중입니다."}, 503
        flash("문제 실행 서버 연결 대기 중입니다.")
        return redirect(url_for("home", n=n))
    player = session["account"]
    try:
        with database() as db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute("SELECT problem,url FROM environments WHERE player=? AND expires>?", (player,time.time())).fetchone()
            web_problem = pilot and n == 1
            if not web_problem and db.execute("SELECT 1 FROM solves WHERE player=? AND flag_id=?", (player,n-1)).fetchone():
                return {"solved": True} if pilot and not web_problem else redirect(url_for("home", n=n))
            if web_problem and old and old[0] == n and old[1] not in ("site", ""):
                return redirect(url_for("home", n=n), code=303)
            if not web_problem and old and old[0] == n:
                if pilot:
                    return {"sample": flags[n-1]}
                return redirect(url_for("home", n=n))
            if not pilot and old and request.form.get("replace") != str(old[0]):
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
            if pilot:
                expiry = float(result["expires"])
                if web_problem:
                    if result.get("web") is not True or not time.time() < expiry <= time.time()+1810:
                        raise ValueError("Invalid web environment")
                    instance = secrets.token_urlsafe(24)
                    db.execute("INSERT OR REPLACE INTO environments VALUES (?,?,?,?)", (player,n,instance,expiry))
                    return redirect(url_for("home", n=n), code=303)
                sample = result["sample"]
                if sample != flags[n-1] or not time.time() < expiry <= time.time()+1800:
                    raise ValueError("Invalid test fixture")
                db.execute("INSERT OR REPLACE INTO environments VALUES (?,?,?,?)", (player,n,"",expiry))
                return {"sample": sample}
            link, expires = result["url"], float(result["expires"])
            if urlsplit(link).scheme not in ("http","https") or not urlsplit(link).hostname or not time.time() < expires < time.time()+1810:
                raise ValueError()
            db.execute("INSERT OR REPLACE INTO environments VALUES (?,?,?,?)", (player,n,link,expires))
    except (URLError, OSError, ValueError, TypeError, KeyError, sqlite3.OperationalError):
        if pilot:
            return {"error": "테스트 환경을 시작하지 못했습니다."}, 503
        flash("환경을 준비하지 못했습니다. 잠시 후 다시 시도해 주세요.")
    return redirect(url_for("home", n=n))
