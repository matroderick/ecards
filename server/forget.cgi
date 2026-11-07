#!/usr/bin/env python3
# "Forget me": POST deletes every visitor-log line recorded for the caller's own IP address, on this card owner's site only.
import os, sys, json, glob, tempfile

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import farlib
ip = os.environ.get("REMOTE_ADDR", "")
tenant = farlib.tenant_row(os.environ.get("HTTP_HOST", ""))
LOG_DIR = os.path.join(farlib.LOG_ROOT, tenant["handle"]) if tenant else "/nonexistent"
if os.environ.get("REQUEST_METHOD") != "POST" or not ip or not tenant:
    sys.stdout.write("Status: 405 Method Not Allowed\nCache-Control: no-store\n\n")
    sys.exit()
deleted = 0
for fn in glob.glob(os.path.join(LOG_DIR, "*.jsonl")):
    keep, drop = [], 0
    try:
        with open(fn, "rb") as f:
            for line in f:
                try:
                    if json.loads(line).get("ip") == ip:
                        drop += 1
                        continue
                except Exception:
                    pass
                keep.append(line)
        if not drop:
            continue
        fd, tmp = tempfile.mkstemp(dir=LOG_DIR)
        with os.fdopen(fd, "wb") as o:
            o.writelines(keep)
        os.chmod(tmp, 0o640)
        os.replace(tmp, fn)
        deleted += drop
    except Exception:
        pass
sys.stdout.write("Content-Type: application/json\nCache-Control: no-store\n\n" + json.dumps({"deleted": deleted}))
