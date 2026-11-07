#!/usr/bin/env python3
"""Card page, vCard and QR templates (Python 3.8+, standard library only).

Imported by service/render.py, which writes one static site per user. No command-line entry point.
Environment: FAR_CONTACT is the address shown in the visitor privacy notice.
"""
from urllib.parse import urlparse
import base64
import datetime
import html
import json
import re
import os
from pathlib import Path

CONTACT = os.environ.get("FAR_CONTACT", "contact@example.com")

ICONS = {
    "calendar": '<rect x="3" y="4" width="18" height="18" rx="2" ry="2"/><line x1="16" y1="2" x2="16" y2="6"/>'
                '<line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/>',
    "user-plus": '<path d="M16 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="8.5" cy="7" r="4"/>'
                 '<line x1="20" y1="8" x2="20" y2="14"/><line x1="23" y1="11" x2="17" y2="11"/>',
    "phone": '<path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 '
             '19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72 12.84 12.84 0 0 0 .7 2.81 '
             '2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45 12.84 12.84 0 0 0 '
             '2.81.7A2 2 0 0 1 22 16.92z"/>',
    "mail": '<path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z"/>'
            '<polyline points="22,6 12,13 2,6"/>',
    "globe": '<circle cx="12" cy="12" r="10"/><line x1="2" y1="12" x2="22" y2="12"/>'
             '<path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/>',
    "link": '<path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/>'
            '<path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/>',
}

CSS = """
:root{--bg:#f4f5f7;--card:#fff;--text:#14171c;--muted:#5b6470;--line:#e3e6ea;--banner:BANNERCOL;--link:LINKLT;--rule:RULELT;--accent:ACCENT;--on-accent:ONACCENT}
@media(prefers-color-scheme:dark){:root{--bg:#0f1115;--card:#171a20;--text:#eceef2;--muted:#9aa3af;--line:#262b33;--accent:DARKACC;--link:DARKACC;--rule:DARKACC;--on-accent:DARKON}}
*{box-sizing:border-box}
html,body{height:100%}
body{margin:0;height:100vh;height:100dvh;display:flex;justify-content:center;align-items:center;padding:12px 16px;
background:var(--bg);color:var(--text);font:16px/1.4 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
.card{position:relative;width:100%;max-width:420px;height:100%;max-height:860px;display:flex;flex-direction:column;background:var(--card);border:1px solid var(--line);border-radius:20px;overflow:hidden}
.top,.who{flex:none}
.body{flex:1;min-height:0;overflow-y:auto;overflow-x:hidden;scrollbar-width:none}.body::-webkit-scrollbar{display:none}
.fit{transform-origin:top center}
.top{height:96px;background:var(--banner);position:relative}
.chip{position:absolute;top:14px;left:14px;background:#fff;border-radius:12px;padding:8px 10px;display:flex;align-items:center}
.chip img{display:block;height:24px;width:auto;max-width:112px}
.chip.bare{background:none;padding:0;top:20px;left:20px}.chip.bare img{height:30px;max-width:150px}
.who{text-align:center;padding:0 20px 8px;margin-top:-56px;position:relative}
.who img{width:112px;height:112px;border-radius:50%;object-fit:cover;border:4px solid var(--card);background:var(--line)}
h1{margin:10px 0 2px;font-size:24px}
.title{margin:0;color:var(--muted)}
.org{margin:2px 0 0;font-weight:600}
.loc{margin:8px 0 0;font-size:14px;line-height:1.25;color:var(--muted)}.loc small{display:block;font-size:11.5px;line-height:1.2;margin-top:1px;opacity:.8}.loc a{color:inherit;text-decoration:none;border-bottom:1px dotted var(--muted)}
.note{margin:12px 0 0;color:var(--muted);font-size:15px}
.actions{display:grid;gap:10px;padding:16px 20px 20px}
a.btn{display:flex;align-items:center;gap:12px;padding:14px 16px;border-radius:14px;border:1px solid var(--line);
color:var(--text);text-decoration:none;font-weight:500}
a.btn.primary{background:var(--accent);border-color:var(--accent);color:var(--on-accent);font-weight:600;justify-content:center}
a.btn.pill{justify-content:center;border:2px solid var(--accent);font-weight:600}
a.btn:active{transform:scale(.99)}
.i{width:20px;height:20px;flex:none}
html{touch-action:pan-y;overflow-x:clip}
body{overflow-x:hidden}
.card{will-change:transform}
.in-l .card{transform:translateX(110vw)}
.in-r .card{transform:translateX(-110vw)}
.cap{margin:0;padding:2px 20px 10px;text-align:center;font-size:12px;font-weight:600;letter-spacing:.06em;text-transform:uppercase;color:var(--muted)}
.i.b{fill:currentColor;stroke:none}
.socials{display:flex;justify-content:center;flex-wrap:wrap;gap:12px;padding:14px 20px 0}
.socials a{width:46px;height:46px;border-radius:50%;border:1px solid var(--line);display:flex;align-items:center;justify-content:center;color:var(--text)}
.socials a:active{transform:scale(.96)}
.socials svg{width:22px;height:22px;fill:currentColor}
.other{flex:none;border-top:1px solid var(--line);padding:14px 20px 18px;text-align:center;font-size:14px;color:var(--muted)}
.other a,.other .cur{text-decoration:none;font-weight:600;margin:0 8px;white-space:nowrap}
.other a{color:var(--link)}
.other .cur{color:var(--text);border-bottom:2px solid var(--rule);padding-bottom:2px}
@media(max-height:780px){.top{height:68px}.who{margin-top:-46px;padding-bottom:4px}.who img{width:92px;height:92px}h1{font-size:21px;margin:6px 0 0}.org{margin-top:0}.loc{margin-top:4px}.note{margin-top:6px}.socials{padding-top:8px;gap:10px}.socials a{width:40px;height:40px}.actions{gap:8px;padding:10px 16px 12px}a.btn{padding:10px 14px}.other{padding:10px 16px 12px}}
@media(max-height:640px){.top{height:52px}.who{margin-top:-36px}.who img{width:72px;height:72px;border-width:3px}h1{font-size:19px}.socials a{width:36px;height:36px}.socials svg{width:19px;height:19px}.actions{gap:6px;padding:8px 14px 10px}a.btn{padding:8px 12px;font-size:15px}.other{padding:8px 14px 10px;font-size:13px}}
/* texture + relief */
:root{--hi:rgba(255,255,255,.9);--sh:rgba(20,30,50,.10);--sh2:rgba(20,30,50,.06)}
@media(prefers-color-scheme:dark){:root{--hi:rgba(255,255,255,.07);--sh:rgba(0,0,0,.55);--sh2:rgba(0,0,0,.35)}}
body{background:radial-gradient(120% 80% at 50% 0%,var(--card) 0,var(--bg) 62%) fixed,var(--bg)}
.card{z-index:1;border-color:color-mix(in srgb,var(--line) 80%,transparent);
 background:linear-gradient(180deg,color-mix(in srgb,var(--card) 100%,#fff 0%) 0,var(--card) 55%,color-mix(in srgb,var(--card) 94%,var(--text) 6%) 100%);
 box-shadow:0 1px 0 var(--hi) inset,0 1px 2px var(--sh),0 8px 18px -6px var(--sh),0 28px 60px -18px var(--sh)}
.top{background-image:linear-gradient(180deg,rgba(255,255,255,.14),rgba(0,0,0,.14));box-shadow:0 -1px 0 rgba(255,255,255,.25) inset,0 2px 6px -2px var(--sh)}
.who img{box-shadow:0 0 0 1px var(--line),0 6px 16px -4px var(--sh),0 2px 4px var(--sh2)}
a.btn{background:linear-gradient(180deg,var(--card),color-mix(in srgb,var(--card) 93%,var(--text) 7%));box-shadow:0 1px 0 var(--hi) inset,0 1px 2px var(--sh2),0 3px 8px -4px var(--sh);transition:box-shadow .15s,transform .15s}
a.btn.primary{background:linear-gradient(180deg,color-mix(in srgb,var(--accent) 88%,#fff 12%),var(--accent) 55%,color-mix(in srgb,var(--accent) 90%,#000 10%));box-shadow:0 1px 0 rgba(255,255,255,.35) inset,0 -1px 0 rgba(0,0,0,.15) inset,0 2px 4px color-mix(in srgb,var(--accent) 35%,transparent),0 8px 16px -8px color-mix(in srgb,var(--accent) 60%,transparent)}
a.btn.pill{background:linear-gradient(180deg,var(--card),color-mix(in srgb,var(--accent) 7%,var(--card)))}
a.btn:active{box-shadow:0 2px 4px rgba(0,0,0,.18) inset;transform:translateY(1px)}
.socials a{background:linear-gradient(180deg,var(--card),color-mix(in srgb,var(--card) 92%,var(--text) 8%));box-shadow:0 1px 0 var(--hi) inset,0 1px 2px var(--sh2),0 3px 8px -4px var(--sh)}
.other{background:color-mix(in srgb,var(--card) 96%,var(--text) 4%);box-shadow:0 1px 0 var(--hi) inset}
/* a little more depth */
:root{--sh:rgba(20,30,50,.16);--sh2:rgba(20,30,50,.10);--edge:rgba(20,30,50,.14)}
@media(prefers-color-scheme:dark){:root{--sh:rgba(0,0,0,.65);--sh2:rgba(0,0,0,.45);--edge:rgba(0,0,0,.55)}}
.card{box-shadow:0 1px 0 var(--hi) inset,0 -1px 0 var(--edge) inset,0 1px 1px var(--sh),0 6px 10px -4px var(--sh),0 18px 28px -10px var(--sh),0 42px 70px -24px var(--sh)}
.top{box-shadow:0 -1px 0 rgba(255,255,255,.3) inset,0 6px 10px -6px rgba(0,0,0,.35),0 1px 0 rgba(0,0,0,.18)}
.who img{box-shadow:0 0 0 1px var(--line),0 2px 3px var(--sh),0 10px 18px -6px var(--sh),inset 0 -3px 6px rgba(0,0,0,.18),inset 0 2px 3px rgba(255,255,255,.25)}
a.btn{box-shadow:0 1px 0 var(--hi) inset,0 -1px 0 var(--edge) inset,0 2px 0 var(--edge),0 4px 8px -3px var(--sh)}
a.btn.primary{box-shadow:0 1px 0 rgba(255,255,255,.4) inset,0 -2px 0 rgba(0,0,0,.18) inset,0 3px 0 color-mix(in srgb,var(--accent) 65%,#000 35%),0 8px 14px -6px color-mix(in srgb,var(--accent) 70%,transparent)}
a.btn:active{box-shadow:0 2px 5px rgba(0,0,0,.22) inset;transform:translateY(2px)}
.socials a{box-shadow:0 1px 0 var(--hi) inset,0 -1px 0 var(--edge) inset,0 2px 0 var(--edge),0 4px 8px -3px var(--sh)}

a.btn.primary{background:var(--accent);box-shadow:0 2px 6px -2px color-mix(in srgb,var(--accent) 60%,transparent)}
a.btn.primary:active{box-shadow:none;transform:translateY(1px)}
a.btn.pill{box-shadow:0 2px 6px -3px var(--sh)}
"""


SOCIAL_PATHS = {
    "instagram": "M7.0301.084c-1.2768.0602-2.1487.264-2.911.5634-.7888.3075-1.4575.72-2.1228 1.3877-.6652.6677-1.075 1.3368-1.3802 2.127-.2954.7638-.4956 1.6365-.552 2.914-.0564 1.2775-.0689 1.6882-.0626 4.947.0062 3.2586.0206 3.6671.0825 4.9473.061 1.2765.264 2.1482.5635 2.9107.308.7889.72 1.4573 1.388 2.1228.6679.6655 1.3365 1.0743 2.1285 1.38.7632.295 1.6361.4961 2.9134.552 1.2773.056 1.6884.069 4.9462.0627 3.2578-.0062 3.668-.0207 4.9478-.0814 1.28-.0607 2.147-.2652 2.9098-.5633.7889-.3086 1.4578-.72 2.1228-1.3881.665-.6682 1.0745-1.3378 1.3795-2.1284.2957-.7632.4966-1.636.552-2.9124.056-1.2809.0692-1.6898.063-4.948-.0063-3.2583-.021-3.6668-.0817-4.9465-.0607-1.2797-.264-2.1487-.5633-2.9117-.3084-.7889-.72-1.4568-1.3876-2.1228C21.2982 1.33 20.628.9208 19.8378.6165 19.074.321 18.2017.1197 16.9244.0645 15.6471.0093 15.236-.005 11.977.0014 8.718.0076 8.31.0215 7.0301.0839m.1402 21.6932c-1.17-.0509-1.8053-.2453-2.2287-.408-.5606-.216-.96-.4771-1.3819-.895-.422-.4178-.6811-.8186-.9-1.378-.1644-.4234-.3624-1.058-.4171-2.228-.0595-1.2645-.072-1.6442-.079-4.848-.007-3.2037.0053-3.583.0607-4.848.05-1.169.2456-1.805.408-2.2282.216-.5613.4762-.96.895-1.3816.4188-.4217.8184-.6814 1.3783-.9003.423-.1651 1.0575-.3614 2.227-.4171 1.2655-.06 1.6447-.072 4.848-.079 3.2033-.007 3.5835.005 4.8495.0608 1.169.0508 1.8053.2445 2.228.408.5608.216.96.4754 1.3816.895.4217.4194.6816.8176.9005 1.3787.1653.4217.3617 1.056.4169 2.2263.0602 1.2655.0739 1.645.0796 4.848.0058 3.203-.0055 3.5834-.061 4.848-.051 1.17-.245 1.8055-.408 2.2294-.216.5604-.4763.96-.8954 1.3814-.419.4215-.8181.6811-1.3783.9-.4224.1649-1.0577.3617-2.2262.4174-1.2656.0595-1.6448.072-4.8493.079-3.2045.007-3.5825-.006-4.848-.0608M16.953 5.5864A1.44 1.44 0 1 0 18.39 4.144a1.44 1.44 0 0 0-1.437 1.4424M5.8385 12.012c.0067 3.4032 2.7706 6.1557 6.173 6.1493 3.4026-.0065 6.157-2.7701 6.1506-6.1733-.0065-3.4032-2.771-6.1565-6.174-6.1498-3.403.0067-6.156 2.771-6.1496 6.1738M8 12.0077a4 4 0 1 1 4.008 3.9921A3.9996 3.9996 0 0 1 8 12.0077",
 "linkedin": "M20.447 20.452h-3.554v-5.569c0-1.328-.027-3.037-1.852-3.037-1.853 0-2.136 1.445-2.136 2.939v5.667H9.351V9h3.414v1.561h.046c.477-.9 1.637-1.85 3.37-1.85 3.601 0 4.267 2.37 4.267 5.455v6.286zM5.337 7.433c-1.144 0-2.063-.926-2.063-2.065 0-1.138.92-2.063 2.063-2.063 1.14 0 2.064.925 2.064 2.063 0 1.139-.925 2.065-2.064 2.065zm1.782 13.019H3.555V9h3.564v11.452zM22.225 0H1.771C.792 0 0 .774 0 1.729v20.542C0 23.227.792 24 1.771 24h20.451C23.2 24 24 23.227 24 22.271V1.729C24 .774 23.2 0 22.222 0h.003z",
 "github": "M12 .297c-6.63 0-12 5.373-12 12 0 5.303 3.438 9.8 8.205 11.385.6.113.82-.258.82-.577 0-.285-.01-1.04-.015-2.04-3.338.724-4.042-1.61-4.042-1.61C4.422 18.07 3.633 17.7 3.633 17.7c-1.087-.744.084-.729.084-.729 1.205.084 1.838 1.236 1.838 1.236 1.07 1.835 2.809 1.305 3.495.998.108-.776.417-1.305.76-1.605-2.665-.3-5.466-1.332-5.466-5.93 0-1.31.465-2.38 1.235-3.22-.135-.303-.54-1.523.105-3.176 0 0 1.005-.322 3.3 1.23.96-.267 1.98-.399 3-.405 1.02.006 2.04.138 3 .405 2.28-1.552 3.285-1.23 3.285-1.23.645 1.653.24 2.873.12 3.176.765.84 1.23 1.91 1.23 3.22 0 4.61-2.805 5.625-5.475 5.92.42.36.81 1.096.81 2.22 0 1.606-.015 2.896-.015 3.286 0 .315.21.69.825.57C20.565 22.092 24 17.592 24 12.297c0-6.627-5.373-12-12-12",
 "whatsapp": "M17.472 14.382c-.297-.149-1.758-.867-2.03-.967-.273-.099-.471-.148-.67.15-.197.297-.767.966-.94 1.164-.173.199-.347.223-.644.075-.297-.15-1.255-.463-2.39-1.475-.883-.788-1.48-1.761-1.653-2.059-.173-.297-.018-.458.13-.606.134-.133.298-.347.446-.52.149-.174.198-.298.298-.497.099-.198.05-.371-.025-.52-.075-.149-.669-1.612-.916-2.207-.242-.579-.487-.5-.669-.51-.173-.008-.371-.01-.57-.01-.198 0-.52.074-.792.372-.272.297-1.04 1.016-1.04 2.479 0 1.462 1.065 2.875 1.213 3.074.149.198 2.096 3.2 5.077 4.487.709.306 1.262.489 1.694.625.712.227 1.36.195 1.871.118.571-.085 1.758-.719 2.006-1.413.248-.694.248-1.289.173-1.413-.074-.124-.272-.198-.57-.347m-5.421 7.403h-.004a9.87 9.87 0 01-5.031-1.378l-.361-.214-3.741.982.998-3.648-.235-.374a9.86 9.86 0 01-1.51-5.26c.001-5.45 4.436-9.884 9.888-9.884 2.64 0 5.122 1.03 6.988 2.898a9.825 9.825 0 012.893 6.994c-.003 5.45-4.437 9.884-9.885 9.884m8.413-18.297A11.815 11.815 0 0012.05 0C5.495 0 .16 5.335.157 11.892c0 2.096.547 4.142 1.588 5.945L.057 24l6.305-1.654a11.882 11.882 0 005.683 1.448h.005c6.554 0 11.89-5.335 11.893-11.893a11.821 11.821 0 00-3.48-8.413Z",
 "telegram": "M11.944 0A12 12 0 0 0 0 12a12 12 0 0 0 12 12 12 12 0 0 0 12-12A12 12 0 0 0 12 0a12 12 0 0 0-.056 0zm4.962 7.224c.1-.002.321.023.465.14a.506.506 0 0 1 .171.325c.016.093.036.306.02.472-.18 1.898-.962 6.502-1.36 8.627-.168.9-.499 1.201-.82 1.23-.696.065-1.225-.46-1.9-.902-1.056-.693-1.653-1.124-2.678-1.8-1.185-.78-.417-1.21.258-1.91.177-.184 3.247-2.977 3.307-3.23.007-.032.014-.15-.056-.212s-.174-.041-.249-.024c-.106.024-1.793 1.14-5.061 3.345-.48.33-.913.49-1.302.48-.428-.008-1.252-.241-1.865-.44-.752-.245-1.349-.374-1.297-.789.027-.216.325-.437.893-.663 3.498-1.524 5.83-2.529 6.998-3.014 3.332-1.386 4.025-1.627 4.476-1.635z",
 "facebook": "M9.101 23.691v-7.98H6.627v-3.667h2.474v-1.58c0-4.085 1.848-5.978 5.858-5.978.401 0 .955.042 1.468.103a8.68 8.68 0 0 1 1.141.195v3.325a8.623 8.623 0 0 0-.653-.036 26.805 26.805 0 0 0-.733-.009c-.707 0-1.259.096-1.675.309a1.686 1.686 0 0 0-.679.622c-.258.42-.374.995-.374 1.752v1.297h3.919l-.386 2.103-.287 1.564h-3.246v8.245C19.396 23.238 24 18.179 24 12.044c0-6.627-5.373-12-12-12s-12 5.373-12 12c0 5.628 3.874 10.35 9.101 11.647Z"
}
SOCIAL_LABELS = {'linkedin': 'LinkedIn', 'github': 'GitHub', 'whatsapp': 'WhatsApp', 'telegram': 'Telegram', 'facebook': 'Facebook', 'instagram': 'Instagram'}

LOGO_EXTS = {".svg", ".png", ".jpg", ".jpeg", ".webp"}


def on_accent(hexcolor):
    """Black or white text, whichever is more readable on the accent colour."""
    r, g, b = (int(hexcolor[i:i + 2], 16) for i in (1, 3, 5))
    return "#14171c" if (r * 299 + g * 587 + b * 114) / 1000 >= 150 else "#ffffff"


def lum(h):
    r, g, b = (int(h[i:i + 2], 16) for i in (1, 3, 5))
    return (r * 299 + g * 587 + b * 114) / 1000


def dark_accent(h):
    """Brand colour for dark mode: unchanged if bright enough, else blended toward white."""
    if lum(h) >= 140:
        return h
    r, g, b = (int(h[i:i + 2], 16) for i in (1, 3, 5))
    for t in range(5, 101, 5):
        c = "#%02x%02x%02x" % tuple(round(v + (255 - v) * t / 100) for v in (r, g, b))
        if lum(c) >= 170:
            return c
    return "#ffffff"


def company_label(p, key, x):
    return x.get("label") or "%s on %s" % (p.get("label", key), SOCIAL_LABELS[x["type"]])


def brand_icon(kind):
    return '<svg class="i b" viewBox="0 0 24 24" aria-hidden="true"><path d="%s"/></svg>' % SOCIAL_PATHS[kind]


SWIPE_HEAD = ""
SWIPE_JS = """<script>
(function(){
if(window.top!==window)return;
var prev=__PREV__,next=__NEXT__,card=document.querySelector('.card');
if(!prev&&!next)return;
var rm=window.matchMedia&&matchMedia('(prefers-reduced-motion: reduce)').matches;
function mk(url,side){if(!url)return null;var f=document.createElement('iframe');f.src=url;f.tabIndex=-1;f.setAttribute('aria-hidden','true');
 f.style.cssText='position:fixed;top:0;height:100%;width:100%;border:0;z-index:5;background:transparent;'+side+':-100%;will-change:transform;pointer-events:none;';
 document.body.appendChild(f);return f;}
var pf,nf;
function load(){pf=mk(prev,'left');nf=(next===prev)?null:mk(next,'left');if(nf)nf.style.left='100%';}
if(document.readyState==='complete')load();else addEventListener('load',load);
function sideOf(dx){return dx<0?'n':'p';}
function move(dx,anim){var t=anim||'none';
 [card,pf,nf].forEach(function(el){if(!el)return;el.style.transition=t;el.style.transform=dx?'translateX('+dx+'px)':'';});}
function go(dir,url){
 if(url){try{window.dispatchEvent(new CustomEvent('far:nav',{detail:{url:url,dir:dir}}));}catch(e){}}
 if(rm||!url){if(url)location.href=url;return;}
 var w=window.innerWidth,end=(dir==='l'?-w:w);
 if(dir==='l'&&!nf&&pf&&next===prev){pf.style.left='100%';nf=pf;}
 if(dir==='r'&&next===prev&&nf&&!pf){nf.style.left='-100%';pf=nf;}
 move(end,'transform .3s cubic-bezier(.2,.8,.2,1)');
 setTimeout(function(){location.href=url;},300);}
function back(){move(0,'transform .22s ease');}
window.addEventListener('pageshow',function(){move(0,'none');});
var sx=0,sy=0,st=0,dx=0,lock=null;
function fix(dx){if(prev===prev&&next===prev&&pf){pf.style.left=dx<0?'100%':'-100%';}}
document.addEventListener('touchstart',function(e){lock=e.touches.length===1?null:'n';if(lock)return;
 sx=e.touches[0].clientX;sy=e.touches[0].clientY;st=Date.now();dx=0;},{passive:true});
document.addEventListener('touchmove',function(e){if(lock==='n'||lock==='y')return;
 var t=e.touches[0];dx=t.clientX-sx;var dy=t.clientY-sy;
 if(lock===null){if(Math.abs(dx)<8&&Math.abs(dy)<8)return;lock=Math.abs(dx)>Math.abs(dy)*1.2?'x':'y';}
 if(lock==='x'){fix(dx);move(dx,'none');}},{passive:true});
document.addEventListener('touchend',function(){var was=lock;lock=null;if(was!=='x')return;
 var v=Math.abs(dx)/Math.max(1,Date.now()-st);
 if(Math.abs(dx)>80||(v>0.5&&Math.abs(dx)>30)){if(dx<0)go('l',next);else go('r',prev);}else back();},{passive:true});
document.addEventListener('touchcancel',function(){if(lock==='x')back();lock=null;},{passive:true});
document.addEventListener('keydown',function(e){if(e.key==='ArrowLeft'){fix(1);go('r',prev);}else if(e.key==='ArrowRight'){fix(-1);go('l',next);}});
})();
</script>"""

PRIVACY_TEXT = ("To see how this is used, this page records your IP address, approximate location, device, browser and "
                "the links you tap. No cookies. Kept for 180 days, then deleted.<br>Questions: " + CONTACT)
def privacy_html(report_url=None):
    rep = ('<a href="%s" class="rep" rel="noopener">Report this card</a>' % report_url) if report_url else ""
    return ('<div class="pv"><button type="button" aria-label="Privacy notice" aria-expanded="false" aria-controls="pvtip">i</button>'
            '<div class="tip" id="pvtip" role="tooltip"><b>Privacy</b><br><span class="pvt">' + PRIVACY_TEXT + '</span>'
            '<a href="#" class="forget">Forget me</a>' + rep + '</div></div>')


PRIVACY_HTML = privacy_html()
PRIVACY_CSS = """
.pv{position:absolute;left:10px;bottom:10px;z-index:4}
.pv button{width:22px;height:22px;border-radius:50%;border:1px solid var(--line);background:var(--card,transparent);color:var(--muted);font:700 12px/1 Georgia,serif;font-style:italic;cursor:pointer;padding:0;display:flex;align-items:center;justify-content:center}
.pv button:hover,.pv button:focus-visible{color:var(--text,var(--ink));border-color:var(--muted);outline:none}
.pv .tip{display:none;position:absolute;left:0;bottom:30px;width:min(250px,calc(100vw - 48px));padding:10px 12px;border-radius:12px;background:var(--text,var(--ink));color:var(--card,var(--bg));font:12px/1.45 system-ui,-apple-system,"Segoe UI",sans-serif;text-align:left;box-shadow:0 6px 24px rgba(0,0,0,.25)}
.pv .forget{display:block;margin-top:4px;width:max-content;color:inherit;font-weight:600;text-decoration:underline}
.pv .rep{display:block;margin-top:4px;width:max-content;color:inherit;opacity:.7;font-size:11px;text-decoration:underline}
.pv.open .tip{display:block}
@media(hover:hover){.pv:hover .tip{display:block}}
"""
PRIVACY_JS = """<script>
(function(){var p=document.querySelector('.pv');if(!p)return;var b=p.querySelector('button');
function set(o){p.classList.toggle('open',o);b.setAttribute('aria-expanded',o?'true':'false');}
b.addEventListener('click',function(e){e.stopPropagation();set(!p.classList.contains('open'));});
var fg=p.querySelector('.forget');if(fg)fg.addEventListener('click',function(e){e.preventDefault();e.stopPropagation();
fg.textContent='Deleting\u2026';window.__farNoTrack=1;
fetch('/api/forget.cgi',{method:'POST',cache:'no-store'}).then(function(r){return r.json()}).then(function(d){
p.querySelector('.pvt').textContent='Done: '+d.deleted+' log '+(d.deleted===1?'entry':'entries')+' for your IP address deleted, and this visit is no longer recorded.';fg.remove();
}).catch(function(){fg.textContent='Failed, email __CONTACT__';});});
document.addEventListener('click',function(e){if(!p.contains(e.target))set(false);});
document.addEventListener('keydown',function(e){if(e.key==='Escape')set(false);});
document.addEventListener('touchstart',function(e){if(!p.contains(e.target))set(false);},{passive:true});})();
</script>"""
PRIVACY_JS = PRIVACY_JS.replace("__CONTACT__", CONTACT)

FIT_JS = """<script>
(function(){var b=document.querySelector('.body'),f=document.querySelector('.fit');if(!b||!f)return;
function fit(){f.style.zoom='';var a=b.clientHeight,n=f.scrollHeight;if(a>0&&n>a+1)f.style.zoom=Math.max(.5,a/n).toFixed(3);}
fit();addEventListener('resize',fit);addEventListener('orientationchange',fit);addEventListener('load',fit);
if(window.ResizeObserver)new ResizeObserver(fit).observe(b);
if(document.fonts&&document.fonts.ready)document.fonts.ready.then(fit);})();
</script>"""

TRACK_JS = r"""<script>
(function(){
if(window.top!==window)return;
var C=__CARD__,pv=Math.random().toString(36).slice(2,10),vis=0,last=null,clicks=0,smax=0;
function send(o){if(window.__farNoTrack)return;o.pv=pv;o.card=C;o.path=location.pathname;var b=JSON.stringify(o);
 try{if(navigator.sendBeacon&&navigator.sendBeacon('/api/hit.cgi',new Blob([b],{type:'text/plain'})))return;}catch(e){}
 try{fetch('/api/hit.cgi',{method:'POST',body:b,keepalive:true,headers:{'Content-Type':'text/plain'}});}catch(e){}}
function mq(q){try{return matchMedia(q).matches?1:0}catch(e){return 0}}
function view(){
 var n=navigator,c=n.connection||{},s=screen,nv=(performance.getEntriesByType&&performance.getEntriesByType('navigation')[0])||{},tz='';
 try{tz=Intl.DateTimeFormat().resolvedOptions().timeZone}catch(e){}
 var o={t:'view',ref:document.referrer,q:location.search.slice(1),lang:(n.languages||[n.language]).slice(0,5),tz:tz,tzo:new Date().getTimezoneOffset(),
  scr:s.width+'x'+s.height,vp:innerWidth+'x'+innerHeight,dpr:window.devicePixelRatio,dark:mq('(prefers-color-scheme: dark)'),rm:mq('(prefers-reduced-motion: reduce)'),
  touch:n.maxTouchPoints,plat:n.platform,mem:n.deviceMemory,cores:n.hardwareConcurrency,net:c.effectiveType,dl:c.downlink,sd:c.saveData?1:0,
  sa:n.standalone?1:0,nav:nv.type,hist:history.length,load:Math.round(nv.loadEventEnd>0?nv.loadEventEnd:0)};
 var u=n.userAgentData;
 if(u){o.ch={m:u.mobile?1:0,p:u.platform,b:(u.brands||[]).map(function(b){return b.brand+' '+b.version}).slice(0,5)};
  if(u.getHighEntropyValues){u.getHighEntropyValues(['model','platformVersion','architecture']).then(function(h){o.ch.model=h.model;o.ch.pv=h.platformVersion;o.ch.arch=h.architecture;send(o);},function(){send(o);});return;}}
 send(o);}
if(document.readyState==='complete')view();else addEventListener('load',function(){setTimeout(view,0);});
function tick(){if(last!==null){vis+=Date.now()-last;last=null;}}
function show(){if(document.visibilityState==='visible'&&last===null)last=Date.now();}
var sent='';
function end(){var sig=Math.round(vis/1000)+':'+clicks+':'+smax;if((vis>0||clicks)&&sig!==sent){sent=sig;send({t:'end',dur:Math.round(vis/1000),smax:smax,n:clicks});}}
show();
document.addEventListener('visibilitychange',function(){if(document.visibilityState==='visible')show();else{tick();end();}});
addEventListener('pagehide',function(){tick();end();});
addEventListener('scroll',function(){var h=document.documentElement,p=Math.round(100*(scrollY+innerHeight)/Math.max(h.scrollHeight,1));if(p>smax)smax=Math.min(p,100);},{passive:true});
var NET={'calendly.com':'booking','wa.me':'whatsapp','api.whatsapp.com':'whatsapp','t.me':'telegram','linkedin.com':'linkedin','github.com':'github','facebook.com':'facebook','instagram.com':'instagram','x.com':'x','twitter.com':'x'};
function kind(a){var u;try{u=new URL(a.href,location.href);}catch(e){return['link',a.getAttribute('href')||''];}
 if(u.protocol==='tel:')return['call',u.pathname];if(u.protocol==='mailto:')return['email',u.pathname];
 if(/\.vcf$/i.test(u.pathname))return['save_contact',u.pathname];
 var H=u.hostname.replace(/^www\./,'');
 if(H===location.hostname.replace(/^www\./,''))return[/\.[a-z0-9]+$/i.test(u.pathname)&&!/\/$/.test(u.pathname)?'internal':'card_switch',u.pathname];
 return[NET[H]||'link',u.href];}
document.addEventListener('click',function(e){var a=e.target&&e.target.closest?e.target.closest('a[href]'):null;if(!a)return;clicks++;var k=kind(a);
 send({t:'click',k:k[0],href:k[1],txt:(a.textContent||'').replace(/\s+/g,' ').trim().slice(0,60)});},true);
window.addEventListener('far:nav',function(e){clicks++;send({t:'click',k:'swipe',href:e.detail.url,dir:e.detail.dir});});
document.addEventListener('copy',function(){send({t:'copy',sel:String(getSelection()).slice(0,80)});});
})();
</script>"""


def swipe_script(keys, key, sib_prefix):
    """Swipe left = next card, swipe right = previous, cycling around in the bottom-link order."""
    prev = nxt = None
    if key in keys and len(keys) > 1:
        i, n = keys.index(key), len(keys)
        prev = sib_prefix + keys[(i - 1) % n] + "/"
        nxt = sib_prefix + keys[(i + 1) % n] + "/"
    return SWIPE_JS.replace("__PREV__", json.dumps(prev)).replace("__NEXT__", json.dumps(nxt))


def icon(name):
    return ('<svg class="i" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
            'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">%s</svg>' % ICONS[name])


def esc(s):
    return html.escape(str(s), quote=True)


# ---------------------------------------------------------------- vCard ----
def vesc(s):
    return str(s).replace("\\", "\\\\").replace("\n", "\\n").replace(",", "\\,").replace(";", "\\;")


def fold(line):
    """Fold at 75 octets (continuation lines start with one space)."""
    if len(line.encode("utf-8")) <= 75:
        return line
    out, cur, limit = [], b"", 75
    for ch in line:
        b = ch.encode("utf-8")
        if len(cur) + len(b) > limit:
            out.append(cur.decode("utf-8"))
            cur, limit = b, 74
        else:
            cur += b
    out.append(cur.decode("utf-8"))
    return "\r\n ".join(out)


def make_vcard(person, p, photo_b64, key='', card_url=None):
    lines = ["BEGIN:VCARD", "VERSION:3.0",
             "N:%s;%s;;;" % (vesc(person["family"]), vesc(person["given"])),
             "FN:%s" % vesc(person["name"])]
    if p.get("org"):
        lines.append("ORG:%s" % vesc(p["org"]))
    if p.get("title"):
        lines.append("TITLE:%s" % vesc(p["title"]))
    if p.get("phone"):
        lines.append("TEL;TYPE=CELL:%s" % p["phone"])
    if p.get("email"):
        lines.append("EMAIL;TYPE=INTERNET,WORK:%s" % p["email"])
    if p.get("url"):
        lines.append("URL:%s" % p["url"])
    if card_url:
        lines.append("item1.URL:%s" % card_url)
        lines.append("item1.X-ABLabel:Online card")
    lines.append("PHOTO;ENCODING=b;TYPE=JPEG:%s" % photo_b64)
    lines.append("REV:%s" % datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
    lines.append("END:VCARD")
    return "\r\n".join(fold(l) for l in lines) + "\r\n"


# ----------------------------------------------------------------- page ----
LOC_HTML = r"""<p class="loc" id="loc" hidden></p>
<script>
(function(){if(window.top!==window)return;
fetch('/loc.json',{cache:'no-store'}).then(function(r){return r.ok?r.json():null}).then(function(d){
 if(!d||!(d.city||d.country)||!d.ts||Date.now()/1000-d.ts>2*86400)return;
 var C={'United Kingdom':'UK','United States':'US','Lithuania':'LT','Latvia':'LV','Estonia':'EE','Poland':'PL','Germany':'DE','France':'FR','Netherlands':'NL','Belgium':'BE','Ireland':'IE','Spain':'ES','Portugal':'PT','Italy':'IT','Switzerland':'CH','Austria':'AT','Czechia':'CZ','Hungary':'HU','Romania':'RO','Bulgaria':'BG','Greece':'GR','Türkiye':'TR','Turkey':'TR','Denmark':'DK','Sweden':'SE','Norway':'NO','Finland':'FI','Iceland':'IS','Ukraine':'UA','Russia':'RU','Canada':'CA','Mexico':'MX','Brazil':'BR','Argentina':'AR','Chile':'CL','Colombia':'CO','Peru':'PE','Egypt':'EG','Morocco':'MA','Nigeria':'NG','Kenya':'KE','South Africa':'ZA','United Arab Emirates':'UAE','Qatar':'QA','Saudi Arabia':'SA','Israel':'IL','India':'IN','Pakistan':'PK','Thailand':'TH','Singapore':'SG','Malaysia':'MY','Indonesia':'ID','Hong Kong':'HK','China':'CN','South Korea':'KR','Japan':'JP','Taiwan':'TW','Philippines':'PH','Australia':'AU','New Zealand':'NZ'};
 var cc=d.country?(C[d.country]||d.country):'',t=d.city?d.city+(cc?', '+cc:''):cc;
 var el=document.getElementById('loc');
 var h=Math.floor((Date.now()/1000-d.ts)/3600),ago=h<1?'under an hour ago':h===1?'1 hour ago':h+' hours ago';
 el.appendChild(document.createTextNode('\ud83d\udccd Last seen - '+t));var sm=document.createElement('small');sm.textContent='('+ago+')';el.appendChild(sm);el.hidden=false;}).catch(function(){});})();
</script>"""

def make_page(person, p, key, siblings, prefix, sib_prefix, vcf_name, photo_uri, canonical, og_image, logo_name=None, privacy=None):
    accent = p.get("accent", "#2563eb")
    if not re.fullmatch(r"#[0-9a-fA-F]{6}", accent):
        raise SystemExit("accent must look like #2563eb, got %r" % accent)
    dacc = p.get("accent_dark") or dark_accent(accent)
    don = (p.get("on_accent") if dacc == accent else None) or on_accent(dacc)
    top = '<div class="top"></div>'
    if logo_name:
        top = ('<div class="top"><span class="chip%s"><img src="%s%s" alt="%s"></span></div>'
               % (" bare" if p.get("logo_bare") else "", esc(prefix), esc(logo_name), esc(p.get("label", key))))
    btns = ['<a class="btn primary" href="%s%s">%s Save contact</a>' % (esc(prefix), esc(vcf_name), icon("user-plus"))]
    bk = p["booking"] if "booking" in p else person.get("booking")
    if bk:
        bk = {"url": bk} if isinstance(bk, str) else bk
        btns.append('<a class="btn pill" href="%s" rel="noopener">%s %s</a>' % (esc(bk["url"]), icon("calendar"), esc(bk.get("label", "Book a meeting"))))
    if p.get("phone"):
        tel = re.sub(r"[^\d+]", "", p["phone"])
        btns.append('<a class="btn" href="tel:%s">%s %s</a>' % (esc(tel), icon("phone"), esc(p["phone"])))
    if p.get("email"):
        btns.append('<a class="btn" href="mailto:%s">%s %s</a>' % (esc(p["email"]), icon("mail"), esc(p["email"])))
    if p.get("url"):
        label = re.sub(r"^https?://(www\.)?", "", p["url"]).rstrip("/")
        btns.append('<a class="btn" href="%s">%s %s</a>' % (esc(p["url"]), icon("globe"), esc(label)))
    for x in p.get("company_links", []):
        btns.append('<a class="btn" href="%s" rel="noopener">%s %s</a>' % (esc(x["url"]), brand_icon(x["type"]), esc(company_label(p, key, x))))
    for link in p.get("links", []):
        btns.append('<a class="btn" href="%s">%s %s</a>' % (esc(link["url"]), icon("link"), esc(link["label"])))
    socials = ""
    if p.get("socials"):
        items = "".join('<a href="%s" aria-label="%s" rel="noopener"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="%s"/></svg></a>'
                        % (esc(x["url"]), esc(SOCIAL_LABELS[x["type"]]), SOCIAL_PATHS[x["type"]]) for x in p["socials"])
        socials = '<div class="socials">%s</div>' % items
    other = ""
    visible = {k: v for k, v in siblings.items() if not v.get("hidden")}
    if len(visible) > 1:
        items = "".join('<span class="cur" aria-current="page">%s</span>' % esc(v.get("label", k)) if k == key
                        else '<a href="%s%s/">%s</a>' % (esc(sib_prefix), esc(k), esc(v.get("label", k)))
                        for k, v in visible.items())
        other = '<div class="other">%s</div>' % items
    swipe = swipe_script(list(visible), key, sib_prefix)
    swipe += FIT_JS + PRIVACY_JS
    swipe += TRACK_JS.replace("__CARD__", json.dumps(urlparse(canonical).path.strip("/") or "home"))
    desc = " · ".join(x for x in [p.get("title"), p.get("org")] if x) or person["name"]
    return """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow">
<meta name="theme-color" content="%(accent)s" media="(prefers-color-scheme: light)">
<meta name="theme-color" content="#0f1115" media="(prefers-color-scheme: dark)">
<title>%(name)s – %(label)s</title>
<meta property="og:title" content="%(name)s">
<meta property="og:description" content="%(desc)s">
<meta property="og:image" content="%(og)s">
<meta property="og:url" content="%(canon)s">
<link rel="canonical" href="%(canon)s">
<style>%(css)s</style>
%(swipe_head)s
</head>
<body>
<main class="card">
%(top)s
<div class="who">
<img src="%(photo)s" alt="%(name)s" width="112" height="112">
<h1>%(name)s</h1>
%(title)s%(org)s%(note)s
%(loc)s</div>
<div class="body"><div class="fit">
%(socials)s
<div class="actions">
%(btns)s
</div>
</div></div>
%(other)s
%(privacy)s
</main>
%(swipe)s
</body>
</html>
""" % {
        "accent": accent, "name": esc(person["name"]), "label": esc(p.get("label", key)), "desc": esc(desc),
        "og": esc(og_image), "canon": esc(canonical), "css": (CSS + PRIVACY_CSS).replace("DARKACC", dacc).replace("DARKON", don).replace("ONACCENT", p.get("on_accent") or on_accent(accent)).replace("LINKLT", accent if lum(accent) < 150 else "#5b6470").replace("RULELT", accent if lum(accent) < 150 else "#14171c").replace("BANNERCOL", p.get("banner") or accent).replace("ACCENT", accent), "photo": photo_uri,
        "top": top,
        "title": '<p class="title">%s</p>\n' % esc(p["title"]) if p.get("title") else "",
        "org": '<p class="org">%s</p>\n' % esc(p["org"]) if p.get("org") else "",
        "note": '<p class="note">%s</p>\n' % esc(p["note"]) if p.get("note") else "",
        "btns": "\n".join(btns), "socials": socials, "other": other, "swipe": swipe, "loc": LOC_HTML if not p.get("no_location") else "", "swipe_head": SWIPE_HEAD, "privacy": privacy or PRIVACY_HTML,
    }
