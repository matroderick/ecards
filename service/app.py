#!/usr/bin/env python3
"""ecards service: signup (magic link), dashboard, persona editor, QR/photo cards, reports, admin.
Pure standard library + Pillow. WSGI; run with `python3 app.py` (binds 127.0.0.1:8780) behind Apache."""
import hashlib, html, io, json, os, re, secrets, shutil, smtplib, socket, sys, threading, time
from email.message import EmailMessage
from email.parser import BytesParser
from email.policy import HTTP as HTTP_POLICY
from http import cookies
from pathlib import Path
from urllib.parse import parse_qs, urlparse, quote

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from farlib import *
import render, cardimg, build, mailalias
from PIL import Image, ImageOps

ADMINS = {e.strip().lower() for e in os.environ.get("FAR_ADMINS", "").split(",") if e.strip()}
MAIL_FROM = os.environ.get("FAR_MAIL_FROM", "%s <login@%s>" % (SITE, BASE))
OUTBOX = os.environ.get("FAR_OUTBOX", "")          # dev: append emails to this file instead of sending
RENDER_LOCK = threading.Lock()
MAX_BODY = 12 * 1024 * 1024
MAX_PERSONAS, MAX_SOCIALS, MAX_COMPANY, MAX_LINKS = 6, 10, 6, 10
SOCIAL_TYPES = list(build.SOCIAL_LABELS)
SWATCHES = ["#2563eb", "#0f766e", "#16a34a", "#ca8a04", "#ea580c", "#dc2626", "#be185d", "#7c3aed", "#334155", "#000000", "#bef5f3", "#fde68a"]
esc = html.escape


# ------------------------------------------------------------------ helpers --
class Resp(Exception):
    def __init__(self, status="200 OK", body=b"", headers=None, ctype="text/html; charset=utf-8"):
        self.status, self.headers = status, [("Content-Type", ctype), ("Cache-Control", "no-store"),
            ("X-Content-Type-Options", "nosniff"), ("Referrer-Policy", "same-origin"), ("X-Frame-Options", "DENY")] + (headers or [])
        self.body = body if isinstance(body, bytes) else body.encode("utf-8")


def redirect(to, headers=None):
    return Resp("303 See Other", b"", [("Location", to)] + (headers or []))


def now():
    return int(time.time())


def sha(s):
    return hashlib.sha256(s.encode()).hexdigest()


def rl_ok(db, key, limit, window):
    t = now()
    db.execute("delete from rl where ts<?", (t - 86400,))
    db.execute("delete from login_tokens where exp<?", (t,))
    db.execute("delete from sessions where exp<?", (t,))
    n = db.execute("select count(*) from rl where k=? and ts>?", (key, t - window)).fetchone()[0]
    if n >= limit:
        return False
    db.execute("insert into rl(k,ts) values(?,?)", (key, t))
    db.commit()
    return True


def parse_multipart(ctype, body):
    msg = BytesParser(policy=HTTP_POLICY).parsebytes(b"Content-Type: " + ctype.encode() + b"\r\nMIME-Version: 1.0\r\n\r\n" + body)
    fields, files = {}, {}
    for part in msg.iter_parts():
        name = part.get_param("name", header="content-disposition")
        data = part.get_payload(decode=True) or b""
        if part.get_filename() is not None:
            if data:
                files[name] = data
        elif name:
            fields.setdefault(name, []).append(data.decode("utf-8", "replace"))
    return fields, files


class Req:
    def __init__(self, env):
        self.env = env
        self.method = env["REQUEST_METHOD"]
        self.path = env.get("PATH_INFO", "/")
        self.query = {k: v[0] for k, v in parse_qs(env.get("QUERY_STRING", "")).items()}
        ra = env.get("REMOTE_ADDR", "")
        xff = env.get("HTTP_X_FORWARDED_FOR", "")
        self.ip = xff.split(",")[0].strip() if xff and ra in ("127.0.0.1", "::1") else ra
        self.fields, self.files = {}, {}
        if self.method == "POST":
            n = int(env.get("CONTENT_LENGTH") or 0)
            if n > MAX_BODY:
                raise Resp("413 Payload Too Large", "Too large")
            raw = env["wsgi.input"].read(n)
            ct = env.get("CONTENT_TYPE", "")
            if ct.startswith("multipart/"):
                self.fields, self.files = parse_multipart(ct, raw)
            else:
                self.fields = parse_qs(raw.decode("utf-8", "replace"), keep_blank_values=True)
        c = cookies.SimpleCookie(env.get("HTTP_COOKIE", ""))
        self.sid = c["far_sid"].value if "far_sid" in c else ""
        self.user = None
        self.session = None

    def f(self, k, default="", n=400):
        v = self.fields.get(k)
        return (v[0].strip()[:n]) if v else default

    def fl(self, k, n=400):
        return [x.strip()[:n] for x in self.fields.get(k, [])]

    def flag(self, k):
        return k in self.fields


def cookie_hdr(sid, max_age):
    sec = "; Secure" if SCHEME == "https" else ""
    return ("Set-Cookie", "far_sid=%s; Path=/; HttpOnly; SameSite=Lax; Max-Age=%d%s" % (sid, max_age, sec))


class _SMTP4(smtplib.SMTP):
    """SMTP over IPv4 only (the VPS's IPv6 route to some mail hosts hangs)."""
    def _get_socket(self, host, port, timeout):
        ip = socket.getaddrinfo(host, port, socket.AF_INET, socket.SOCK_STREAM)[0][4][0]
        return socket.create_connection((ip, port), timeout)


class _SMTP4_SSL(smtplib.SMTP_SSL):
    def _get_socket(self, host, port, timeout):
        ip = socket.getaddrinfo(host, port, socket.AF_INET, socket.SOCK_STREAM)[0][4][0]
        return self.context.wrap_socket(socket.create_connection((ip, port), timeout), server_hostname=host)


def send_mail(to, subject, body):
    if OUTBOX:
        with open(OUTBOX, "a") as f:
            f.write("TO: %s\nSUBJECT: %s\n\n%s\n----\n" % (to, subject, body))
        return
    host = os.environ.get("FAR_SMTP_HOST")
    if not host:
        print("[mail disabled] to=%s subject=%s\n%s" % (to, subject, body), file=sys.stderr)
        return
    m = EmailMessage(); m["From"] = MAIL_FROM; m["To"] = to; m["Subject"] = subject; m.set_content(body)
    port = int(os.environ.get("FAR_SMTP_PORT", "465"))
    cls = _SMTP4_SSL if port == 465 else _SMTP4
    with cls(host, port, timeout=20) as s:
        if port != 465:
            s.starttls()
        if os.environ.get("FAR_SMTP_USER"):
            s.login(os.environ["FAR_SMTP_USER"], os.environ.get("FAR_SMTP_PASS", ""))
        s.send_message(m)


# ------------------------------------------------------------- validation ----
URL_RE = re.compile(r"https?://[^\s<>\"'`]{3,300}", re.I)
EMAIL_RE = re.compile(r"[^@\s<>\"',;]{1,64}@[^@\s<>\"',;]{1,120}\.[a-z]{2,24}", re.I)
PHONE_RE = re.compile(r"\+?[0-9 ()\-.]{5,25}")
COLOR_RE = re.compile(r"#[0-9a-fA-F]{6}")


def clean_url(v, errs, label):
    v = (v or "").strip()
    if not v:
        return ""
    if not re.match(r"[a-z][a-z0-9+.-]*:", v, re.I):
        v = "https://" + v
    if not URL_RE.fullmatch(v) or "." not in urlparse(v).netloc:
        errs.append("%s: that doesn't look like a web address." % label)
        return ""
    return v


def process_photo(data):
    im = Image.open(io.BytesIO(data))
    im = ImageOps.exif_transpose(im)
    if im.width * im.height > 60_000_000:
        raise ValueError("image too large")
    im = ImageOps.fit(im.convert("RGB"), (256, 256), Image.LANCZOS)
    for q in (88, 80, 70, 60):
        b = io.BytesIO(); im.save(b, "JPEG", quality=q, optimize=True)
        if b.tell() < 60_000:
            break
    return b.getvalue()


def process_logo(data):
    im = Image.open(io.BytesIO(data))
    if im.width * im.height > 60_000_000:
        raise ValueError("image too large")
    im = ImageOps.exif_transpose(im).convert("RGBA")
    im.thumbnail((600, 300), Image.LANCZOS)
    b = io.BytesIO(); im.save(b, "PNG", optimize=True)
    return b.getvalue()


def build_persona(req, existing, errs):
    """Form -> persona dict (only whitelisted keys; unknown keys of `existing` are kept)."""
    p = dict(existing or {})
    p["label"] = req.f("label", "Card", 24) or "Card"
    for k, n in (("org", 60), ("title", 60), ("note", 160)):
        v = req.f(k, "", n)
        p.pop(k, None) if not v else p.__setitem__(k, v)
    ph = req.f("phone", "", 25)
    if ph and not PHONE_RE.fullmatch(ph):
        errs.append("Phone: use digits, spaces and + ( ) - only."); ph = ""
    p.pop("phone", None) if not ph else p.__setitem__("phone", ph)
    em = req.f("email", "", 120)
    if em and not EMAIL_RE.fullmatch(em):
        errs.append("Email: that doesn't look like an email address."); em = ""
    p.pop("email", None) if not em else p.__setitem__("email", em)
    web = clean_url(req.f("url"), errs, "Website")
    p.pop("url", None) if not web else p.__setitem__("url", web)
    bk = clean_url(req.f("booking"), errs, "Booking link")
    p.pop("booking", None)
    if bk:
        p["booking"] = {"url": bk, "label": req.f("booking_label", "Book a meeting", 30) or "Book a meeting"}
    acc = req.f("accent", "#2563eb", 7)
    if not COLOR_RE.fullmatch(acc):
        errs.append("Colour: pick a colour like #2563eb."); acc = p.get("accent", "#2563eb")
    p["accent"] = acc.lower()
    for k in ("on_accent", "banner", "accent_dark"):
        p.pop(k, None)
    p["hidden"] = req.flag("hidden")
    p["no_location"] = req.flag("no_location")
    if not p["hidden"]: p.pop("hidden")
    if not p["no_location"]: p.pop("no_location")

    def rows(prefix, kinds, cap, with_label=False):
        out = []
        types, urls = req.fl(prefix + "_type"), req.fl(prefix + "_url", 300)
        labels = req.fl(prefix + "_label", 40)
        for i, u in enumerate(urls):
            if not u:
                continue
            if len(out) >= cap:
                errs.append("Too many %s links (max %d)." % (prefix, cap)); break
            url = clean_url(u, errs, "Link")
            if not url:
                continue
            if not url.lower().startswith("https://") and prefix != "link":
                errs.append("Social links must start with https://"); continue
            row = {"url": url}
            if kinds:
                t = types[i] if i < len(types) else ""
                if t not in kinds:
                    errs.append("Pick a network for %s." % url); continue
                row["type"] = t
            if with_label:
                lab = labels[i] if i < len(labels) else ""
                if not lab and not kinds:
                    lab = urlparse(url).netloc
                if lab:
                    row["label"] = lab
            out.append(row)
        return out

    for key, kinds, cap, wl in (("social", SOCIAL_TYPES, MAX_SOCIALS, False), ("company", SOCIAL_TYPES, MAX_COMPANY, True), ("link", None, MAX_LINKS, True)):
        res = rows(key, kinds, cap, wl)
        dest = {"social": "socials", "company": "company_links", "link": "links"}[key]
        p.pop(dest, None)
        if res:
            p[dest] = res
    return p


def save_assets(uid, slug, req, errs, persist=True):
    """Return (photo_bytes|None, logo_bytes|None, remove_logo) after validating uploads."""
    photo = logo = None
    if "photo" in req.files:
        try: photo = process_photo(req.files["photo"])
        except Exception: errs.append("Photo: couldn't read that image (use JPG, PNG or WebP).")
    if "logo" in req.files:
        try: logo = process_logo(req.files["logo"])
        except Exception: errs.append("Logo: couldn't read that image (use PNG, JPG or WebP).")
    rm = req.flag("remove_logo")
    if persist and not errs:
        d = render.asset_dir(uid, slug); d.mkdir(parents=True, exist_ok=True)
        if photo: (d / "photo.jpg").write_bytes(photo)
        if req.flag("remove_photo") and not photo: (d / "photo.jpg").unlink(missing_ok=True)
        if logo or rm:
            for ext in (".png", ".jpg", ".webp", ".svg"): (d / ("logo" + ext)).unlink(missing_ok=True)
        if logo: (d / "logo.png").write_bytes(logo)
    return photo, logo, rm


# ------------------------------------------------------------------- views ---
CSS = """
:root{--bg:#f4f5f7;--card:#fff;--text:#14171c;--muted:#5b6470;--line:#e3e6ea;--ink:#14171c;--on-ink:#fff;--accent:#2563eb;--bad:#b91c1c;--ok:#15803d}
@media(prefers-color-scheme:dark){:root{--bg:#0f1115;--card:#171a20;--text:#eceef2;--muted:#9aa3af;--line:#262b33;--ink:#eceef2;--on-ink:#0f1115;--accent:#6aa0ff;--bad:#f87171;--ok:#4ade80}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:16px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
a{color:var(--accent)}h1{font-size:26px;margin:0 0 6px;letter-spacing:-.01em}h2{font-size:18px;margin:28px 0 10px}
header.top{display:flex;align-items:center;gap:14px;padding:14px 20px;border-bottom:1px solid var(--line);background:var(--card)}
header.top b{font:600 15px/1 ui-monospace,Menlo,monospace;letter-spacing:.06em;text-transform:uppercase}header.top b a{font:inherit;color:inherit}header.top .sp{flex:1}header.top a{color:var(--muted);text-decoration:none;font-size:14px}
main{max-width:980px;margin:0 auto;padding:22px 16px 60px}main.narrow{max-width:460px}
.panel{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:18px;margin:0 0 14px}
label{display:block;font-size:13px;font-weight:600;color:var(--muted);margin:12px 0 4px}
input[type=text],input[type=email],input[type=url],input[type=tel],select,textarea{width:100%;padding:10px 12px;border-radius:10px;border:1px solid var(--line);background:var(--bg);color:var(--text);font:inherit}
input:focus,select:focus,textarea:focus{outline:2px solid var(--accent);outline-offset:0}
button,.btn{display:inline-block;padding:10px 16px;border-radius:10px;border:1px solid var(--line);background:var(--card);color:var(--text);font:600 14px/1.2 inherit;cursor:pointer;text-decoration:none}
button.primary,.btn.primary{background:var(--ink);color:var(--on-ink);border-color:var(--ink)}
button.danger{color:var(--bad);border-color:var(--bad)}button.small,.btn.small{padding:6px 10px;font-size:13px}
.row{display:flex;gap:8px;flex-wrap:wrap;align-items:center}.row.end{justify-content:flex-end}
.muted{color:var(--muted);font-size:14px}.err{color:var(--bad);font-size:14px;margin:8px 0}.ok{color:var(--ok);font-size:14px}
.persona{display:flex;gap:14px;align-items:center;flex-wrap:wrap}.persona .sw{width:36px;height:36px;border-radius:50%;flex:none;border:1px solid var(--line)}
.persona .meta{flex:1;min-width:180px}.persona .meta b{display:block}.tag{font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.06em;background:var(--ink);color:var(--on-ink);border-radius:6px;padding:2px 6px;margin-left:6px}
.grid{display:grid;grid-template-columns:minmax(0,1fr) 380px;gap:24px;align-items:start}@media(max-width:860px){.grid{grid-template-columns:1fr}}
.preview{position:sticky;top:12px}.preview iframe{width:100%;max-width:380px;height:720px;border:1px solid var(--line);border-radius:22px;background:var(--bg);display:block;margin:0 auto}
.rowset .r{display:grid;grid-template-columns:130px 1fr auto;gap:6px;margin-bottom:6px}.rowset.co .r{grid-template-columns:110px 1fr 120px auto}.rowset.ln .r{grid-template-columns:130px 1fr auto}
.swatches{display:flex;gap:8px;flex-wrap:wrap;margin-top:6px}.swatches button{width:28px;height:28px;border-radius:50%;padding:0;border:2px solid var(--card);box-shadow:0 0 0 1px var(--line)}
table{width:100%;border-collapse:collapse;font-size:14px}th,td{text-align:left;padding:8px 6px;border-bottom:1px solid var(--line);vertical-align:top}
code,.mono{font:13px ui-monospace,Menlo,monospace;word-break:break-all}.hero{padding:30px 0 10px}
"""


def layout(title, body, user=None, narrow=False, csrf="", extra_head=""):
    nav = ""
    if user:
        nav = ('<a href="/dashboard">Dashboard</a>%s<form method="post" action="/logout" style="margin:0"><input type="hidden" name="csrf" value="%s">'
               '<button class="small">Sign out</button></form>' % ('<a href="/admin">Admin</a>' if user["email"].lower() in ADMINS else "", esc(csrf)))
    banner = ('<div style="background:#fde68a;color:#3b2f00;text-align:center;padding:8px 12px;font-size:14px">Demo mode: sample data, changes aren\'t saved. '
              '<a href="/" style="color:inherit">Sign up free</a></div>' if user and user.get("demo") else "")
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            '<meta name="robots" content="noindex"><title>%s – %s</title><style>%s</style>%s</head><body>'
            '%s<header class="top"><b><a href="%s" style="color:inherit;text-decoration:none">%s</a></b><span class="sp"></span>%s</header>'
            '<main%s>%s</main></body></html>' % (esc(title), esc(SITE), CSS, extra_head, banner, "%s://%s%s/" % (SCHEME, BASE, PORT), esc(SITE), nav, ' class="narrow"' if narrow else "", body))



def login_page(msg="", email=""):
    return layout("Sign in", """
<div class="hero"><h1>Your digital business card</h1><p class="muted">Pick a name, add your details, share a QR code. Free, by invitation while in beta. No password – we email you a sign-in link.</p></div>
<form method="post" action="/login" class="panel"><label for="e">Email</label><input id="e" type="email" name="email" value="%s" required autocomplete="email" autofocus>
<div class="row" style="margin-top:14px"><button class="primary">Email me a link</button></div>%s
<p style="margin:14px 0 0"><a href="/request">Need an invite? Request one →</a></p>
<p style="margin:10px 0 0"><a href="/demo">Just looking? Sign in to the demo →</a><br><span class="muted">Sample data, no email needed.</span></p>
<p class="muted" style="margin:14px 0 0">By continuing you agree to the <a href="/terms">Terms</a> and <a href="/privacy">Privacy notice</a>.</p></form>""" % (esc(email), msg), narrow=True)


def persona_row(slug, p, u, i, n, dflt, csrf):
    url = card_origin(u["handle"]) + "/%s/" % slug
    return """<div class="panel persona"><div class="sw" style="background:%(acc)s"></div>
<div class="meta"><b>%(label)s%(tag)s</b><a class="muted" href="%(url)s" target="_blank" rel="noopener">%(show)s</a>%(hid)s</div>
<div class="row"><a class="btn small" href="/edit/%(slug)s">Edit</a>
<a class="btn small" href="/card/%(slug)s.png" download="%(h)s-%(slug)s-card.png">Phone card</a>
<a class="btn small" href="/card/%(slug)s.pdf" download="%(h)s-%(slug)s-print.pdf">Print sheet</a>
<a class="btn small" href="/qr/%(slug)s.svg" download="%(h)s-%(slug)s-qr.svg">QR</a>
<form method="post" action="/persona/%(slug)s/move" class="row" style="margin:0"><input type="hidden" name="csrf" value="%(csrf)s">
<button class="small" name="d" value="up" %(du)s>↑</button><button class="small" name="d" value="down" %(dd)s>↓</button>%(mk)s</form></div></div>""" % {
        "acc": esc(p.get("accent", "#2563eb")), "label": esc(p.get("label", slug)), "slug": esc(slug), "h": u["handle"], "csrf": esc(csrf), "url": esc(url),
        "show": esc(url.split("://", 1)[1]), "tag": '<span class="tag">default</span>' if slug == dflt else "",
        "hid": ' <span class="muted">· hidden from the swipe order</span>' if p.get("hidden") else "",
        "du": "disabled" if i == 0 else "", "dd": "disabled" if i == n - 1 else "",
        "mk": "" if slug == dflt else '<button class="small" name="d" value="default">Make default</button>'}


def dashboard_page(u, csrf, flash=""):
    cfg = u["cfg"]; ps = cfg["personas"]; dflt = render.default_slug(cfg)
    rows = "".join(persona_row(k, v, u, i, len(ps), dflt, csrf) for i, (k, v) in enumerate(ps.items()))
    add = ('<a class="btn primary" href="/edit/new">Add a card</a>' if len(ps) < MAX_PERSONAS else '<span class="muted">Limit of %d cards reached.</span>' % MAX_PERSONAS)
    return layout("Dashboard", """
%(flash)s<h1>Your cards</h1><p class="muted">Your page: <a href="%(o)s" target="_blank" rel="noopener"><b>%(host)s</b></a>. Swipe left/right between cards.</p>
%(rows)s<div class="row" style="margin:14px 0">%(add)s</div>
<h2>Visitors</h2><div class="panel"><p class="muted" style="margin-top:0">See who opened your cards and which links they tapped. Entries are kept for 180 days.</p>
<div class="row"><a class="btn" href="/visitors" target="_blank">Open visitor log</a></div></div>
<h2>Email address</h2>%(mail)s
<h2>"Last seen" location</h2><div class="panel"><p class="muted" style="margin-top:0">Optional: an iPhone Shortcut can show a major city and "N hours ago" on your cards. Only the nearest major city is stored.</p>
<div class="row"><a class="btn" href="/location">Set up</a></div></div>
<h2>Account</h2><div class="panel"><form method="post" action="/account/name"><input type="hidden" name="csrf" value="%(csrf)s">
<label for="nm">Your name (shown on every card)</label><div class="row"><input id="nm" type="text" name="name" value="%(name)s" maxlength="60" style="max-width:320px" required>
<button>Save</button></div></form><p class="muted">Signed in as %(email)s</p>
<details><summary class="muted" style="cursor:pointer">Delete my account</summary><form method="post" action="/account/delete" style="margin-top:10px">
<input type="hidden" name="csrf" value="%(csrf)s"><p class="muted">This removes all your cards, uploads and visitor logs immediately. Type your handle (<b>%(h)s</b>) to confirm.</p>
<div class="row"><input type="text" name="confirm" style="max-width:220px" autocomplete="off"><button class="danger">Delete everything</button></div></form></details></div>
""" % {"flash": flash, "o": esc(card_origin(u["handle"])), "host": esc(card_origin(u["handle"]).split("://", 1)[1]), "rows": rows, "add": add,
       "csrf": esc(csrf), "name": esc(u["name"]), "email": esc(u["email"]), "h": esc(u["handle"]), "mail": mail_panel(u, csrf)}, user=u, csrf=csrf)


def mail_panel(u, csrf):
    addr = "%s@%s" % (u["handle"], BASE)
    if u["mail_on"]:
        state = ('<p style="margin-top:0"><b>%s</b> forwards to <b>%s</b>.</p><form method="post" action="/mail/disable" class="row" style="margin:0 0 10px">'
                 '<input type="hidden" name="csrf" value="%s"><button class="small danger">Turn off</button></form>' % (esc(addr), esc(u["mail_fwd"]), esc(csrf)))
    else:
        state = ('<p style="margin-top:0">Get <b>%s</b>: mail sent to it is forwarded to <b>%s</b>.</p><form method="post" action="/mail/enable" class="row" style="margin:0 0 10px">'
                 '<input type="hidden" name="csrf" value="%s"><button class="primary small">Turn on</button></form>' % (esc(addr), esc(u["mail_fwd"]), esc(csrf)))
    return ('<div class="panel">%s<p class="muted">Receive only: you can\'t send as this address. Forwarding is handled by ImprovMX.</p>'
            '<form method="post" action="/mail/forward"><input type="hidden" name="csrf" value="%s"><label for="fw">Forward to</label>'
            '<div class="row"><input id="fw" type="email" name="forward" value="%s" style="max-width:320px" maxlength="120" required><button class="small">Change</button></div>'
            '<p class="muted" style="margin-bottom:0">A different address needs a confirmation link sent to it first.</p></form></div>' % (state, esc(csrf), esc(u["mail_fwd"])))


def rowset_js():
    return """
<script>
(function(){var form=document.getElementById('f'),fr=document.getElementById('pv'),t=null,busy=false,again=false;
function typeOpts(){return %(types)s.map(function(x){return '<option value="'+x[0]+'">'+x[1]+'</option>'}).join('')}
document.querySelectorAll('[data-add]').forEach(function(b){b.addEventListener('click',function(){var set=document.getElementById(b.dataset.add);
 var tpl=set.dataset.tpl.replace('%%TYPES%%',typeOpts());var d=document.createElement('div');d.className='r';d.innerHTML=tpl;set.appendChild(d);bind(d);});});
function bind(root){root.querySelectorAll('.del').forEach(function(x){x.onclick=function(){x.closest('.r').remove();sched()}});
 root.querySelectorAll('input,select').forEach(function(x){x.addEventListener('input',sched)});}
bind(document);
document.querySelectorAll('.swatches button').forEach(function(b){b.addEventListener('click',function(e){e.preventDefault();form.accent.value=b.dataset.c;sched()})});
form.addEventListener('input',sched);form.addEventListener('change',sched);
function sched(){clearTimeout(t);t=setTimeout(run,500)}
function run(){if(busy){again=true;return}busy=true;var fd=new FormData(form);
 fetch('/preview/'+form.dataset.slug,{method:'POST',body:fd,credentials:'same-origin'}).then(function(r){return r.text()}).then(function(h){fr.srcdoc=h})
 .finally(function(){busy=false;if(again){again=false;run()}})}
run();})();
</script>""" % {"types": json.dumps([[t, build.SOCIAL_LABELS[t]] for t in SOCIAL_TYPES])}


def edit_page(u, csrf, slug, p, errs=None, is_new=False):
    def rows(items, cls, tpl, fields):
        out = ""
        for it in items:
            out += '<div class="r">' + fields(it) + "</div>"
        return '<div class="rowset %s" id="%s" data-tpl="%s">%s</div>' % (cls[0], cls[1], esc(tpl), out)

    def sel(name, cur):
        return '<select name="%s_type">%s</select>' % (name, "".join(
            '<option value="%s"%s>%s</option>' % (t, " selected" if t == cur else "", esc(build.SOCIAL_LABELS[t])) for t in SOCIAL_TYPES))
    DEL = '<button type="button" class="del small">✕</button>'
    soc = rows(p.get("socials", []), ("so", "socials"),
               '<select name="social_type">%TYPES%</select><input type="text" inputmode="url" name="social_url" placeholder="https://…">' + DEL,
               lambda it: sel("social", it["type"]) + '<input type="text" inputmode="url" name="social_url" value="%s">' % esc(it["url"]) + DEL)
    co = rows(p.get("company_links", []), ("co", "company"),
              '<select name="company_type">%TYPES%</select><input type="text" inputmode="url" name="company_url" placeholder="https://…"><input type="text" name="company_label" placeholder="Label (optional)">' + DEL,
              lambda it: sel("company", it["type"]) + '<input type="text" inputmode="url" name="company_url" value="%s"><input type="text" name="company_label" value="%s" placeholder="Label (optional)">' % (esc(it["url"]), esc(it.get("label", ""))) + DEL)
    ln = rows(p.get("links", []), ("ln", "links"),
              '<input type="text" name="link_label" placeholder="Label"><input type="text" inputmode="url" name="link_url" placeholder="https://…">' + DEL,
              lambda it: '<input type="text" name="link_label" value="%s"><input type="text" inputmode="url" name="link_url" value="%s">' % (esc(it.get("label", "")), esc(it["url"])) + DEL)
    bk = p.get("booking")
    bk = {"url": bk} if isinstance(bk, str) else (bk or {})
    errh = "".join('<div class="err">%s</div>' % esc(e) for e in (errs or []))
    sw = "".join('<button type="button" data-c="%s" style="background:%s" aria-label="%s"></button>' % (c, c, c) for c in SWATCHES)
    slugfield = ('<label for="sl">Web address</label><div class="row"><span class="muted">%s/</span><input id="sl" type="text" name="slug" value="%s" pattern="[a-z0-9-]{1,20}" maxlength="20" style="max-width:160px" required></div>'
                 % (esc(card_origin(u["handle"]).split("://", 1)[1]), esc(p.get("_slug", ""))) if is_new else "")
    body = """<p><a href="/dashboard" class="muted">← Dashboard</a></p><h1>%(title)s</h1>%(err)s
<div class="grid"><form id="f" method="post" action="/edit/%(slug)s" enctype="multipart/form-data" data-slug="%(slug)s" class="panel">
<input type="hidden" name="csrf" value="%(csrf)s">%(slugfield)s
<label>Card name (shown in the switcher)</label><input type="text" name="label" value="%(label)s" maxlength="24" required>
<label>Company / organisation</label><input type="text" name="org" value="%(org)s" maxlength="60">
<label>Job title</label><input type="text" name="title" value="%(ttl)s" maxlength="60">
<label>Short note (optional)</label><input type="text" name="note" value="%(note)s" maxlength="160">
<label>Phone</label><input type="tel" name="phone" value="%(phone)s" maxlength="25">
<label>Email</label><input type="email" name="email" value="%(email)s" maxlength="120">
<label>Website</label><input type="text" name="url" value="%(url)s" maxlength="300" placeholder="example.com">
<label>Booking link (Calendly, Cal.com…)</label><input type="text" name="booking" value="%(bk)s" maxlength="300"><input type="text" name="booking_label" value="%(bkl)s" maxlength="30" placeholder="Button text, e.g. Book a meeting" style="margin-top:6px">
<label>Photo</label><input type="file" name="photo" accept="image/jpeg,image/png,image/webp"><label style="font-weight:400"><input type="checkbox" name="remove_photo"> Use initials instead</label>
<label>Logo (optional, shown top-left)</label><input type="file" name="logo" accept="image/png,image/jpeg,image/webp"><label style="font-weight:400"><input type="checkbox" name="remove_logo"> Remove logo</label>
<label>Colour</label><input type="text" name="accent" value="%(acc)s" maxlength="7" style="max-width:120px"><div class="swatches">%(sw)s</div>
<label>Social icons</label>%(soc)s<button type="button" class="small" data-add="socials">+ Add</button>
<label>Company links</label>%(co)s<button type="button" class="small" data-add="company">+ Add</button>
<label>Other links</label>%(ln)s<button type="button" class="small" data-add="links">+ Add</button>
<label style="font-weight:400;margin-top:16px"><input type="checkbox" name="hidden" %(hid)s> Hide from the swipe order (reachable only by its own link)</label>
<label style="font-weight:400"><input type="checkbox" name="no_location" %(nl)s> Never show my "Last seen" location on this card</label>
<div class="row" style="margin-top:18px"><button class="primary">Save</button></div></form>
<div class="preview"><iframe id="pv" sandbox="allow-scripts" title="Preview"></iframe></div></div>%(del)s%(js)s""" % {
        "title": "New card" if is_new else "Edit “%s”" % esc(p.get("label", "")), "err": errh, "slug": "new" if is_new else esc(p["_slug"]), "csrf": esc(csrf), "slugfield": slugfield,
        "label": esc(p.get("label", "")), "org": esc(p.get("org", "")), "ttl": esc(p.get("title", "")), "note": esc(p.get("note", "")),
        "phone": esc(p.get("phone", "")), "email": esc(p.get("email", "")), "url": esc(p.get("url", "")), "bk": esc(bk.get("url", "")), "bkl": esc(bk.get("label", "")),
        "acc": esc(p.get("accent", "#2563eb")), "sw": sw, "soc": soc, "co": co, "ln": ln, "js": rowset_js(),
        "hid": "checked" if p.get("hidden") else "", "nl": "checked" if p.get("no_location") else "",
        "del": "" if is_new or len(u["cfg"]["personas"]) < 2 else
        '<form method="post" action="/persona/%s/delete" onsubmit="return confirm(\'Delete this card?\')" style="margin:10px 0 0"><input type="hidden" name="csrf" value="%s"><button class="danger small">Delete this card</button></form>' % (esc(p["_slug"]), esc(csrf))}
    return layout("Edit card" if not is_new else "New card", body, user=u, csrf=csrf)


def simple(title, inner, user=None, csrf="", narrow=True):
    return layout(title, "<h1>%s</h1>%s" % (esc(title), inner), user=user, csrf=csrf, narrow=narrow)


TERMS = """<p class="muted">Last updated 23 October 2026 (beta). Plain-language terms, not legal advice.</p>
<p>@SITE@ lets you publish digital business cards at <b>yourname.@BASE@</b>. By using it you agree to the following.</p>
<ul><li>You are responsible for everything on your cards. Don't publish anything unlawful, deceptive, abusive or that impersonates someone else or an organisation, and don't use a card to collect passwords or payments.</li>
<li>We may suspend or remove any card or account at our discretion, for example after a report, and without notice where needed to prevent harm.</li>
<li><b>@SITE@ is in beta.</b> It is free and provided as-is, with no guarantee of availability, features or data retention. It may change, break, lose data, or be shut down at any time, with little or no notice. Don't rely on it for anything critical, and keep your own copy of your details. Your vCard and QR codes are downloadable, and printed QR codes will stop working if the service closes.</li>
<li>You can delete your account at any time from the dashboard; all your data is then removed.</li>
<li>Names (handles) are first-come, first-served and may be reclaimed if abusive or misleading.</li></ul>
<p>Contact: <a href="mailto:%(c)s">%(c)s</a></p>""" % {"c": CONTACT}

PRIVACY = """<p class="muted">Last updated 23 October 2026. Plain-language notice, not legal advice.</p>
<h2>Cardholders (you)</h2><ul><li>We store your email address, the details you put on your cards, and any images you upload. Email is used only for sign-in links and service notices. When you sign up or sign in we also record the time, IP address and browser, which the service operator can see for security and to understand usage.</li>
<li>If you turn on your <b>handle@@BASE@</b> address, mail sent to it is forwarded to the address you choose by our forwarding provider (ImprovMX). We don't store the mail; the provider handles it under its own policy.</li>
<li>No advertising, no selling data, no third-party trackers. Login emails are sent via an email delivery provider.</li>
<li>Deleting your account removes your cards, uploads and visitor logs.</li></ul>
<h2>People who open a card (or the home page / demo)</h2><ul><li>To show the card's owner how it is used, each page records your IP address, approximate location (city level), device, browser, language, and which links you tap. No cookies or local storage are used.</li>
<li>Only the card's owner can see these entries (and, in cases of abuse, the service administrator). They are deleted after 180 days.</li>
<li>Every card has an <b>i</b> button with a <b>Forget me</b> link that immediately deletes all entries recorded for your IP address on that card owner's site, and stops further recording for that visit.</li>
<li>Owners may also show an optional "last seen" city based on their own phone; this is about the owner, not visitors.</li></ul>
<p>Questions or requests: <a href="mailto:%(c)s">%(c)s</a></p>""" % {"c": CONTACT}
for _n in ("TERMS", "PRIVACY"):   # product name and addresses follow the configuration
    globals()[_n] = globals()[_n].replace("@BASE@", BASE).replace("@SITE@", SITE)


# --------------------------------------------------------------- routing ----
ROUTES = []


def route(method, pattern):
    def deco(fn):
        ROUTES.append((method, re.compile(pattern + r"\Z"), fn)); return fn
    return deco


def load_user(row):
    return {"id": row["id"], "email": row["email"], "handle": row["handle"], "name": row["name"] or "",
            "cfg": json.loads(row["cfg"]) if row["cfg"] else {"default": None, "personas": {}}, "status": row["status"],
            "log_ver": row["log_ver"], "loc_ver": row["loc_ver"],
            "demo": row["email"].lower().endswith(".invalid"), "mail_on": row["mail_on"], "mail_fwd": row["mail_fwd"] or row["email"], "mail_id": row["mail_id"]}


def need_user(req, db, csrf_check=False, need_handle=True, demo_ok=False):
    row = db.execute("select u.*,s.csrf as csrf,s.exp as sexp from sessions s join users u on u.id=s.uid where s.hash=?", (sha(req.sid),)).fetchone() if req.sid else None
    if not row or row["sexp"] < now() or row["status"] != "active":
        raise redirect("/")
    u = load_user(row); req.csrf = row["csrf"]
    if csrf_check and not secrets.compare_digest(req.f("csrf"), row["csrf"]):
        raise Resp("403 Forbidden", "Bad CSRF token — go back and reload the page.")
    if csrf_check and u["demo"] and not demo_ok:
        raise redirect("/dashboard?m=" + quote("Demo mode: changes aren't saved. Sign up to make your own card."))
    if need_handle and not u["handle"]:
        raise redirect("/welcome")
    return u


def save_user(db, u):
    db.execute("update users set name=?, cfg=? where id=?", (u["name"], json.dumps(u["cfg"]), u["id"]))
    db.commit()


def rerender(u):
    with RENDER_LOCK:
        render.render_user(u)


def start_session(db, uid):
    sid = secrets.token_urlsafe(32)
    db.execute("insert into sessions(hash,uid,csrf,exp) values(?,?,?,?)", (sha(sid), uid, secrets.token_urlsafe(16), now() + 30 * 86400))
    db.execute("update users set last_login=? where id=?", (now(), uid))
    db.commit()
    return sid


def approved_request(db, email):
    return db.execute("select * from requests where email=? and status='approved' order by id desc limit 1", (email,)).fetchone()


def is_invited(db, email):
    """Existing users, admins and approved requests may sign in; everyone else must request an invite first."""
    return (email in ADMINS or db.execute("select 1 from users where email=?", (email,)).fetchone() is not None
            or approved_request(db, email) is not None)


def handle_taken(db, h, email=""):
    return (db.execute("select 1 from users where handle=?", (h,)).fetchone() is not None
            or db.execute("select 1 from requests where handle=? and status in ('pending','approved') and email!=?", (h, email)).fetchone() is not None)


def request_page(msg="", handle="", email=""):
    return layout("Request an invite", """<div class="hero"><h1>Request an invite</h1><p class="muted">%s is invitation-only while it's in beta. Choose the address you'd like and your email; you'll hear back once the request is approved.</p></div>
<form method="post" action="/request" class="panel">%s<label for="h">Handle</label><div class="row"><input id="h" type="text" name="handle" value="%s" pattern="[a-z0-9-]{1,30}" maxlength="30" required style="max-width:200px" autofocus><span class="muted">.%s</span></div>
<label for="e">Email</label><input id="e" type="email" name="email" value="%s" required autocomplete="email">
<div class="row" style="margin-top:14px"><button class="primary">Request invite</button></div>
<p class="muted" style="margin:14px 0 0">Already approved? <a href="/">Sign in</a>. Just looking? <a href="/demo">Try the demo</a>.</p></form>""" % (esc(SITE), msg, esc(handle), esc(BASE), esc(email)), narrow=True)


@route("GET", r"/request")
def request_get(req, db):
    return Resp(body=request_page())


@route("POST", r"/request")
def request_post(req, db):
    h, email = req.f("handle", "", 30).lower(), req.f("email", "", 120).lower()
    err = None
    if not EMAIL_RE.fullmatch(email):
        err = "Please enter a valid email address."
    else:
        err = handle_error(h)
    if not err and not rl_ok(db, "reqip:" + req.ip, 5, 3600):
        return Resp("429 Too Many Requests", request_page('<div class="err">Too many requests. Try again later.</div>', h, email))
    if not err:
        if db.execute("select 1 from users where email=?", (email,)).fetchone() or approved_request(db, email):
            return Resp(body=simple("You're already in", '<p>That email is already approved. <a href="/">Sign in</a>.</p>'))
        if handle_taken(db, h, email):
            err = "That name is taken."
    if err:
        return Resp(body=request_page('<div class="err">%s</div>' % esc(err), h, email))
    db.execute("delete from requests where email=? and status in ('pending','rejected')", (email,))
    rid = db.execute("insert into requests(handle,email,ip,ua,ts) values(?,?,?,?,?)", (h, email, req.ip, req.env.get("HTTP_USER_AGENT", "")[:300], now())).lastrowid
    db.commit()
    log_event(db, "invite_request", req, handle=h, email=email)
    for adm in sorted(ADMINS):
        try:
            send_mail(adm, SITE + " invite request: %s" % h, "New invite request\n\nHandle: %s.%s\nEmail: %s\nIP: %s\n\nApprove or reject: %s/admin#requests" % (h, BASE, email, req.ip, app_origin()))
        except Exception as e:
            print("admin notify error", e, file=sys.stderr)
    return Resp(body=simple("Request received", "<p>Thanks. Your request for <b>%s.%s</b> is with us. You'll get an email at <b>%s</b> when it's approved.</p>" % (esc(h), esc(BASE), esc(email))))


@route("GET", r"/")
def home(req, db):
    if req.sid:
        try:
            need_user(req, db, need_handle=False); return redirect("/dashboard")
        except Resp:
            pass
    return Resp(body=login_page())


@route("GET", r"/login")
def login_get(req, db):
    return home(req, db)


@route("GET", r"/demo")
def demo_login(req, db):
    row = db.execute("select id from users where handle='demo' and email like '%.invalid' and status='active'").fetchone()
    if not row:
        return Resp("404 Not Found", simple("Demo unavailable", "<p>The demo isn't set up yet.</p>"))
    if not rl_ok(db, "demo:" + req.ip, 30, 3600):
        return Resp("429 Too Many Requests", simple("Try again later", "<p>Too many demo sessions from your network.</p>"))
    sid = secrets.token_urlsafe(32)
    db.execute("insert into sessions(hash,uid,csrf,exp) values(?,?,?,?)", (sha(sid), row["id"], secrets.token_urlsafe(16), now() + 2 * 3600)); db.commit()
    log_event(db, "demo_start", req, uid=row["id"], handle="demo")
    return redirect("/dashboard", [cookie_hdr(sid, 2 * 3600)])


@route("POST", r"/login")
def login(req, db):
    email = req.f("email", "", 120).lower()
    if not EMAIL_RE.fullmatch(email):
        return Resp(body=login_page('<div class="err">Please enter a valid email address.</div>', email))
    if not rl_ok(db, "ip:" + req.ip, 20, 3600) or not rl_ok(db, "em:" + email, 5, 3600):
        return Resp("429 Too Many Requests", login_page('<div class="err">Too many attempts. Try again later.</div>', email))
    if not is_invited(db, email):
        return Resp(body=login_page('<div class="err">That email hasn\'t been approved yet. <a href="/request">Request an invite</a>.</div>', email))
    log_event(db, "login_request", req, email=email)
    tok = secrets.token_urlsafe(32)
    db.execute("insert into login_tokens(hash,email,exp) values(?,?,?)", (sha(tok), email, now() + 900))
    db.commit()
    link = "%s/auth?t=%s" % (app_origin(), tok)
    try:
        send_mail(email, "Your %s sign-in link" % SITE, "Open this link to sign in to %s (valid for 15 minutes, works once):\n\n%s\n\nIf you didn't ask for this, ignore this email." % (SITE, link))
    except Exception as e:
        print("mail error", e, file=sys.stderr)
        return Resp("500 Server Error", login_page('<div class="err">Couldn\'t send the email. Please try again shortly.</div>', email))
    return Resp(body=simple("Check your email", "<p>If <b>%s</b> is valid we've sent a sign-in link. It works once and expires in 15 minutes.</p>" % esc(email)))


@route("GET", r"/auth")
def auth_get(req, db):
    t = req.query.get("t", "")
    return Resp(body=simple("Sign in", '<form method="post" action="/auth" class="panel"><input type="hidden" name="t" value="%s"><p>Continue to sign in to %s.</p>'
                                       '<button class="primary">Sign in</button></form>' % (esc(t), esc(SITE))))


@route("POST", r"/auth")
def auth_post(req, db):
    t = req.f("t", "", 80)
    row = db.execute("select email,exp from login_tokens where hash=?", (sha(t),)).fetchone() if t else None
    if not row or row["exp"] < now():
        return Resp("400 Bad Request", simple("Link expired", '<p>That link has expired or was already used. <a href="/">Request a new one.</a></p>'))
    db.execute("delete from login_tokens where hash=?", (sha(t),))
    u = db.execute("select id from users where email=?", (row["email"],)).fetchone()
    if not u and not is_invited(db, row["email"]):
        return Resp("403 Forbidden", simple("Not approved", '<p>That email hasn\'t been approved. <a href="/request">Request an invite</a>.</p>'))
    if u:
        uid = u["id"]
    else:
        uid = db.execute("insert into users(email,created) values(?,?)", (row["email"], now())).lastrowid
    db.commit()
    log_event(db, "login" if u else "signup", req, uid=uid, email=row["email"])
    sid = start_session(db, uid)
    return redirect("/dashboard", [cookie_hdr(sid, 30 * 86400)])


@route("POST", r"/logout")
def logout(req, db):
    u = need_user(req, db, True, False, demo_ok=True)
    db.execute("delete from sessions where hash=?", (sha(req.sid),)); db.commit()
    return redirect("/", [cookie_hdr("", 0)])


@route("GET", r"/welcome")
def welcome_get(req, db):
    u = need_user(req, db, need_handle=False)
    if u["handle"]:
        return redirect("/dashboard")
    inv = approved_request(db, u["email"])
    return Resp(body=welcome_page(u, req.csrf, handle=inv["handle"] if inv else "", lock=bool(inv)))


def welcome_page(u, csrf, err="", handle="", name="", lock=False):
    return layout("Welcome", """<h1>Choose your address</h1><p class="muted">This becomes your card's web address. You can't change it later.</p>
<form method="post" action="/welcome" class="panel"><input type="hidden" name="csrf" value="%s">%s
<label for="h">Handle</label><div class="row"><input id="h" type="text" name="handle" value="%s" pattern="[a-z0-9-]{1,30}" maxlength="30" required style="max-width:200px" %s><span class="muted">.%s</span></div>
<label for="n">Your name</label><input id="n" type="text" name="name" value="%s" maxlength="60" required autocomplete="name">
<label style="font-weight:400;margin-top:16px"><input type="checkbox" name="terms" required> I agree to the <a href="/terms" target="_blank">Terms</a> and <a href="/privacy" target="_blank">Privacy notice</a></label>
<div class="row" style="margin-top:14px"><button class="primary">Create my card</button></div></form>""" % (esc(csrf), ('<div class="err">%s</div>' % esc(err)) if err else "", esc(handle), "readonly" if lock else "autofocus", esc(BASE), esc(name)),
                  user=u, narrow=True, csrf=csrf)


@route("POST", r"/welcome")
def welcome_post(req, db):
    u = need_user(req, db, True, False)
    if u["handle"]:
        return redirect("/dashboard")
    inv = approved_request(db, u["email"])
    h, name = (inv["handle"] if inv else req.f("handle", "", 30).lower()), req.f("name", "", 60)
    err = handle_error(h) or (None if name else "Please enter your name.") or (None if req.flag("terms") else "Please accept the terms.")
    if not err and (db.execute("select 1 from users where handle=?", (h,)).fetchone() or (not inv and handle_taken(db, h, u["email"]))):
        err = "That name is taken."
    if err:
        return Resp(body=welcome_page(u, req.csrf, err, h, name, lock=bool(inv)))
    cfg = {"default": "me", "personas": {"me": {"label": "Me", "email": u["email"], "accent": "#2563eb", "socials": []}}}
    cfg["personas"]["me"].pop("socials")
    db.execute("update users set handle=?, name=?, cfg=?, terms_at=? where id=?", (h, name, json.dumps(cfg), now(), u["id"])); db.commit()
    log_event(db, "handle_chosen", req, uid=u["id"], handle=h, email=u["email"])
    u.update(handle=h, name=name, cfg=cfg)
    rerender(u)
    return redirect("/edit/me")


@route("GET", r"/dashboard")
def dashboard(req, db):
    u = need_user(req, db)
    return Resp(body=dashboard_page(u, req.csrf, '<div class="ok panel">%s</div>' % esc(req.query["m"]) if req.query.get("m") else ""))


@route("POST", r"/account/name")
def account_name(req, db):
    u = need_user(req, db, True)
    n = req.f("name", "", 60)
    if n:
        u["name"] = n; save_user(db, u); rerender(u)
    return redirect("/dashboard?m=Saved")


@route("POST", r"/account/delete")
def account_delete(req, db):
    u = need_user(req, db, True)
    if req.f("confirm") != u["handle"]:
        return redirect("/dashboard?m=Handle+didn%27t+match,+nothing+deleted")
    purge_user(db, u["id"], u["handle"])
    return redirect("/", [cookie_hdr("", 0)])


def drop_alias(row_or_none, handle):
    try:
        if row_or_none and row_or_none["mail_on"]:
            mailalias.delete(handle, row_or_none["mail_id"])
    except mailalias.MailError as e:
        print("alias cleanup error", e, file=sys.stderr)


def purge_user(db, uid, handle):
    drop_alias(db.execute("select mail_on,mail_id from users where id=?", (uid,)).fetchone(), handle)
    for base in (Path(USERS_ROOT) / handle, Path(ASSETS) / str(uid), Path(LOG_ROOT) / handle):
        shutil.rmtree(base, ignore_errors=True)
    db.execute("delete from sessions where uid=?", (uid,))
    db.execute("delete from users where id=?", (uid,))
    db.commit()


def edit_target(u, slug):
    p = u["cfg"]["personas"].get(slug)
    if p is None:
        raise Resp("404 Not Found", simple("Not found", "<p>No such card.</p>", u))
    q = dict(p); q["_slug"] = slug
    return q


@route("GET", r"/edit/(new|[a-z0-9-]{1,20})")
def edit_get(req, db, slug):
    u = need_user(req, db)
    if slug == "new":
        if len(u["cfg"]["personas"]) >= MAX_PERSONAS:
            return redirect("/dashboard")
        base = {"label": "", "email": u["email"], "accent": "#2563eb", "_slug": ""}
        return Resp(body=edit_page(u, req.csrf, "", base, is_new=True))
    return Resp(body=edit_page(u, req.csrf, slug, edit_target(u, slug)))


def collect(req, u, slug, existing, errs, persist):
    p = build_persona(req, existing, errs)
    photo, logo, rm = save_assets(u["id"], slug, req, errs, persist)
    return p, photo, logo, rm


@route("POST", r"/edit/(new|[a-z0-9-]{1,20})")
def edit_post(req, db, slug):
    u = need_user(req, db, True)
    ps = u["cfg"]["personas"]; errs = []
    is_new = slug == "new"
    if is_new:
        if len(ps) >= MAX_PERSONAS:
            return redirect("/dashboard")
        slug = req.f("slug", "", 20).lower()
        if not re.fullmatch(r"[a-z0-9-]{1,20}", slug) or slug in PERSONA_RESERVED or slug in ps:
            errs.append("Pick a different web address for this card (letters, digits, hyphens; not already used).")
    existing = {} if is_new else ps[slug]
    p, photo, logo, rm = collect(req, u, slug if not errs else "x", existing, errs, persist=False)
    if errs:
        q = dict(p); q["_slug"] = slug if not is_new else req.f("slug"); return Resp("400 Bad Request", edit_page(u, req.csrf, slug, q, errs, is_new))
    save_assets(u["id"], slug, req, errs, persist=True)
    ps[slug] = p
    if not u["cfg"].get("default") or u["cfg"]["default"] not in ps:
        u["cfg"]["default"] = slug
    save_user(db, u); rerender(u)
    return redirect("/dashboard?m=Saved")


@route("POST", r"/preview/(new|[a-z0-9-]{1,20})")
def preview(req, db, slug):
    u = need_user(req, db, True, demo_ok=True)
    ps = u["cfg"]["personas"]; errs = []
    key = slug if slug != "new" else (req.f("slug", "new", 20) or "new")
    existing = ps.get(slug, {}) if slug != "new" else {}
    p, photo, logo, rm = collect(req, u, key, existing, errs, persist=False)
    if photo is None:
        photo = render.load_photo(u["id"], key, u["name"], p["accent"])
    if logo is None and not rm:
        logo = render.load_logo(u["id"], key)[1]
    sib = {k: v for k, v in ps.items() if k != key}; sib[key] = p
    sib = {k: sib[k] for k in list(ps) + [key] if k in sib}
    return Resp(body=render.preview_html(u["handle"], u["name"], key, p, sib, photo, None if rm else logo))


@route("POST", r"/persona/([a-z0-9-]{1,20})/move")
def persona_move(req, db, slug):
    u = need_user(req, db, True)
    ps = u["cfg"]["personas"]
    if slug not in ps:
        return redirect("/dashboard")
    d = req.f("d")
    keys = list(ps)
    if d == "default":
        u["cfg"]["default"] = slug
    elif d in ("up", "down"):
        i = keys.index(slug); j = i - 1 if d == "up" else i + 1
        if 0 <= j < len(keys):
            keys[i], keys[j] = keys[j], keys[i]; u["cfg"]["personas"] = {k: ps[k] for k in keys}
    save_user(db, u); rerender(u)
    return redirect("/dashboard")


@route("POST", r"/persona/([a-z0-9-]{1,20})/delete")
def persona_delete(req, db, slug):
    u = need_user(req, db, True)
    ps = u["cfg"]["personas"]
    if slug in ps and len(ps) > 1:
        del ps[slug]
        if u["cfg"].get("default") == slug:
            u["cfg"]["default"] = None
        shutil.rmtree(render.asset_dir(u["id"], slug), ignore_errors=True)
        save_user(db, u); rerender(u)
    return redirect("/dashboard?m=Deleted")


def card_urls(u, slug):
    dflt = render.default_slug(u["cfg"])
    base = card_origin(u["handle"])
    url = "%s/%s/" % (base, slug)   # always the permanent per-card address, never "/" (the default can change)
    return url, url.split("://", 1)[1].rstrip("/")


@route("GET", r"/card/([a-z0-9-]{1,20})\.(png|pdf)")
def card_img(req, db, slug, ext):
    u = need_user(req, db)
    p = edit_target(u, slug)
    url, shown = card_urls(u, slug)
    photo = render.load_photo(u["id"], slug, u["name"], p.get("accent", "#2563eb"))
    if ext == "png":
        return Resp(body=cardimg.phone_card(u["name"], p, url, shown, photo), ctype="image/png")
    return Resp(body=cardimg.print_sheet(u["name"], p, url, shown, photo), ctype="application/pdf")


@route("GET", r"/qr/([a-z0-9-]{1,20})\.(svg|png)")
def qr(req, db, slug, ext):
    u = need_user(req, db)
    edit_target(u, slug)
    url, _ = card_urls(u, slug)
    return Resp(body=cardimg.qr_svg(url) if ext == "svg" else cardimg.qr_png(url, 900), ctype="image/svg+xml" if ext == "svg" else "image/png")


@route("GET", r"/visitors")
def visitors(req, db):
    u = need_user(req, db)
    return redirect("%s/log/#t=%s" % (card_origin(u["handle"]), derive(u["handle"], "log", u["log_ver"])))


@route("GET", r"/location")
def location_get(req, db):
    u = need_user(req, db)
    ep = card_origin(u["handle"]) + "/api/loc.cgi"
    tok = derive(u["handle"], "loc", u["loc_ver"])
    return Resp(body=layout("Last seen location", """<p><a href="/dashboard" class="muted">← Dashboard</a></p><h1>"Last seen" location</h1>
<p class="muted">Your cards can show <i>📍 Last seen - London, UK (2 hours ago)</i>. Your phone sends a location; the server keeps only the nearest <b>major city</b> (or just the country) and the time, never coordinates. It expires after 2 days.</p>
<div class="panel"><b>iPhone Shortcut</b><ol><li>Shortcuts → <b>+</b> → add <b>Get Current Location</b>.</li>
<li>Add <b>Get Details of Locations</b> (Latitude), another for <b>Longitude</b>, and another for <b>Country</b>.</li>
<li>Add <b>Get Contents of URL</b>: URL <code>%(ep)s</code>, Method <b>POST</b>, Request Body <b>Form</b> with fields <code>token</code>, <code>lat</code>, <code>lon</code>, <code>country</code>.</li>
<li>Token value: <code>%(tok)s</code></li><li>Run it from an Automation (e.g. "Arrive" / time of day) so it updates itself. To hide your location, send the form field <code>clear</code> = <code>1</code> with the token.</li></ol></div>
<form method="post" action="/rotate" class="panel"><input type="hidden" name="csrf" value="%(csrf)s"><p class="muted" style="margin-top:0">Token leaked? Generate new ones (the old log link and Shortcut token stop working).</p>
<div class="row"><button name="kind" value="loc">New Shortcut token</button><button name="kind" value="log">New visitor-log link</button></div></form>""" % {
        "ep": esc(ep), "tok": esc(tok), "csrf": esc(req.csrf)}, user=u, csrf=req.csrf))


@route("POST", r"/rotate")
def rotate(req, db):
    u = need_user(req, db, True)
    col = "loc_ver" if req.f("kind") == "loc" else "log_ver"
    db.execute("update users set %s=%s+1 where id=?" % (col, col), (u["id"],)); db.commit()
    return redirect("/location" if col == "loc_ver" else "/dashboard?m=New+visitor-log+link+active")


def mail_flash(msg):
    return redirect("/dashboard?m=" + quote(msg))


@route("POST", r"/mail/enable")
def mail_enable(req, db):
    u = need_user(req, db, True)
    if u["mail_on"]:
        return redirect("/dashboard")
    if not rl_ok(db, "mail:%d" % u["id"], 10, 3600):
        return mail_flash("Too many changes, try again later.")
    try:
        aid = mailalias.create(u["handle"], u["mail_fwd"])
    except mailalias.Exists:
        return mail_flash("That address is already in use. Contact %s." % CONTACT)
    except mailalias.MailError as e:
        print("mail enable error", e, file=sys.stderr)
        return mail_flash("Couldn't set up the address right now. Please try again later.")
    db.execute("update users set mail_on=1, mail_fwd=?, mail_id=? where id=?", (u["mail_fwd"], aid, u["id"])); db.commit()
    return mail_flash("%s@%s is on." % (u["handle"], BASE))


@route("POST", r"/mail/disable")
def mail_disable(req, db):
    u = need_user(req, db, True)
    if u["mail_on"]:
        if not rl_ok(db, "mail:%d" % u["id"], 10, 3600):
            return mail_flash("Too many changes, try again later.")
        try:
            mailalias.delete(u["handle"], u["mail_id"])
        except mailalias.MailError as e:
            print("mail disable error", e, file=sys.stderr)
            return mail_flash("Couldn't turn it off right now. Please try again later.")
        db.execute("update users set mail_on=0, mail_id=null where id=?", (u["id"],)); db.commit()
    return mail_flash("Email address turned off.")


def apply_forward(db, u, addr):
    if u["mail_on"]:
        mailalias.update(u["handle"], u["mail_id"], addr)
    db.execute("update users set mail_fwd=? where id=?", (addr, u["id"])); db.commit()


@route("POST", r"/mail/forward")
def mail_forward(req, db):
    u = need_user(req, db, True)
    addr = req.f("forward", "", 120).lower()
    if not EMAIL_RE.fullmatch(addr):
        return mail_flash("That doesn't look like an email address.")
    if not rl_ok(db, "mailfwd:%d" % u["id"], 6, 3600):
        return mail_flash("Too many changes, try again later.")
    if addr == u["email"].lower():
        try:
            apply_forward(db, u, addr)
        except mailalias.MailError as e:
            print("forward error", e, file=sys.stderr); return mail_flash("Couldn't update right now. Please try again later.")
        return mail_flash("Forwarding to %s." % addr)
    tok = secrets.token_urlsafe(32)
    db.execute("insert into mail_verify(hash,uid,email,exp) values(?,?,?,?)", (sha(tok), u["id"], addr, now() + 3600)); db.commit()
    try:
        send_mail(addr, "Confirm forwarding for %s@%s" % (u["handle"], BASE),
                  "Someone (signed in as %s) asked to forward mail for %s@%s to this address.\n\nTo confirm, open this link (valid 1 hour):\n\n%s/mail/verify?t=%s\n\nIf this wasn't you, ignore this email and nothing changes." % (u["email"], u["handle"], BASE, app_origin(), tok))
    except Exception as e:
        print("mail error", e, file=sys.stderr); return mail_flash("Couldn't send the confirmation email.")
    return mail_flash("We sent a confirmation link to %s. Forwarding changes once you open it." % addr)


@route("GET", r"/mail/verify")
def mail_verify_get(req, db):
    return Resp(body=simple("Confirm forwarding", '<form method="post" action="/mail/verify" class="panel"><input type="hidden" name="t" value="%s"><p>Confirm forwarding to this address?</p><button class="primary">Confirm</button></form>' % esc(req.query.get("t", ""))))


@route("POST", r"/mail/verify")
def mail_verify_post(req, db):
    t = req.f("t", "", 80)
    row = db.execute("select * from mail_verify where hash=?", (sha(t),)).fetchone() if t else None
    if not row or row["exp"] < now():
        return Resp("400 Bad Request", simple("Link expired", "<p>That link has expired or was already used.</p>"))
    db.execute("delete from mail_verify where hash=?", (row["hash"],)); db.commit()
    r = db.execute("select * from users where id=?", (row["uid"],)).fetchone()
    if not r or not r["handle"] or r["status"] != "active":
        return Resp("400 Bad Request", simple("Not available", "<p>This card no longer exists.</p>"))
    try:
        apply_forward(db, load_user(r), row["email"])
    except mailalias.MailError as e:
        print("verify error", e, file=sys.stderr)
        return Resp("500 Server Error", simple("Try again later", "<p>We couldn't update forwarding right now. Please request a new link later.</p>"))
    return Resp(body=simple("Done", "<p>Mail for <b>%s@%s</b> now forwards to <b>%s</b>.</p>" % (esc(r["handle"]), esc(BASE), esc(row["email"]))))


@route("GET", r"/terms")
def terms(req, db):
    return Resp(body=simple("Terms", TERMS, narrow=False))


@route("GET", r"/privacy")
def privacy(req, db):
    return Resp(body=simple("Privacy notice", PRIVACY, narrow=False))


@route("GET", r"/report")
def report_get(req, db):
    h = req.query.get("h", "")
    return Resp(body=report_page(h))


def report_page(h, msg=""):
    return simple("Report a card", """<p class="muted">Tell us what's wrong with <b>%(h)s.%(b)s</b>. We review every report.</p>%(m)s
<form method="post" action="/report" class="panel"><input type="hidden" name="h" value="%(h)s">
<label for="r">Reason</label><select id="r" name="reason"><option>Impersonation or misleading</option><option>Scam or phishing</option><option>Abusive or illegal content</option><option>Spam</option><option>Other</option></select>
<label for="n">Details (optional)</label><textarea id="n" name="note" rows="4" maxlength="500"></textarea>
<div class="row" style="margin-top:14px"><button class="primary">Send report</button></div></form>""" % {"h": esc(h), "b": esc(BASE), "m": msg})


@route("POST", r"/report")
def report_post(req, db):
    h = req.f("h", "", 40).lower()
    if not db.execute("select 1 from users where handle=?", (h,)).fetchone():
        return Resp("404 Not Found", simple("Not found", "<p>No such card.</p>"))
    if not rl_ok(db, "rep:" + req.ip, 5, 86400):
        return Resp("429 Too Many Requests", report_page(h, '<div class="err">Too many reports from your network today.</div>'))
    db.execute("insert into reports(handle,reason,note,ip,ts) values(?,?,?,?,?)", (h, req.f("reason", "", 60), req.f("note", "", 500), req.ip, now())); db.commit()
    return Resp(body=simple("Thank you", "<p>Your report was received.</p>"))


def need_admin(req, db, csrf=False):
    u = need_user(req, db, csrf, False)
    if u["email"].lower() not in ADMINS:
        raise Resp("404 Not Found", "Not found", ctype="text/plain")
    return u


# ---------- activity log (sign-ups, sign-ins, demo) + site/demo visit reports for the admin page ----------
def log_event(db, kind, req, uid=None, handle=None, email=None):
    try:
        db.execute("insert into events(ts,kind,uid,handle,email,ip,ua,al,ref) values(?,?,?,?,?,?,?,?,?)",
                   (now(), kind, uid, handle, email, req.ip, req.env.get("HTTP_USER_AGENT", "")[:300],
                    req.env.get("HTTP_ACCEPT_LANGUAGE", "")[:100], req.env.get("HTTP_REFERER", "")[:200]))
        if secrets.randbelow(50) == 0:
            db.execute("delete from events where ts<?", (now() - 365 * 86400,))
        db.commit()
    except Exception as e:
        print("event log error", e, file=sys.stderr)


_GEO_CACHE = {}


def place(ip):
    if ip not in _GEO_CACHE:
        if len(_GEO_CACHE) > 2000:
            _GEO_CACHE.clear()
        _GEO_CACHE[ip] = geo(ip)
    g = _GEO_CACHE[ip]
    return ", ".join(x for x in (g.get("city"), g.get("cc")) if x), g.get("org", "")


def short_ua(ua):
    ua = ua or ""
    if re.search(r"bot|crawl|spider|slurp|curl|python|wget|headless|preview|monitor", ua, re.I):
        return "bot"
    os_ = next((n for p, n in (("iPhone", "iPhone"), ("iPad", "iPad"), ("Android", "Android"), ("Windows", "Windows"), ("Macintosh", "Mac"), ("CrOS", "ChromeOS"), ("Linux", "Linux")) if p in ua), "?")
    br = next((n for p, n in (("LinkedInApp", "LinkedIn app"), ("Edg/", "Edge"), ("OPR/", "Opera"), ("Firefox", "Firefox"), ("Chrome", "Chrome"), ("Safari", "Safari")) if p in ua), "?")
    return "%s / %s" % (os_, br)


def read_log(name, days):
    out = []
    d = Path(LOG_ROOT) / name
    if not d.is_dir():
        return out
    for i in range(days):
        fn = d / (time.strftime("%Y-%m-%d", time.gmtime(now() - i * 86400)) + ".jsonl")
        try:
            for line in fn.read_text(errors="replace").splitlines():
                try:
                    out.append(json.loads(line))
                except ValueError:
                    pass
        except OSError:
            pass
    return out


def ref_host(e):
    r = e.get("ref") or e.get("rh") or ""
    h = urlparse(r).hostname or ""
    return h.replace("www.", "") if h and h.replace("www.", "") != BASE else ""


def tstr(t):
    return time.strftime("%Y-%m-%d %H:%M", time.gmtime(t)) if t else "–"


def visits_report(name, title, note=""):
    evs = read_log(name, 14)
    views = [e for e in evs if e.get("t") == "view"]
    humans = [e for e in views if short_ua(e.get("ua")) != "bot"]
    by_pv = {}
    for e in evs:
        if e.get("pv"):
            by_pv.setdefault(e["pv"], []).append(e)
    t0 = now() - now() % 86400
    top = lambda it, n=5: ", ".join("%s (%d)" % (esc(k), v) for k, v in __import__("collections").Counter(x for x in it if x).most_common(n)) or "–"
    clicks = [e for e in evs if e.get("t") == "click"]
    stats = ('<p class="muted">Today: <b>%d</b> views &middot; 7 days: <b>%d</b> &middot; 14 days: <b>%d</b> (%d unique visitors, %d bots filtered)</p>'
             '<p class="muted">Top referrers: %s<br>Top countries: %s<br>Clicks: %s</p>') % (
        sum(1 for e in humans if e["ts"] >= t0), sum(1 for e in humans if e["ts"] >= now() - 7 * 86400), len(humans),
        len({e.get("vid") for e in humans}), len(views) - len(humans),
        top(ref_host(e) for e in humans), top((e.get("geo") or {}).get("cc") for e in humans),
        top("%s %s" % (e.get("k"), (e.get("href") or "")[:40]) for e in clicks))
    rows = ""
    for e in sorted(humans, key=lambda e: -e["ts"])[:40]:
        g = e.get("geo") or {}
        grp = by_pv.get(e.get("pv"), [])
        dur = max([x.get("dur", 0) for x in grp if x.get("t") == "end"] or [0])
        ks = ", ".join(x.get("k", "") for x in grp if x.get("t") == "click")
        rows += "<tr><td>%s</td><td class=\"mono\">%s</td><td>%s<br><span class=\"muted\">%s</span></td><td>%s</td><td>%s</td><td>%ss</td><td>%s</td></tr>" % (
            tstr(e["ts"]), esc(e.get("ip", "")), esc(", ".join(x for x in (g.get("city"), g.get("cc")) if x) or "–"), esc(g.get("org", "")),
            esc(ref_host(e) or "direct"), esc(short_ua(e.get("ua"))), dur, esc(ks))
    return '<h2>%s &nbsp;<a class="small" href="/admin/log/%s" style="font-size:14px">Open full log →</a></h2>%s<div class="panel">%s<table><tr><th>When (UTC)</th><th>IP</th><th>Place / network</th><th>From</th><th>Device</th><th>Time</th><th>Clicked</th></tr>%s</table></div>' % (
        title, name, note, stats, rows or '<tr><td colspan="7" class="muted">No visits yet.</td></tr>')


def signups_report(db):
    sig = {r["uid"]: r for r in db.execute("select * from events where kind='signup'")}
    rows = ""
    for r in db.execute("select * from users where email not like '%.invalid' order by created desc limit 50"):
        s = sig.get(r["id"])
        p, org = place(s["ip"]) if s and s["ip"] else ("", "")
        rows += '<tr><td>%s<br><span class="muted">%s</span></td><td>%s</td><td>%s</td><td class="mono">%s</td><td>%s<br><span class="muted">%s</span></td><td>%s</td></tr>' % (
            esc(r["email"]), esc(r["name"] or ""), esc(r["handle"] or "(no handle yet)"), tstr(r["created"]), esc(s["ip"] if s else "–"),
            esc(p or "–"), esc(org), esc(short_ua(s["ua"]) if s else "–"))
    return ('<h2>Sign-ups</h2><div class="panel"><table><tr><th>Email / name</th><th>Handle</th><th>Signed up (UTC)</th><th>IP</th><th>Place / network</th><th>Device</th></tr>%s</table></div>' % rows)


def events_report(db):
    rows = ""
    for r in db.execute("select * from events order by ts desc limit 60"):
        p, _ = place(r["ip"]) if r["ip"] else ("", "")
        rows += '<tr><td>%s</td><td>%s</td><td>%s</td><td class="mono">%s</td><td>%s</td><td>%s</td></tr>' % (
            tstr(r["ts"]), esc(r["kind"]), esc(r["email"] or r["handle"] or ""), esc(r["ip"] or ""), esc(p or "–"), esc(short_ua(r["ua"])))
    return '<h2>Recent activity</h2><div class="panel"><table><tr><th>When (UTC)</th><th>Event</th><th>Who</th><th>IP</th><th>Place</th><th>Device</th></tr>%s</table></div>' % rows


ADMIN_LOGS = {"_site": "Home page visits (%s)" % BASE, "_demo": "Demo card visits (demo.%s)" % BASE}


@route("GET", r"/admin/log/(_site|_demo)")
def admin_log_page(req, db, name):
    need_admin(req, db)
    page = (Path(__file__).resolve().parent.parent / "server" / "log.html").read_text()
    page = page.replace("<head>", "<head><script>window.FAR_API='/admin/logdata/%s';</script>" % name, 1)
    return Resp(body=page, ctype="text/html; charset=utf-8")


@route("POST", r"/admin/logdata/(_site|_demo)")
def admin_logdata(req, db, name):
    need_admin(req, db)
    try:
        days = max(1, min(int(req.f("days") or 30), 365))
    except ValueError:
        days = 30
    evs = read_log(name, days)[-60000:]
    return Resp(body=json.dumps({"you": req.ip, "now": now(), "days": days, "geo": os.path.exists(GEO_CITY), "events": evs}, ensure_ascii=False), ctype="application/json")


@route("GET", r"/admin")
def admin(req, db):
    u = need_admin(req, db)
    users = db.execute("select u.*,(select count(*) from reports r where r.handle=u.handle and r.resolved=0) as nrep from users u order by created desc limit 500").fetchall()
    reps = db.execute("select * from reports where resolved=0 order by ts desc limit 100").fetchall()
    f = lambda t: time.strftime("%Y-%m-%d %H:%M", time.gmtime(t)) if t else "–"
    urows = "".join("""<tr><td>%s<br><span class="muted">%s</span></td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td><form method="post" action="/admin/act" class="row" style="margin:0">
<input type="hidden" name="csrf" value="%s"><input type="hidden" name="id" value="%d">%s<button class="small danger" name="a" value="delete" onclick="return confirm('Delete this user and all data?')">Delete</button></form></td></tr>""" % (
        esc(r["handle"] or "(no handle)"), esc(r["email"]), esc(r["status"]), f(r["created"]), f(r["last_login"]), r["nrep"] or "",
        esc(req.csrf), r["id"], '<button class="small" name="a" value="%s">%s</button>' % (("activate", "Unsuspend") if r["status"] != "active" else ("suspend", "Suspend"))) for r in users)
    rrows = "".join("""<tr><td>%s</td><td>%s</td><td>%s<br><span class="muted">%s</span></td><td><form method="post" action="/admin/act" style="margin:0"><input type="hidden" name="csrf" value="%s"><input type="hidden" name="rid" value="%d">
<button class="small" name="a" value="resolve">Resolve</button></form></td></tr>""" % (f(r["ts"]), esc(r["handle"]), esc(r["reason"] or ""), esc(r["note"] or ""), esc(req.csrf), r["id"]) for r in reps)
    pend = db.execute("select * from requests where status='pending' order by ts").fetchall()
    prow = "".join("""<tr><td>%s</td><td><b>%s</b>.%s</td><td>%s<br><span class="muted">%s &middot; %s</span></td><td><form method="post" action="/admin/act" class="row" style="margin:0"><input type="hidden" name="csrf" value="%s"><input type="hidden" name="rid" value="%d">
<button class="small primary" name="a" value="approve">Approve</button><button class="small danger" name="a" value="reject">Reject</button></form></td></tr>""" % (
        tstr(r["ts"]), esc(r["handle"]), esc(BASE), esc(r["email"]), esc(r["ip"] or ""), esc(short_ua(r["ua"])), esc(req.csrf), r["id"]) for r in pend)
    msg = '<div class="ok panel">%s</div>' % esc(req.query["m"]) if req.query.get("m") else ""
    return Resp(body=layout("Admin", msg + """<h1>Admin</h1><h2 id="requests">Invite requests (%d)</h2><div class="panel"><table><tr><th>Requested</th><th>Handle</th><th>Email</th><th></th></tr>%s</table></div>
<h2>Open reports (%d)</h2><div class="panel"><table><tr><th>When</th><th>Card</th><th>Reason</th><th></th></tr>%s</table></div>
<h2>Users (%d)</h2><div class="panel"><table><tr><th>Handle / email</th><th>Status</th><th>Created</th><th>Last login</th><th>Reports</th><th></th></tr>%s</table></div>""" % (
        len(pend), prow or '<tr><td colspan="4" class="muted">No pending requests.</td></tr>', len(reps), rrows, len(users), urows) + signups_report(db) + events_report(db)
        + visits_report("_site", "Home page visits (%s)" % BASE) + visits_report("_demo", "Demo card visits (demo.%s)" % BASE, '<p class="muted">Real visitors only; the demo account\'s own visitor log is generated sample data.</p>'), user=u, csrf=req.csrf))


@route("POST", r"/admin/act")
def admin_act(req, db):
    need_admin(req, db, True)
    a = req.f("a")
    if a in ("approve", "reject"):
        r = db.execute("select * from requests where id=? and status='pending'", (int(req.f("rid") or 0),)).fetchone()
        if r and a == "approve":
            if db.execute("select 1 from users where handle=?", (r["handle"],)).fetchone():
                return redirect("/admin?m=" + quote("Handle %s is already taken; reject or contact the requester." % r["handle"]))
            db.execute("update requests set status='approved', decided=? where id=?", (now(), r["id"])); db.commit()
            try:
                send_mail(r["email"], "Your %s invite is approved" % SITE, "Good news: your request for %s.%s has been approved.\n\nSign in with this email address (no password, we email you a link):\n\n%s/\n" % (r["handle"], BASE, app_origin()))
            except Exception as e:
                print("approval mail error", e, file=sys.stderr)
                return redirect("/admin?m=" + quote("Approved, but the email to %s failed to send." % r["email"]))
        elif r:
            db.execute("update requests set status='rejected', decided=? where id=?", (now(), r["id"])); db.commit()
        return redirect("/admin")
    if a == "resolve":
        db.execute("update reports set resolved=1 where id=?", (int(req.f("rid") or 0),)); db.commit()
        return redirect("/admin")
    row = db.execute("select * from users where id=?", (int(req.f("id") or 0),)).fetchone()
    if not row:
        return redirect("/admin")
    if a == "delete":
        if row["handle"]: purge_user(db, row["id"], row["handle"])
        else:
            db.execute("delete from users where id=?", (row["id"],)); db.commit()
    elif a in ("suspend", "activate") and row["handle"]:
        db.execute("update users set status=? where id=?", ("suspended" if a == "suspend" else "active", row["id"])); db.commit()
        u = load_user(db.execute("select * from users where id=?", (row["id"],)).fetchone())
        rerender(u)
        if a == "suspend":
            db.execute("delete from sessions where uid=?", (row["id"],)); db.commit()
            drop_alias(row, row["handle"])
        elif row["mail_on"]:
            try:
                db.execute("update users set mail_id=? where id=?", (mailalias.create(row["handle"], row["mail_fwd"] or row["email"]), row["id"])); db.commit()
            except mailalias.MailError as e:
                print("alias restore error", e, file=sys.stderr)
    return redirect("/admin")


def app(env, start):
    try:
        req = Req(env)
        db = init_db() if not os.path.exists(DB) else connect()
        try:
            for method, rx, fn in ROUTES:
                m = rx.match(req.path)
                if m and (method == req.method or (method == "GET" and req.method == "HEAD")):
                    try:
                        r = fn(req, db, *m.groups())
                    except Resp as e:
                        r = e
                    break
            else:
                r = Resp("404 Not Found", simple("Not found", "<p>Nothing here.</p>"))
        finally:
            db.close()
    except Resp as e:
        r = e
    except Exception:
        import traceback; traceback.print_exc()
        r = Resp("500 Server Error", "Something went wrong.", ctype="text/plain")
    start(r.status, r.headers)
    return [r.body]


if __name__ == "__main__":
    from wsgiref.simple_server import make_server, WSGIServer, WSGIRequestHandler
    from socketserver import ThreadingMixIn

    class Threaded(ThreadingMixIn, WSGIServer):
        daemon_threads = True

    class Quiet(WSGIRequestHandler):
        def log_message(self, *a): pass

    init_db().close()
    host, port = os.environ.get("FAR_BIND", "127.0.0.1"), int(os.environ.get("FAR_APP_PORT", "8780"))
    print("far app on %s:%d" % (host, port))
    make_server(host, port, app, server_class=Threaded, handler_class=Quiet).serve_forever()
