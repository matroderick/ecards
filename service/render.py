"""Render one user's cards (static HTML) into FAR_USERS_ROOT/<handle>/ using the shared build.py templates."""
import base64, io, json, re, shutil, sys, os
from html import escape as html_escape
from pathlib import Path
from PIL import Image, ImageDraw, ImageOps
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import build
from farlib import *

LOG_PAGE = Path(__file__).resolve().parent.parent / "server" / "log.html"
KEEP = {"log", "loc.json", "index.html"}


def person_dict(name):
    parts = name.split()
    return {"name": name, "given": " ".join(parts[:-1]) or name, "family": parts[-1] if len(parts) > 1 else ""}


def asset_dir(uid, slug):
    return Path(ASSETS) / str(uid) / slug


def avatar(name, accent):
    from cardimg import font, _hex
    ini = "".join(w[0] for w in name.split()[:2]).upper() or "?"
    im = Image.new("RGB", (256, 256), _hex(accent)); d = ImageDraw.Draw(im)
    f = font(112, "Bold"); w = d.textlength(ini, font=f)
    d.text(((256 - w) / 2, 62), ini, font=f, fill=_hex(build.on_accent(accent)))
    b = io.BytesIO(); im.save(b, "JPEG", quality=88); return b.getvalue()


def load_photo(uid, slug, name, accent):
    f = asset_dir(uid, slug) / "photo.jpg"
    return f.read_bytes() if f.exists() else avatar(name, accent)


def load_logo(uid, slug):
    for ext in (".png", ".jpg", ".webp", ".svg"):
        f = asset_dir(uid, slug) / ("logo" + ext)
        if f.exists():
            return "logo" + ext, f.read_bytes()
    return None, None


def default_slug(cfg):
    ps = cfg["personas"]
    d = cfg.get("default")
    if d in ps:
        return d
    return next((k for k, v in ps.items() if not v.get("hidden")), next(iter(ps)))


def _put(path, data):
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data if isinstance(data, bytes) else data.encode("utf-8"))
    os.replace(tmp, path)


def redirect_page(target):
    t = html_escape(target)
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            '<title>Redirecting</title><link rel="canonical" href="%s"><meta http-equiv="refresh" content="0;url=%s">'
            '<script>location.replace(%s+location.search+location.hash)</script></head>'
            '<body><p><a href="%s">Continue</a></p></body></html>' % (t, t, json.dumps(target), t))


def suspended_stub(root):
    _put(root / "index.html", '<!doctype html><meta charset="utf-8"><meta name="robots" content="noindex"><meta name="viewport" content="width=device-width,initial-scale=1">'
         '<title>Unavailable</title><body style="font:16px system-ui;display:grid;place-items:center;height:100vh;margin:0;color:#444"><p>This card is not available.</p>')


def render_user(u):
    """u: dict(id, handle, name, cfg(dict), status)"""
    root = Path(USERS_ROOT) / u["handle"]
    root.mkdir(parents=True, exist_ok=True)
    for child in list(root.iterdir()):
        if u["status"] != "active" and child.name != "loc.json" or (child.is_dir() and child.name not in u["cfg"]["personas"] and child.name != "log"):
            shutil.rmtree(child) if child.is_dir() else (child.unlink() if child.name not in KEEP else None)
    if u["status"] != "active":
        suspended_stub(root); return
    cfg = u["cfg"]; personas = cfg["personas"]; person = person_dict(u["name"])
    base = card_origin(u["handle"])
    privacy = build.privacy_html(app_origin() + "/report?h=" + u["handle"])
    dflt = default_slug(cfg)
    for key, p in personas.items():
        photo = load_photo(u["id"], key, u["name"], p.get("accent", "#2563eb"))
        b64 = base64.b64encode(photo).decode("ascii"); uri = "data:image/jpeg;base64," + b64
        logo_name, logo = load_logo(u["id"], key)
        url = "%s/%s/" % (base, key)
        vcf = "%s-%s.vcf" % (u["handle"], key)
        d = root / (key + ".new")
        if d.exists():
            shutil.rmtree(d)
        d.mkdir()
        _put(d / "photo.jpg", photo)
        if logo:
            _put(d / logo_name, logo)
        _put(d / vcf, build.make_vcard(person, p, b64, key, url))
        _put(d / "index.html", build.make_page(person, p, key, personas, "", "../", vcf, uri, url, url + "photo.jpg", logo_name, privacy))
        if (root / key).exists():
            shutil.rmtree(root / key)
        os.replace(d, root / key)
    # "/" only redirects to the default card's permanent address, so the default can change without breaking any card's URL
    _put(root / "index.html", redirect_page("%s/%s/" % (base, dflt)))
    (root / "log").mkdir(exist_ok=True)
    if LOG_PAGE.exists():
        _put(root / "log" / "index.html", LOG_PAGE.read_bytes())


def preview_html(handle, name, key, p, siblings, photo, logo):
    """Same page the visitor would get, with assets inlined, for the editor's live preview."""
    b64 = base64.b64encode(photo).decode("ascii")
    logo_uri = None
    if logo:
        mime = "image/png" if logo[:4] == b"\x89PNG" else "image/jpeg" if logo[:2] == b"\xff\xd8" else "image/svg+xml" if logo.lstrip()[:1] == b"<" else "image/webp"
        logo_uri = "data:%s;base64,%s" % (mime, base64.b64encode(logo).decode("ascii"))
    url = "%s/%s/" % (card_origin(handle), key)
    html = build.make_page(person_dict(name), p, key, siblings, "", "#", "x.vcf", "data:image/jpeg;base64," + b64, url, url, logo_uri,
                           build.privacy_html(None))
    block = ("<script>document.addEventListener('click',function(e){if(e.target.closest('a')||e.target.closest('.pv .forget'))e.preventDefault()},true);"
             "window.__farNoTrack=1;</script>")
    return html.replace("</body>", block + "</body>")
