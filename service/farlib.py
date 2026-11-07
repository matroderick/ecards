"""Shared helpers for the ecards service (app + CGIs). Standard library only."""
import os, re, hmac, hashlib, sqlite3, time, json

BASE = os.environ.get("FAR_BASE_DOMAIN", "cards.example.com")   # cards live at <handle>.BASE, sign-in at app.BASE
SITE = os.environ.get("FAR_SITE_NAME", "ecards")                   # product name shown in pages and emails
CONTACT = os.environ.get("FAR_CONTACT", "contact@" + BASE)         # shown in Terms/Privacy and card privacy notices
SCHEME = os.environ.get("FAR_SCHEME", "https")
PORT = os.environ.get("FAR_PUBLIC_PORT", "")          # dev only, e.g. ":8770"
DB = os.environ.get("FAR_DB", "/var/lib/far-app/far.db")
USERS_ROOT = os.environ.get("FAR_USERS_ROOT", "/var/www/far-users")
ASSETS = os.environ.get("FAR_ASSETS", "/var/lib/far-app/assets")
LOG_ROOT = os.environ.get("FAR_LOG_DIR", "/var/lib/far-log")
SECRET_FILE = os.environ.get("FAR_SECRET_FILE", "/etc/far-secret")
APP_HOST = "app." + BASE

HANDLE_RE = re.compile(r"[a-z0-9]([a-z0-9-]{0,28}[a-z0-9])?")
RESERVED = set("""www app api admin mail smtp imap pop ftp ns ns1 ns2 dns mx cdn static assets img images media files
info sales hello noreply no-reply mailer-daemon team office careers jobs press ceo president
log logs loc stats status help support contact about terms privacy legal abuse report security postmaster hostmaster
webmaster root test dev staging demo beta login logout signin signup register account accounts dashboard edit
card cards me you far farcx home blog docs doc shop store pay billing invoice invoices vpn git svn
google apple microsoft amazon facebook instagram twitter linkedin github paypal stripe anthropic claude openai""".split())
BAD_WORDS = ("fuck", "shit", "cunt", "nazi", "rape", "porn", "nigg", "paedo", "pedo", "bitch")
INFRA_HOSTS = {"www", "app", "api", "mail", "smtp", "imap", "pop", "ftp", "ns", "ns1", "ns2", "dns", "mx", "cdn"}
NO_TRACK = {"demo"}          # demo card: visits are never logged (its log holds generated sample data)
PERSONA_RESERVED = {"log", "loc", "loc.json", "api", "cgi-bin", "static", "photo", "assets"}


def secret():
    s = os.environ.get("FAR_SECRET")
    if s:
        return s.encode()
    with open(SECRET_FILE, "rb") as f:
        return f.read().strip()


def derive(handle, kind, ver):
    """Stateless per-user tokens (visitor log link, location shortcut)."""
    return hmac.new(secret(), ("%s:%s:%s" % (kind, handle, ver)).encode(), hashlib.sha256).hexdigest()[:32]


def check_token(given, handle, kind, ver):
    return bool(given) and hmac.compare_digest(derive(handle, kind, ver), given)


def connect(readonly=False):
    if readonly:
        c = sqlite3.connect("file:%s?mode=ro" % DB, uri=True, timeout=10)
    else:
        os.makedirs(os.path.dirname(DB), exist_ok=True)
        c = sqlite3.connect(DB, timeout=10)
    c.row_factory = sqlite3.Row
    return c


RESERVED_FILE = os.environ.get("FAR_RESERVED_FILE", "/var/lib/far-app/reserved.txt")   # optional extra reserved names, one per line (edit by hand)
MIN_NEW_HANDLE = 1      # short handles are allowed (invite-only: the admin approves each one)


def extra_reserved():
    try:
        with open(RESERVED_FILE) as f:
            return set(f.read().split())
    except OSError:
        return set()


def handle_error(h):
    if not isinstance(h, str) or not HANDLE_RE.fullmatch(h) or "--" in h or len(h) < MIN_NEW_HANDLE:
        return "Use 1–30 lowercase letters, digits or hyphens (not at the start or end)."
    if h in RESERVED or h in extra_reserved() or any(w in h for w in BAD_WORDS):
        return "That name isn't available."
    return None


def tenant_from_host(host):
    """handle for '<handle>.<BASE>' or None"""
    host = (host or "").split(":")[0].lower().rstrip(".")
    suf = "." + BASE
    if not host.endswith(suf):
        return None
    h = host[: -len(suf)]
    # reserved names can't be claimed at signup, but a few (e.g. "demo") are created by the admin and must resolve
    return h if HANDLE_RE.fullmatch(h) and h not in INFRA_HOSTS else None


def tenant_row(host):
    """Active tenant row for the current Host header, else None. Read-only DB access (CGI use)."""
    h = tenant_from_host(host)
    if not h:
        return None
    try:
        c = connect(readonly=True)
        r = c.execute("select id,handle,status,log_ver,loc_ver from users where handle=?", (h,)).fetchone()
        c.close()
    except Exception:
        return None
    return r if r and r["status"] == "active" else None


def card_origin(handle):
    return "%s://%s.%s%s" % (SCHEME, handle, BASE, PORT)


def app_origin():
    return "%s://%s%s" % (SCHEME, APP_HOST, PORT)


SCHEMA = """
create table if not exists users(
 id integer primary key, email text unique not null, handle text unique, name text, cfg text,
 status text not null default 'active', log_ver integer not null default 1, loc_ver integer not null default 1,
 terms_at integer, created integer not null, last_login integer);
create table if not exists login_tokens(hash text primary key, email text not null, exp integer not null);
create table if not exists sessions(hash text primary key, uid integer not null, csrf text not null, exp integer not null);
create table if not exists reports(id integer primary key, handle text not null, reason text, note text, ip text, ts integer not null, resolved integer not null default 0);
create table if not exists rl(k text not null, ts integer not null);
create index if not exists rl_k on rl(k, ts);
"""


MIGRATIONS = [("users", "mail_on", "integer not null default 0"), ("users", "mail_fwd", "text"), ("users", "mail_id", "text")]
SCHEMA += """create table if not exists requests(id integer primary key, handle text not null, email text not null, ip text, ua text, ts integer not null, status text not null default 'pending', decided integer);
create index if not exists requests_email on requests(email);
"""
SCHEMA += """create table if not exists events(id integer primary key, ts integer not null, kind text not null, uid integer, handle text, email text, ip text, ua text, al text, ref text);
create index if not exists events_ts on events(ts);
"""
SCHEMA += """create table if not exists mail_verify(hash text primary key, uid integer not null, email text not null, exp integer not null);"""


def init_db():
    c = connect()
    c.execute("pragma journal_mode=wal")
    c.executescript(SCHEMA)
    for t, col, decl in MIGRATIONS:
        if col not in [r[1] for r in c.execute("pragma table_info(%s)" % t)]:
            c.execute("alter table %s add column %s %s" % (t, col, decl))
    c.commit()
    return c


GEO_CITY = os.environ.get("FAR_GEO_CITY", "/usr/share/GeoIP/dbip-city-lite.mmdb")
GEO_ASN = os.environ.get("FAR_GEO_ASN", "/usr/share/GeoIP/dbip-asn-lite.mmdb")


def geo(ip):
    """Approximate location + network for an IP from the optional DB-IP files ({} if unavailable)."""
    g = {}
    try:
        import maxminddb
    except ImportError:
        return g
    try:
        if os.path.exists(GEO_CITY):
            with maxminddb.open_database(GEO_CITY) as r:
                d = r.get(ip) or {}
            g["cc"] = (d.get("country") or {}).get("iso_code", "")
            g["city"] = ((d.get("city") or {}).get("names") or {}).get("en", "")
            sub = d.get("subdivisions") or [{}]
            g["region"] = ((sub[0] or {}).get("names") or {}).get("en", "")
            loc = d.get("location") or {}
            if "latitude" in loc:
                g["lat"], g["lon"] = loc["latitude"], loc["longitude"]
        if os.path.exists(GEO_ASN):
            with maxminddb.open_database(GEO_ASN) as r:
                d = r.get(ip) or {}
            g["asn"] = d.get("autonomous_system_number")
            g["org"] = d.get("autonomous_system_organization", "")
    except Exception:
        pass
    return {k: v for k, v in g.items() if v not in ("", None)}


def log_name(host):
    """Which log folder a beacon from this Host belongs to: '_site' = the apex landing page, '_demo' = real visits to
    the demo card, else the tenant handle. None = ignore. (Folders starting with '_' can't clash with handles.)"""
    h = (host or "").split(":")[0].lower().rstrip(".")
    if h in (BASE, "www." + BASE):
        return "_site"
    t = tenant_row(host)
    if not t:
        return None
    return "_demo" if t["handle"] in NO_TRACK else t["handle"]
