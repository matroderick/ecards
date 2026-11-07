#!/usr/bin/env python3
"""Render the landing page template with the configured names and the visit-tracking script.

   FAR_BASE_DOMAIN=cards.example.com FAR_SITE_NAME=ecards FAR_CONTACT=hi@example.com \\
       python3 service/build_landing.py [out.html]      (default: dist/landing/index.html)
"""
import sys
from pathlib import Path
here = Path(__file__).resolve().parent
sys.path.insert(0, str(here.parent))
import build, farlib


def render(template: str) -> str:
    s = template
    for key, val in (("{{BASE}}", farlib.BASE), ("{{SITE}}", farlib.SITE), ("{{CONTACT}}", farlib.CONTACT)):
        s = s.replace(key, val)
    blk = "<!--track-->" + build.TRACK_JS.replace("__CARD__", '"home"') + "<!--/track-->"
    return s.replace("</body>", blk + "\n</body>", 1)


if __name__ == "__main__":
    out = Path(sys.argv[1] if len(sys.argv) > 1 else here.parent / "dist" / "landing" / "index.html")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render((here / "landing" / "index.tmpl.html").read_text()))
    print("wrote", out)
