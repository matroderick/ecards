"""QR codes and shareable photo cards (phone screen + printable A4 sheet) via Pillow."""
import io, shutil, subprocess, os, re, sys
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageOps
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import build

FONT_DIRS = ["/usr/share/fonts/opentype/inter", "/usr/share/fonts/truetype/inter", "/usr/share/fonts/truetype/dejavu",
             str(Path(__file__).resolve().parent / "fonts")]


def font(size, weight="Regular"):
    for d in FONT_DIRS:
        for name in ("Inter-%s.otf" % weight, "Inter-%s.ttf" % weight, "DejaVuSans-Bold.ttf" if weight != "Regular" else "DejaVuSans.ttf"):
            p = Path(d) / name
            if p.exists():
                return ImageFont.truetype(str(p), size)
    return ImageFont.load_default()


def qr_matrix(text):
    try:
        import qrcode
        q = qrcode.QRCode(border=0, error_correction=qrcode.constants.ERROR_CORRECT_M)
        q.add_data(text); q.make(fit=True)
        return [[bool(c) for c in row] for row in q.get_matrix()]
    except ImportError:
        pass
    exe = shutil.which("qrencode")
    if not exe:
        raise RuntimeError("install python3-qrcode or qrencode")
    out = subprocess.run([exe, "-t", "ASCII", "-m", "0", "-l", "M", "-o", "-", text], capture_output=True, check=True).stdout.decode()
    rows = []
    for line in out.splitlines():
        if line.strip("# ") == "" and "#" not in line:
            continue
        rows.append([line[i] == "#" for i in range(0, len(line), 2)])
    return rows


def qr_svg(text, quiet=2):
    m = qr_matrix(text); n = len(m) + 2 * quiet
    d = "".join("M%d %dh1v1h-1z" % (x + quiet, y + quiet) for y, r in enumerate(m) for x, v in enumerate(r) if v)
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %d %d" shape-rendering="crispEdges"><rect width="%d" height="%d" fill="#fff"/>'
            '<path d="%s" fill="#000"/></svg>' % (n, n, n, n, d))


def qr_image(text, size, quiet=2):
    m = qr_matrix(text); n = len(m) + 2 * quiet
    scale = max(1, size // n)
    img = Image.new("RGB", (n * scale, n * scale), "white")
    px = ImageDraw.Draw(img)
    for y, r in enumerate(m):
        for x, v in enumerate(r):
            if v:
                px.rectangle([(x + quiet) * scale, (y + quiet) * scale, (x + quiet + 1) * scale - 1, (y + quiet + 1) * scale - 1], fill="black")
    return img


def qr_png(text, size=800):
    b = io.BytesIO(); qr_image(text, size).save(b, "PNG"); return b.getvalue()


def _hex(h):
    h = h.lstrip("#"); return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _bg_and_ink(accent):
    # cards sit on the accent colour; very light accents get dark text, everything else white text
    bg = _hex(accent)
    ink = _hex(build.on_accent(accent))
    return bg, ink


def _rounded_photo(photo_bytes, size, radius):
    im = ImageOps.fit(Image.open(io.BytesIO(photo_bytes)).convert("RGB"), (size, size), Image.LANCZOS)
    mask = Image.new("L", (size, size), 0); ImageDraw.Draw(mask).rounded_rectangle([0, 0, size - 1, size - 1], radius, fill=255)
    im.putalpha(mask); return im


def _fit_text(draw, text, fnt_fn, max_w, start, weight, floor=28):
    s = start
    while s > floor and draw.textlength(text, font=fnt_fn(s, weight)) > max_w:
        s -= 2
    return fnt_fn(s, weight)


def phone_card(name, p, url, shown_url, photo_bytes):
    W, H = 1170, 1560
    bg, ink = _bg_and_ink(p.get("accent", "#334155"))
    muted = tuple(int(c * 0.72 + b * 0.28) for c, b in zip(ink, bg))
    img = Image.new("RGB", (W, H), bg); d = ImageDraw.Draw(img)
    label = p.get("label", "")
    d.text((86, 70), label, font=_fit_text(d, label, font, W - 172, 118, "Bold", 56), fill=ink)
    if p.get("title"):
        d.text((88, 318), p["title"].upper(), font=_fit_text(d, p["title"].upper(), font, 700, 34, "Regular", 22), fill=muted)
    d.text((88, 372), name, font=_fit_text(d, name, font, 700, 84, "SemiBold", 46), fill=ink)
    if p.get("org"):
        d.text((88, 480), p["org"], font=_fit_text(d, p["org"], font, 700, 38, "Regular", 24), fill=muted)
    img.paste(_rounded_photo(photo_bytes, 228, 36), (858, 222), _rounded_photo(photo_bytes, 228, 36))
    box = 738
    d.rounded_rectangle([216, 630, 216 + box, 630 + box], 56, fill="white")
    qr = qr_image(url, box - 100, quiet=0)
    img.paste(qr.resize((box - 100, box - 100), Image.NEAREST), (216 + 50, 630 + 50))
    f = font(42)
    d.text(((W - d.textlength(shown_url, font=f)) / 2, 1440), shown_url, font=f, fill=muted)
    b = io.BytesIO(); img.save(b, "PNG", optimize=True); return b.getvalue()


def _business_card(name, p, url, shown_url, photo_bytes):
    W, H = 1004, 650  # 85 x 55 mm at 300 dpi
    bg, ink = _bg_and_ink(p.get("accent", "#334155"))
    muted = tuple(int(c * 0.72 + b * 0.28) for c, b in zip(ink, bg))
    img = Image.new("RGB", (W, H), bg); d = ImageDraw.Draw(img)
    ph = _rounded_photo(photo_bytes, 150, 28); img.paste(ph, (48, 48), ph)
    d.text((48, 232), name, font=_fit_text(d, name, font, 520, 56, "Bold", 34), fill=ink)
    y = 306
    for t in (p.get("title"), p.get("org")):
        if t:
            d.text((48, y), t, font=_fit_text(d, t, font, 520, 36, "Regular", 24), fill=muted); y += 48
    d.text((48, H - 92), shown_url, font=_fit_text(d, shown_url, font, 520, 34, "SemiBold", 22), fill=ink)
    box = 400
    d.rounded_rectangle([W - box - 48, (H - box) // 2, W - 48, (H - box) // 2 + box], 28, fill="white")
    q = qr_image(url, box - 48, quiet=0).resize((box - 48, box - 48), Image.NEAREST)
    img.paste(q, (W - box - 48 + 24, (H - box) // 2 + 24))
    return img


def print_sheet(name, p, url, shown_url, photo_bytes):
    """A4 sheet, 10 cards of 85x55 mm, as PDF at 300 dpi with light cut lines."""
    PW, PH = 2480, 3508
    card = _business_card(name, p, url, shown_url, photo_bytes)
    cw, ch = card.size
    x0, y0 = (PW - 2 * cw) // 2, (PH - 5 * ch) // 2
    sheet = Image.new("RGB", (PW, PH), "white"); d = ImageDraw.Draw(sheet)
    for r in range(5):
        for c in range(2):
            sheet.paste(card, (x0 + c * cw, y0 + r * ch))
    for c in range(3):
        x = x0 + c * cw; d.line([(x, y0 - 40), (x, y0 - 10)], fill="#999", width=2); d.line([(x, y0 + 5 * ch + 10), (x, y0 + 5 * ch + 40)], fill="#999", width=2)
    for r in range(6):
        y = y0 + r * ch; d.line([(x0 - 40, y), (x0 - 10, y)], fill="#999", width=2); d.line([(x0 + 2 * cw + 10, y), (x0 + 2 * cw + 40, y)], fill="#999", width=2)
    b = io.BytesIO(); sheet.save(b, "PDF", resolution=300.0); return b.getvalue()
