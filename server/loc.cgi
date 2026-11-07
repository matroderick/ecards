#!/usr/bin/env python3
# POST token=...&lat=...&lon=...&country=...   (or clear=1 to hide). Only a major city (<=80 km) or the country is ever stored.  ->  /var/www/far-users/<handle>/loc.jsonmat.json
import os, sys, json, time, hmac, tempfile
from urllib.parse import parse_qs
sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import farlib

CITIES = [
("London","United Kingdom",51.507,-0.128),("Birmingham","United Kingdom",52.486,-1.890),("Manchester","United Kingdom",53.481,-2.243),
("Leeds","United Kingdom",53.800,-1.549),("Liverpool","United Kingdom",53.408,-2.992),("Bristol","United Kingdom",51.454,-2.588),
("Sheffield","United Kingdom",53.383,-1.466),("Newcastle","United Kingdom",54.978,-1.618),("Nottingham","United Kingdom",52.954,-1.150),
("Southampton","United Kingdom",50.904,-1.404),("Cardiff","United Kingdom",51.481,-3.179),("Edinburgh","United Kingdom",55.953,-3.189),
("Glasgow","United Kingdom",55.864,-4.252),("Belfast","United Kingdom",54.597,-5.930),("Oxford","United Kingdom",51.752,-1.258),
("Cambridge","United Kingdom",52.205,0.119),("Brighton","United Kingdom",50.822,-0.137),("Aberdeen","United Kingdom",57.150,-2.094),
("Vilnius","Lithuania",54.687,25.280),("Kaunas","Lithuania",54.899,23.912),("Klaipėda","Lithuania",55.703,21.144),
("Šiauliai","Lithuania",55.934,23.314),("Panevėžys","Lithuania",55.735,24.357),("Riga","Latvia",56.949,24.105),("Tallinn","Estonia",59.437,24.754),
("Warsaw","Poland",52.230,21.012),("Kraków","Poland",50.065,19.945),("Gdańsk","Poland",54.352,18.646),("Berlin","Germany",52.520,13.405),
("Hamburg","Germany",53.551,9.994),("Munich","Germany",48.135,11.582),("Frankfurt","Germany",50.111,8.682),("Cologne","Germany",50.938,6.960),
("Paris","France",48.857,2.352),("Lyon","France",45.764,4.836),("Marseille","France",43.296,5.370),("Nice","France",43.710,7.262),
("Amsterdam","Netherlands",52.368,4.904),("Rotterdam","Netherlands",51.924,4.478),("Brussels","Belgium",50.850,4.352),("Dublin","Ireland",53.350,-6.260),
("Madrid","Spain",40.417,-3.704),("Barcelona","Spain",41.385,2.173),("Valencia","Spain",39.470,-0.376),("Seville","Spain",37.389,-5.984),
("Lisbon","Portugal",38.722,-9.139),("Porto","Portugal",41.157,-8.629),("Rome","Italy",41.903,12.496),("Milan","Italy",45.464,9.190),
("Naples","Italy",40.852,14.268),("Turin","Italy",45.070,7.687),("Zurich","Switzerland",47.377,8.541),("Geneva","Switzerland",46.204,6.143),
("Vienna","Austria",48.208,16.374),("Prague","Czechia",50.075,14.438),("Budapest","Hungary",47.498,19.040),("Bucharest","Romania",44.427,26.103),
("Sofia","Bulgaria",42.698,23.322),("Athens","Greece",37.984,23.728),("Istanbul","Türkiye",41.008,28.978),("Copenhagen","Denmark",55.676,12.568),
("Stockholm","Sweden",59.329,18.069),("Gothenburg","Sweden",57.709,11.975),("Oslo","Norway",59.914,10.752),("Helsinki","Finland",60.170,24.938),
("Reykjavík","Iceland",64.147,-21.943),("Kyiv","Ukraine",50.450,30.523),("Moscow","Russia",55.756,37.617),
("New York","United States",40.713,-74.006),("Boston","United States",42.360,-71.059),("Washington","United States",38.907,-77.037),
("Chicago","United States",41.878,-87.630),("Atlanta","United States",33.749,-84.388),("Miami","United States",25.762,-80.192),
("Houston","United States",29.760,-95.370),("Dallas","United States",32.777,-96.797),("Denver","United States",39.739,-104.990),
("Seattle","United States",47.606,-122.332),("San Francisco","United States",37.775,-122.419),("Los Angeles","United States",34.052,-118.244),
("San Diego","United States",32.716,-117.161),("Las Vegas","United States",36.170,-115.140),("Toronto","Canada",43.653,-79.383),
("Montréal","Canada",45.502,-73.567),("Vancouver","Canada",49.283,-123.121),("Mexico City","Mexico",19.433,-99.133),
("São Paulo","Brazil",-23.551,-46.633),("Rio de Janeiro","Brazil",-22.907,-43.173),("Buenos Aires","Argentina",-34.604,-58.382),
("Santiago","Chile",-33.449,-70.669),("Bogotá","Colombia",4.711,-74.072),("Lima","Peru",-12.046,-77.043),
("Cairo","Egypt",30.044,31.236),("Casablanca","Morocco",33.573,-7.590),("Lagos","Nigeria",6.524,3.379),("Nairobi","Kenya",-1.286,36.817),
("Johannesburg","South Africa",-26.204,28.047),("Cape Town","South Africa",-33.925,18.424),("Dubai","United Arab Emirates",25.205,55.271),
("Abu Dhabi","United Arab Emirates",24.454,54.377),("Doha","Qatar",25.286,51.533),("Riyadh","Saudi Arabia",24.713,46.675),("Tel Aviv","Israel",32.085,34.782),
("Mumbai","India",19.076,72.878),("Delhi","India",28.614,77.209),("Bengaluru","India",12.972,77.594),("Karachi","Pakistan",24.861,67.010),
("Bangkok","Thailand",13.756,100.502),("Singapore","Singapore",1.352,103.820),("Kuala Lumpur","Malaysia",3.139,101.687),("Jakarta","Indonesia",-6.209,106.846),
("Hong Kong","Hong Kong",22.320,114.169),("Shenzhen","China",22.543,114.058),("Shanghai","China",31.230,121.474),("Beijing","China",39.904,116.407),
("Seoul","South Korea",37.567,126.978),("Tokyo","Japan",35.690,139.692),("Osaka","Japan",34.694,135.502),("Taipei","Taiwan",25.033,121.565),
("Manila","Philippines",14.600,120.984),("Sydney","Australia",-33.869,151.209),("Melbourne","Australia",-37.814,144.963),
("Brisbane","Australia",-27.470,153.026),("Perth","Australia",-31.950,115.860),("Auckland","New Zealand",-36.849,174.763),
]
MAX_KM = 80
def snap(lat, lon):
    import math
    best = None
    for name, ctry, la, lo in CITIES:
        p = math.pi / 180
        a = math.sin((la-lat)*p/2)**2 + math.cos(lat*p)*math.cos(la*p)*math.sin((lo-lon)*p/2)**2
        d = 12742 * math.asin(math.sqrt(a))
        if best is None or d < best[0]: best = (d, name, ctry)
    return (best[1], best[2]) if best and best[0] <= MAX_KM else (None, None)

def reply(code, msg):
    print("Status: %s\nContent-Type: text/plain\nCache-Control: no-store\n\n%s" % (code, msg)); sys.exit()

if os.environ.get("REQUEST_METHOD") != "POST":
    reply("405 Method Not Allowed", "POST only")
n = min(int(os.environ.get("CONTENT_LENGTH") or 0), 2048)
f = parse_qs(sys.stdin.read(n))
g = lambda k: (f.get(k, [""])[0]).strip()[:80]
tenant = farlib.tenant_row(os.environ.get("HTTP_HOST", ""))
if not tenant:
    reply("404 Not Found", "no such card")
if not farlib.check_token(g("token"), tenant["handle"], "loc", tenant["loc_ver"]):
    time.sleep(1)
    reply("403 Forbidden", "bad token")
OUT = os.path.join(farlib.USERS_ROOT, tenant["handle"], "loc.json")
os.makedirs(os.path.dirname(OUT), exist_ok=True)
data = {}
if not g("clear"):
    city = ctry = None
    try:
        city, ctry = snap(float(g("lat")), float(g("lon")))
    except ValueError:
        # older Shortcuts post only a city name: keep it only if it IS a major city
        for name, c, _, _ in CITIES:
            if name.lower() == g("city").lower():
                city, ctry = name, c
    ctry = ctry or g("country")
    if city or ctry:
        data = {"city": city or "", "country": ctry, "ts": int(time.time())}
fd, tmp = tempfile.mkstemp(dir=os.path.dirname(OUT)); os.write(fd, json.dumps(data).encode()); os.close(fd)
os.chmod(tmp, 0o644); os.replace(tmp, OUT)
reply("200 OK", "ok")
