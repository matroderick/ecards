#!/usr/bin/env python3
# Visit beacon from the cards. POST (JSON text) -> one line appended to LOG_ROOT/<handle>/YYYY-MM-DD.jsonl (not web-readable).
# The log folder comes from the Host header: <handle>.<base domain> -> <handle>, <base domain> -> _site (landing page), demo -> _demo; unknown or suspended hosts are ignored.
import os, sys, json, time, hashlib, random, re
sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import farlib

RETAIN_DAYS = 180
MAX_BODY = 6000
DAY_CAP = 5 * 1024 * 1024
TYPES = {"view", "click", "end", "copy"}
KEYS = {"t", "card", "pv", "ref", "q", "lang", "tz", "tzo", "scr", "vp", "dpr", "dark", "rm", "touch", "plat",
        "mem", "cores", "net", "dl", "sd", "sa", "nav", "hist", "load", "ch", "path",
        "k", "href", "txt", "dir", "sel", "dur", "smax", "n"}


def done(code="204 No Content"):
    sys.stdout.write("Status: %s\nCache-Control: no-store\n\n" % code)
    sys.exit()


def clean(v, depth=0):
    if isinstance(v, str):
        return v[:300]
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, (int, float)):
        return v
    if isinstance(v, list) and depth < 2:
        return [clean(x, depth + 1) for x in v[:12]]
    if isinstance(v, dict) and depth < 2:
        return {str(k)[:20]: clean(x, depth + 1) for k, x in list(v.items())[:12]}
    return None


env = os.environ.get
if env("REQUEST_METHOD") != "POST":
    done()
name = farlib.log_name(env("HTTP_HOST", ""))
if not name:
    done()
try:
    n = min(int(env("CONTENT_LENGTH") or 0), MAX_BODY)
    o = json.loads(sys.stdin.read(n))
    assert isinstance(o, dict)
except Exception:
    done("400 Bad Request")
if o.get("t") not in TYPES or not re.fullmatch(r"[a-z0-9/_-]{1,40}", str(o.get("card", ""))):
    done("400 Bad Request")
rec = {k: clean(v) for k, v in o.items() if k in KEYS}
ip = env("REMOTE_ADDR", "")
ua = env("HTTP_USER_AGENT", "")[:300]
rec.update({"ts": int(time.time()), "ip": ip, "ua": ua, "al": env("HTTP_ACCEPT_LANGUAGE", "")[:100],
            "rh": env("HTTP_REFERER", "")[:200],
            "vid": hashlib.sha256(("%s|%s|%s|%s" % (name, ip, ua, time.strftime("%Y-%m"))).encode()).hexdigest()[:10]})
g = farlib.geo(ip)
if g:
    rec["geo"] = g
log_dir = os.path.join(farlib.LOG_ROOT, name)
os.makedirs(log_dir, mode=0o750, exist_ok=True)
fn = os.path.join(log_dir, time.strftime("%Y-%m-%d", time.gmtime()) + ".jsonl")
if os.path.exists(fn) and os.path.getsize(fn) > DAY_CAP:
    done()
fd = os.open(fn, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o640)
os.write(fd, (json.dumps(rec, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8"))
os.close(fd)
if random.random() < 0.02:  # housekeeping: drop this owner's files older than RETAIN_DAYS
    cutoff = time.time() - RETAIN_DAYS * 86400
    for f in os.listdir(log_dir):
        p = os.path.join(log_dir, f)
        if f.endswith(".jsonl") and os.path.getmtime(p) < cutoff:
            os.remove(p)
done()
