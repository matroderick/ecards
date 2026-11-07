#!/usr/bin/env python3
# POST token=...&days=30  ->  JSON of this card owner's logged events (for /log). Token: derived per user (farlib.derive).
import os, sys, json, time, hmac
from urllib.parse import parse_qs

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import farlib
MAX_EVENTS = 60000


def reply(code, body, ctype="text/plain"):
    sys.stdout.write("Status: %s\nContent-Type: %s\nCache-Control: no-store\n\n%s" % (code, ctype, body))
    sys.exit()


if os.environ.get("REQUEST_METHOD") != "POST":
    reply("405 Method Not Allowed", "POST only")
f = parse_qs(sys.stdin.read(min(int(os.environ.get("CONTENT_LENGTH") or 0), 2048)))
g = lambda k: (f.get(k, [""])[0]).strip()[:200]
tenant = farlib.tenant_row(os.environ.get("HTTP_HOST", ""))
if not tenant:
    reply("404 Not Found", "no such card")
if not farlib.check_token(g("token"), tenant["handle"], "log", tenant["log_ver"]):
    time.sleep(1)
    reply("403 Forbidden", "bad token")
LOG_DIR = os.path.join(farlib.LOG_ROOT, tenant["handle"])
try:
    days = max(1, min(int(g("days") or 30), 365))
except ValueError:
    days = 30
cutoff = time.strftime("%Y-%m-%d", time.gmtime(time.time() - days * 86400))
events = []
try:
    files = sorted(x for x in os.listdir(LOG_DIR) if x.endswith(".jsonl") and x[:10] >= cutoff)
except OSError:
    files = []
for name in files:
    with open(os.path.join(LOG_DIR, name), encoding="utf-8") as fh:
        for line in fh:
            try:
                events.append(json.loads(line))
            except ValueError:
                pass
events = events[-MAX_EVENTS:]
try:
    import maxminddb  # noqa
    has_geo = os.path.exists(os.environ.get("FAR_GEO_CITY", "/usr/share/GeoIP/dbip-city-lite.mmdb"))
except ImportError:
    has_geo = False
reply("200 OK", json.dumps({"you": os.environ.get("REMOTE_ADDR", ""), "now": int(time.time()), "days": days,
                            "geo": has_geo, "events": events}, ensure_ascii=False), "application/json")
