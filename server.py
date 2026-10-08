#!/usr/bin/env python3
"""Общая база для Telegram Mini App «Учёт рекламы». Только стандартная библиотека Python."""
import os, json, hmac, hashlib, time, threading, re
from urllib.parse import parse_qsl, urlparse, parse_qs
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

BOT_TOKEN = os.environ["BOT_TOKEN"].strip()
HOST = os.environ.get("HOST", "127.0.0.1")
PORT = int(os.environ.get("PORT", "8787"))
MAX_USERS = int(os.environ.get("MAX_USERS", "2"))          # сколько аккаунтов пускать
ALLOWED = [int(x) for x in os.environ.get("ALLOWED_IDS", "").replace(" ", "").split(",") if x]
DIR = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(DIR, "data.json")
LOCK = threading.Lock()
SECRET = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def load():
    try:
        with open(DATA, encoding="utf-8") as f:
            d = json.load(f)
    except Exception:
        d = {}
    d.setdefault("users", [])
    d.setdefault("items", {})
    return d


def save(d):
    tmp = DATA + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False)
    os.replace(tmp, DATA)


def verify(init_data):
    """Проверяет подпись Telegram и возвращает id пользователя или None."""
    if not init_data:
        return None
    pairs = dict(parse_qsl(init_data, keep_blank_values=True))
    got = pairs.pop("hash", None)
    if not got:
        return None
    check = "\n".join("%s=%s" % (k, pairs[k]) for k in sorted(pairs))
    calc = hmac.new(SECRET, check.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calc, got):
        return None
    try:
        if time.time() - int(pairs.get("auth_date", "0")) > 30 * 86400:
            return None
        return int(json.loads(pairs.get("user", "{}")).get("id"))
    except Exception:
        return None


def allowed(uid, d):
    if ALLOWED:
        return uid in ALLOWED
    if uid in d["users"]:
        return True
    if len(d["users"]) < MAX_USERS:      # первые два аккаунта занимают места
        d["users"].append(uid)
        return True
    return False


class H(BaseHTTPRequestHandler):
    server_version = "adtracker"

    def log_message(self, *a):
        pass

    def send(self, code, body=b"", ctype="application/json", extra=None):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False).encode()
        elif isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype + ("; charset=utf-8" if ctype.startswith("text") or ctype == "application/json" else ""))
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def auth(self, d):
        uid = verify(self.headers.get("X-Init-Data", ""))
        if uid is None:
            self.send(401, {"error": "unauthorized"})
            return None
        if not allowed(uid, d):
            self.send(403, {"error": "forbidden"})
            return None
        return uid

    def do_GET(self):
        u = urlparse(self.path)
        if u.path in ("/", "/index.html"):
            try:
                with open(os.path.join(DIR, "index.html"), "rb") as f:
                    return self.send(200, f.read(), "text/html")
            except OSError:
                return self.send(500, "index.html not found", "text/plain")
        if u.path == "/api/items":
            with LOCK:
                d = load()
                if self.auth(d) is None:
                    return
                save(d)
                return self.send(200, {"items": list(d["items"].values())})
        self.send(404, {"error": "not found"})

    def do_PUT(self):
        u = urlparse(self.path)
        if u.path != "/api/item":
            return self.send(404, {"error": "not found"})
        try:
            n = int(self.headers.get("Content-Length", "0"))
            if n <= 0 or n > 20000:
                return self.send(413, {"error": "bad size"})
            rec = json.loads(self.rfile.read(n))
            if not isinstance(rec, dict) or not ID_RE.match(str(rec.get("id", ""))):
                return self.send(400, {"error": "bad record"})
        except Exception:
            return self.send(400, {"error": "bad json"})
        with LOCK:
            d = load()
            uid = self.auth(d)
            if uid is None:
                return
            rec["updatedAt"] = int(time.time())
            rec["by"] = uid
            d["items"][rec["id"]] = rec
            save(d)
        self.send(200, {"ok": True})

    def do_DELETE(self):
        u = urlparse(self.path)
        if u.path != "/api/item":
            return self.send(404, {"error": "not found"})
        iid = (parse_qs(u.query).get("id") or [""])[0]
        if not ID_RE.match(iid):
            return self.send(400, {"error": "bad id"})
        with LOCK:
            d = load()
            if self.auth(d) is None:
                return
            d["items"].pop(iid, None)
            save(d)
        self.send(200, {"ok": True})


if __name__ == "__main__":
    ThreadingHTTPServer((HOST, PORT), H).serve_forever()
