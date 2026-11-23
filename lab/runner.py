"""Pilot runner for trusted static fixtures. Each active slot owns one process."""
import hmac
import multiprocessing
import os
import re
import threading
import time
from pathlib import Path

from flask import Flask, abort, request

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 2048
ROOT = Path(__file__).resolve().parent.parent / "challenges"
TOKEN = os.environ["CTF_RUNNER_TOKEN"]
slots = {}
lock = threading.Lock()
ctx = multiprocessing.get_context("spawn")


def fixture_worker(channel, fixture):
    # Keep the selected fixture isolated from the other fixture processes.
    try:
        flag = fixture.read_text().strip()
        while channel.poll(1800):
            channel.recv()
            channel.send(flag)
    except EOFError:
        pass
    finally:
        channel.close()


def remove(player):
    _, proc, channel, _ = slots.pop(player)
    channel.close()
    proc.terminate()
    proc.join()


def reap():
    with lock:
        for player, (_, proc, _, expiry) in list(slots.items()):
            if expiry <= time.time() or not proc.is_alive():
                remove(player)


def sweep():
    while True:
        time.sleep(10)
        reap()


@app.put("/environments/<player>")
def start(player):
    if not hmac.compare_digest(request.headers.get("Authorization", "").encode(), ("Bearer " + TOKEN).encode()):
        abort(403)
    if not re.fullmatch(r"[a-f0-9]{48}", player):
        abort(400)
    data = request.get_json()
    n = data.get("problem") if isinstance(data, dict) else None
    if type(n) is not int or not 1 <= n <= 15:
        abort(400)
    reap()
    with lock:
        if player in slots and slots[player][0] != n:
            remove(player)
        if player not in slots:
            if len(slots) >= 16:
                abort(503)
            parent, child = ctx.Pipe()
            proc = ctx.Process(target=fixture_worker, args=(child, ROOT / f"{n:02}" / "flag.txt"), daemon=True)
            proc.start()
            child.close()
            slots[player] = (n, proc, parent, time.time() + 1800)
        _, proc, channel, expiry = slots[player]
        try:
            channel.send("read")
            if not channel.poll(2):
                raise TimeoutError()
            flag = channel.recv()
        except (EOFError, OSError):
            remove(player)
            abort(503)
        return {"sample": flag, "expires": expiry}


if __name__ == "__main__":
    from waitress import serve
    threading.Thread(target=sweep, daemon=True).start()
    serve(app, host="127.0.0.1", port=9011)
