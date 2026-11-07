#!/usr/bin/env python3
"""Local test harness: app.<base> -> WSGI app, <handle>.<base> -> static card files + /api/*.cgi (emulates Apache)."""
import os, sys, io, subprocess, mimetypes, socketserver, http.server
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import farlib, app as farapp
CGI_DIR = HERE.parent / "server"
PORT = int(os.environ.get("FAR_DEV_PORT", "8771"))


class H(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"
    def log_message(self, *a): pass

    def host(self):
        return (self.headers.get("Host") or "").split(":")[0].lower()

    def do_GET(self): self.go()
    def do_POST(self): self.go()

    def go(self):
        h = self.host()
        if h == farlib.APP_HOST:
            return self.wsgi()
        t = farlib.tenant_from_host(h)
        if h == farlib.BASE:   # apex = landing page
            t = None
            path = self.path.split("?")[0]
            if path.startswith("/api/") and path.endswith(".cgi"):
                return self.cgi(path.rsplit("/", 1)[1])
            import build_landing
            data = build_landing.render((Path(__file__).parent / "landing" / "index.tmpl.html").read_text()).encode()
            self.send_response(200); self.send_header("Content-Type", "text/html"); self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)
            return
        if not t:
            return self.send_error(404)
        path = self.path.split("?")[0]
        if path.startswith("/api/") and path.endswith(".cgi"):
            return self.cgi(path.rsplit("/", 1)[1])
        root = Path(farlib.USERS_ROOT) / t
        rel = path.lstrip("/")
        f = (root / rel).resolve()
        if not str(f).startswith(str(root.resolve())):
            return self.send_error(403)
        if f.is_dir():
            f = f / "index.html"
        if not f.exists():
            return self.send_error(404)
        data = f.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", mimetypes.guess_type(str(f))[0] or "application/octet-stream")
        self.send_header("Cache-Control", "no-store"); self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)

    def body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(n) if n else b""

    def wsgi(self):
        body = self.body()
        p, _, q = self.path.partition("?")
        env = {"REQUEST_METHOD": self.command, "PATH_INFO": p, "QUERY_STRING": q, "CONTENT_LENGTH": str(len(body)),
               "CONTENT_TYPE": self.headers.get("Content-Type", ""), "wsgi.input": io.BytesIO(body), "REMOTE_ADDR": "127.0.0.1",
               "HTTP_COOKIE": self.headers.get("Cookie", ""), "HTTP_HOST": self.headers.get("Host", ""), "HTTP_USER_AGENT": self.headers.get("User-Agent", ""), "HTTP_ACCEPT_LANGUAGE": self.headers.get("Accept-Language", "")}
        if self.headers.get("X-Test-IP"):
            env["HTTP_X_FORWARDED_FOR"] = self.headers["X-Test-IP"]
        out = {}
        def start(status, headers): out["s"], out["h"] = status, headers
        chunks = farapp.app(env, start)
        data = b"".join(chunks)
        self.send_response(int(out["s"].split()[0]))
        for k, v in out["h"]:
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)

    def cgi(self, name):
        if name not in ("hit.cgi", "log.cgi", "loc.cgi", "forget.cgi"):
            return self.send_error(404)
        body = self.body()
        env = dict(os.environ, REQUEST_METHOD=self.command, CONTENT_LENGTH=str(len(body)), HTTP_HOST=self.headers.get("Host", ""),
                   REMOTE_ADDR=self.headers.get("X-Test-IP", "127.0.0.1"), HTTP_USER_AGENT=self.headers.get("User-Agent", ""),
                   HTTP_ACCEPT_LANGUAGE=self.headers.get("Accept-Language", ""), HTTP_REFERER=self.headers.get("Referer", ""),
                   PYTHONPATH=str(HERE))
        out = subprocess.run(["python3", str(CGI_DIR / name)], input=body, env=env, capture_output=True).stdout
        head, _, b = out.partition(b"\n\n"); code = 200; hs = []
        for l in head.decode().split("\n"):
            if l.startswith("Status:"): code = int(l.split()[1])
            elif ": " in l: hs.append(l.split(": ", 1))
        self.send_response(code)
        for k, v in hs: self.send_header(k, v)
        self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)


class S(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True; allow_reuse_address = True

if __name__ == "__main__":
    farlib.init_db().close()
    S(("127.0.0.1", PORT), H).serve_forever()
