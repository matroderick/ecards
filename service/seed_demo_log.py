#!/usr/bin/env python3
"""(Re)generate sample visitor-log data for the demo account, relative to now. Run daily from cron.
   python3 seed_demo_log.py"""
import hashlib, json, os, random, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import farlib

H = "demo"
random.seed(int(time.time() // 86400))
UA = {
 "iphone": "Mozilla/5.0 (iPhone; CPU iPhone OS 18_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.1 Mobile/15E148 Safari/604.1",
 "pixel": "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Mobile Safari/537.36",
 "mac": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
 "win": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36 Edg/130.0.0.0",
 "linkedin": "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 LinkedInApp/9.30.1",
 "bot": "Mozilla/5.0 (compatible; Bingbot/2.0; +http://www.bing.com/bingbot.htm)",
}
PEOPLE = [  # ip, ua, geo, lang, tz, scr, vp, touch
 ("203.0.113.21", "iphone", dict(cc="GB", city="London", region="England", org="Example Mobile Ltd", asn=64501), ["en-GB"], "Europe/London", "390x844", "390x664", 5),
 ("198.51.100.77", "mac", dict(cc="GB", city="Manchester", region="England", org="Sample Broadband plc", asn=64502), ["en-GB", "en"], "Europe/London", "1512x982", "1440x800", 0),
 ("192.0.2.140", "linkedin", dict(cc="DE", city="Berlin", region="Berlin", org="Beispiel Telekom GmbH", asn=64503), ["de-DE"], "Europe/Berlin", "393x852", "393x700", 5),
 ("203.0.113.88", "pixel", dict(cc="US", city="New York", region="New York", org="Example Wireless Inc", asn=64504), ["en-US"], "America/New_York", "412x915", "412x780", 5),
 ("198.51.100.19", "win", dict(cc="SG", city="Singapore", region="Singapore", org="Sample Fibre Pte", asn=64505), ["en-SG", "en"], "Asia/Singapore", "1920x1080", "1904x950", 0),
 ("192.0.2.33", "iphone", dict(cc="FR", city="Paris", region="Île-de-France", org="Exemple Mobile SA", asn=64506), ["fr-FR"], "Europe/Paris", "390x844", "390x664", 5),
 ("203.0.113.150", "mac", dict(cc="GB", city="Bristol", region="England", org="Sample Broadband plc", asn=64502), ["en-GB"], "Europe/London", "1440x900", "1440x780", 0),
 ("198.51.100.201", "iphone", dict(cc="NL", city="Amsterdam", region="North Holland", org="Voorbeeld Mobiel BV", asn=64507), ["nl-NL"], "Europe/Amsterdam", "430x932", "430x760", 5),
 ("192.0.2.99", "bot", dict(cc="US", city="Boydton", region="Virginia", org="Example Cloud", asn=64508), [], "", "", "", 0),
 ("203.0.113.5", "pixel", dict(cc="IE", city="Dublin", region="Leinster", org="Example Mobile Ltd", asn=64501), ["en-IE"], "Europe/Dublin", "412x915", "412x780", 5),
]
CARDS = ["work", "work", "work", "photo", "me"]
CLICKS = {"work": [("save_contact", "/work/demo-work.vcf", "Save contact"), ("booking", "https://example.com/book", "Book a meeting"), ("call", "+442079460123", "+44 20 7946 0123"),
                   ("email", "sam@example.com", "sam@example.com"), ("linkedin", "https://www.linkedin.com/", ""), ("link", "https://example.com/portfolio", "Portfolio")],
          "photo": [("instagram", "https://www.instagram.com/", ""), ("link", "https://example.com/prints", "Prints shop"), ("email", "sam.photo@example.com", "sam.photo@example.com")],
          "me": [("whatsapp", "https://wa.me/442079460456", ""), ("call", "+442079460456", "+44 20 7946 0456")]}
REFS = ["", "", "", "https://www.linkedin.com/", "https://t.co/", "https://www.instagram.com/"]

out = Path(farlib.LOG_ROOT) / H
out.mkdir(parents=True, exist_ok=True)
for f in out.glob("*.jsonl"):
    f.unlink()
now = int(time.time())
events = []
for n in range(70):
    ip, ua, geo, lang, tz, scr, vp, touch = random.choice(PEOPLE)
    day = random.choices(range(14), weights=[10, 9, 8, 7, 6, 6, 5, 5, 4, 4, 3, 3, 2, 2])[0]
    sec = int(random.gauss(14.5, 3.5) * 3600) % 86400
    t0 = (now // 86400 - day) * 86400 + sec
    if t0 > now - 60:
        t0 = now - random.randint(120, 7200)
    pv = "%08x" % random.getrandbits(32)
    card = random.choice(CARDS)
    base = {"ip": ip, "ua": UA[ua], "al": ",".join(lang) or "", "vid": hashlib.sha256((H + ip + UA[ua]).encode()).hexdigest()[:10], "geo": geo, "pv": pv, "path": "/" if card == "work" and random.random() < .6 else "/%s/" % card}
    seq = [dict(base, ts=t0, t="view", card=card, ref=random.choice(REFS), lang=lang, tz=tz, scr=scr, vp=vp, dpr=3 if touch else 2, touch=touch, dark=random.randint(0, 1), load=random.randint(80, 600), nav="navigate", hist=random.randint(1, 4))]
    if ua == "bot":
        events += seq; continue
    t = t0
    for _ in range(random.choice([0, 0, 1, 1, 2, 3])):
        t += random.randint(4, 40)
        if random.random() < .35 and card != "me":
            nxt = random.choice([c for c in ("work", "photo", "me") if c != card])
            seq.append(dict(base, ts=t, t="click", card=card, k="swipe" if touch else "card_switch", href="/%s/" % nxt, dir="l")); card = nxt
            seq.append(dict(base, ts=t + 1, t="view", card=card, pv=pv, ref="", lang=lang, tz=tz, scr=scr, vp=vp, touch=touch))
        k, href, txt = random.choice(CLICKS[card])
        seq.append(dict(base, ts=t + random.randint(1, 5), t="click", card=card, k=k, href=href, txt=txt))
    dur = random.randint(6, 120)
    seq.append(dict(base, ts=t + dur, t="end", card=card, dur=dur, smax=random.choice([40, 70, 100, 100]), n=sum(1 for e in seq if e["t"] == "click")))
    events += seq
events.sort(key=lambda e: e["ts"])
by_day = {}
for e in events:
    by_day.setdefault(time.strftime("%Y-%m-%d", time.gmtime(e["ts"])), []).append(e)
for d, evs in by_day.items():
    (out / (d + ".jsonl")).write_text("".join(json.dumps(e, separators=(",", ":"), ensure_ascii=False) + "\n" for e in evs))
print("wrote %d sample events over %d days to %s" % (len(events), len(by_day), out))
