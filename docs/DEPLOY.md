# Deploying ecards

Examples use `cards.example.com`; replace it everywhere. Paths follow the defaults in `service/farlib.py`: code in `/opt/far`, data in `/var/lib/far-app`, user sites in `/var/www/far-users/<handle>`, visitor logs in `/var/lib/far-log/<handle>`.

## 1. DNS
Point two names at the server (A, and AAAA if it has IPv6):

    cards.example.com      A  <server IPv4>
    *.cards.example.com    A  <server IPv4>

Most DNS panels append the zone name, so enter only `cards` and `*.cards` in the Host field. Add MX/TXT records only if you will use `handle@` forwarding (see 7).

## 2. Wildcard TLS certificate (DNS-01)
A wildcard needs DNS validation. With acme.sh and any supported DNS provider:

    acme.sh --issue --dns dns_<provider> -d cards.example.com -d '*.cards.example.com'
    sudo mkdir -p /etc/ssl/cards.example.com
    acme.sh --install-cert -d cards.example.com --key-file /etc/ssl/cards.example.com/privkey.pem \
        --fullchain-file /etc/ssl/cards.example.com/fullchain.pem --reloadcmd "systemctl reload apache2"

## 3. Packages and files

    sudo apt install -y apache2 python3 python3-pil python3-qrcode fonts-inter python3-maxminddb
    sudo a2enmod ssl headers rewrite cgid proxy proxy_http vhost_alias
    sudo mkdir -p /opt/far /var/lib/far-app /var/www/far-users /var/www/cards.example.com /var/lib/far-log /usr/local/lib/far-cgi
    sudo cp -r build.py service server /opt/far/
    sudo install -m 755 server/hit.cgi server/log.cgi server/loc.cgi server/forget.cgi service/farlib.py /usr/local/lib/far-cgi/
    sudo chown -R www-data:www-data /var/lib/far-app /var/www/far-users /var/lib/far-log
    openssl rand -hex 32 | sudo tee /etc/far-secret >/dev/null && sudo chown root:www-data /etc/far-secret && sudo chmod 640 /etc/far-secret
    sudo cp deploy/ecards.env.example /etc/far-app.env && sudo chown root:www-data /etc/far-app.env && sudo chmod 640 /etc/far-app.env
    sudoedit /etc/far-app.env

## 4. Landing page

    FAR_BASE_DOMAIN=cards.example.com FAR_SITE_NAME=ecards FAR_CONTACT=contact@example.com \
        python3 service/build_landing.py /var/www/cards.example.com/index.html

## 5. Apache and the service

    sudo cp deploy/apache.conf /etc/apache2/sites-available/cards.example.com.conf   # edit the domain and the SetEnv lines
    sudo a2ensite cards.example.com
    sudo cp deploy/ecards.service /etc/systemd/system/ && sudo systemctl daemon-reload && sudo systemctl enable --now ecards
    sudo apache2ctl configtest && sudo systemctl reload apache2

The CGIs read `FAR_BASE_DOMAIN` from Apache's `SetEnv` (see `deploy/apache.conf`); keep it equal to the value in `/etc/far-app.env`.

## 6. First sign-in and demo

Open `https://app.cards.example.com`, sign in with an address listed in `FAR_ADMINS`, and approve invite requests under `/admin`.

Optional demo account (read-only, linked from the landing page):

    cd /opt/far/service && sudo -u www-data python3 import_cards.py demo_cards.json demo demo@demo.invalid --replace
    sudo -u www-data python3 seed_demo_log.py      # sample visitor log; re-run daily from cron to keep it fresh

## 7. Optional: `handle@` email forwarding (ImprovMX)
Add the domain to ImprovMX, set `FAR_IMPROVMX_KEY`, and add at `cards`: MX 10 `mx1.improvmx.com`, MX 20 `mx2.improvmx.com`, TXT `v=spf1 include:spf.improvmx.com ~all`. ImprovMX's free plan has API and alias limits.

## 8. Optional: visitor geolocation
    sudo mkdir -p /usr/share/GeoIP && cd /usr/share/GeoIP
    for t in city asn; do sudo curl -fsSL https://download.db-ip.com/free/dbip-$t-lite-$(date +%Y-%m).mmdb.gz | gunzip | sudo tee dbip-$t-lite.mmdb >/dev/null; done
DB-IP lite data is CC-BY: keep the attribution on the log page.

## Reserved handles
Fixed names live in `RESERVED` in `service/farlib.py`. Add more, one per line, to `/var/lib/far-app/reserved.txt`.

## Operations
- Back up nightly: `sqlite3 /var/lib/far-app/far.db ".backup /backup/far.db"` plus `/var/lib/far-app/assets`.
- Update: copy new files to `/opt/far` and the CGIs to `/usr/local/lib/far-cgi`, then `systemctl restart ecards`. Re-render users after template changes.
- Logs: `journalctl -u ecards`.
