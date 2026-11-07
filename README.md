# ecards

A small, self-hosted service for digital business cards. People get `handle.cards.example.com` with one or more cards (personas), a QR code, a one-tap "save contact" vCard, optional `handle@cards.example.com` email forwarding, and a private visitor log.

- **Multi-tenant**: one server, many users, tenants chosen by the `Host` header.
- **Static cards**: each user's cards are plain HTML files, served by Apache; only sign-in and the dashboard run Python.
- **Invite-only**: people request a handle, the admin approves by email link. A read-only demo account is built in.
- **No framework, no build step**: Python 3 standard library + Pillow, SQLite, Apache. About 2,500 lines.

## Layout

| Path | What it is |
|---|---|
| `service/app.py` | WSGI app: sign-in (magic link), dashboard, persona editor, invite requests, admin, reports |
| `service/farlib.py` | Shared config, tenant lookup, tokens, SQLite schema (also used by the CGIs) |
| `build.py` | Card page, vCard and QR templates |
| `service/render.py` | Writes one user's static site |
| `service/mailalias.py` | ImprovMX API client for `handle@` forwarding (optional) |
| `server/*.cgi` | Visit logging, "forget me", location and log API |
| `service/landing/` | Landing page template, rendered by `service/build_landing.py` |
| `deploy/` | Apache vhosts, systemd unit, example environment file |
| `tests/` | `python3 -m unittest discover -s tests` |

## Try it locally

    pip install pillow
    export FAR_BASE_DOMAIN=localhost FAR_SCHEME=http FAR_PUBLIC_PORT=:8771 FAR_DEV_PORT=8771 \
           FAR_DB=/tmp/ecards/far.db FAR_USERS_ROOT=/tmp/ecards/users FAR_ASSETS=/tmp/ecards/assets \
           FAR_LOG_DIR=/tmp/ecards/log FAR_SECRET=dev FAR_OUTBOX=/tmp/ecards/outbox.txt FAR_ADMINS=you@example.com
    mkdir -p /tmp/ecards/{users,assets,log}
    python3 service/devserver.py        # app at http://app.localhost:8771 ; sign-in emails are appended to the outbox file

## Configuration

All settings are environment variables (`deploy/ecards.env.example`). The ones you must set: `FAR_BASE_DOMAIN`, `FAR_ADMINS`, and SMTP details. `FAR_SITE_NAME` and `FAR_CONTACT` control the name and address shown in pages, emails, Terms and Privacy. The `FAR_` prefix and the `/opt/far`, `/var/lib/far-app` paths are historical names; every path can be overridden by environment.

## Deploy

See [docs/DEPLOY.md](docs/DEPLOY.md): DNS, wildcard certificate, Apache, systemd, optional ImprovMX forwarding and geolocation.

## Privacy

Cards record visitor IP, approximate location, device and clicked links for the card owner (180 days). Each card has a "forget me" control. Adjust the wording in `service/app.py` (`TERMS`, `PRIVACY`) and `build.py` (`PRIVACY_TEXT`) to match your own legal position before running this for other people.

## Licence

MIT, see [LICENSE](LICENSE). Not legal advice; the bundled Terms and Privacy text is a plain-language starting point for a beta service.
