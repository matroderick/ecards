#!/usr/bin/env python3
"""Import an existing cards.json person into the service DB (used for the demo account).
   python3 import_cards.py cards.json mat you@example.com [--replace]
Emails ending in .invalid make a card nobody can sign in to (used for the demo), without a mail alias."""
import json, shutil, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from farlib import *
import render

src, pid, email = Path(sys.argv[1]), sys.argv[2], sys.argv[3].lower()
replace = "--replace" in sys.argv[4:]
cfg = json.loads(src.read_text())["people"][pid]
if handle_error(pid) and pid not in ("mat", "demo"):
    sys.exit("handle problem: " + handle_error(pid))
db = init_db()
if replace:
    old = db.execute("select id from users where handle=?", (pid,)).fetchone()
    if old:
        import shutil as _sh
        for d in (Path(USERS_ROOT) / pid, Path(ASSETS) / str(old["id"]), Path(LOG_ROOT) / pid):
            _sh.rmtree(d, ignore_errors=True)
        db.execute("delete from users where id=?", (old["id"],)); db.commit()
if db.execute("select 1 from users where handle=? or email=?", (pid, email)).fetchone():
    sys.exit("handle or email already exists")
personas = {}
for key, p in cfg["personas"].items():
    q = {k: v for k, v in p.items() if k not in ("photo", "logo")}
    if "booking" not in q and cfg.get("booking"):
        q["booking"] = {"url": cfg["booking"]} if isinstance(cfg["booking"], str) else cfg["booking"]
    personas[key] = q
data = {"default": cfg.get("default"), "personas": personas}
uid = db.execute("insert into users(email,handle,name,cfg,terms_at,created) values(?,?,?,?,?,?)",
                 (email, pid, cfg["name"], json.dumps(data), int(time.time()), int(time.time()))).lastrowid
if not email.endswith(".invalid"):
    db.execute("update users set mail_on=1, mail_fwd=? where id=?", (email, uid))  # existing ImprovMX alias <handle>@<domain> is left untouched
db.commit()
for key, p in cfg["personas"].items():
    d = render.asset_dir(uid, key); d.mkdir(parents=True, exist_ok=True)
    if p.get("photo"):
        shutil.copyfile(src.parent / p["photo"], d / "photo.jpg")
    if p.get("logo"):
        lp = src.parent / p["logo"]; shutil.copyfile(lp, d / ("logo" + lp.suffix.lower()))
u = {"id": uid, "handle": pid, "name": cfg["name"], "cfg": data, "status": "active"}
render.render_user(u)
print("imported %s (%d cards) -> %s/%s" % (pid, len(personas), USERS_ROOT, pid))
