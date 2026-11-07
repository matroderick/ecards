"""Receive-only <handle>@<base domain> forwarding via the ImprovMX API (v4). Sending as the address is NOT configured."""
import base64, json, os, urllib.request, urllib.error
from farlib import BASE

API = os.environ.get("FAR_IMPROVMX_API", "https://api.improvmx.com/v4")
KEY = os.environ.get("FAR_IMPROVMX_KEY", "")
FAKE = os.environ.get("FAR_IMPROVMX_FAKE", "")      # dev: path of a JSON file that simulates ImprovMX


class MailError(Exception):
    pass


class Exists(MailError):
    pass


def _fake(method, handle, forward, aid):
    st = json.load(open(FAKE)) if os.path.exists(FAKE) else {}
    if method == "POST":
        if handle in st:
            raise Exists(handle)
        st[handle] = {"forward": forward, "id": str(len(st) + 100)}
    elif method == "PUT":
        if handle not in st:
            raise MailError("no such alias")
        st[handle]["forward"] = forward
    elif method == "DELETE":
        st.pop(handle, None)
    json.dump(st, open(FAKE, "w"))
    return st.get(handle, {}).get("id")


def _call(method, path, body=None):
    if not KEY:
        raise MailError("ImprovMX key not configured")
    req = urllib.request.Request(API + path, method=method, data=json.dumps(body).encode() if body is not None else None)
    req.add_header("Authorization", "Basic " + base64.b64encode(("api:" + KEY).encode()).decode())
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            raw = r.read()
            return r.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as e:
        try:
            data = json.loads(e.read() or b"{}")
        except ValueError:
            data = {}
        return e.code, data
    except Exception as e:
        raise MailError("network error: %s" % e)


def create(handle, forward):
    """Returns the alias id (str). Raises Exists if the address is already configured."""
    if FAKE:
        return _fake("POST", handle, forward, None)
    st, d = _call("POST", "/domains/%s/aliases" % BASE, {"alias": handle, "forward": forward})
    if st in (200, 201):
        a = d.get("alias", d)
        return str(a.get("id", handle))
    msg = json.dumps(d)[:300].lower()
    if st in (400, 409, 422) and ("exist" in msg or "already" in msg or "taken" in msg):
        raise Exists(handle)
    raise MailError("ImprovMX %s: %s" % (st, msg))


def update(handle, aid, forward):
    if FAKE:
        return _fake("PUT", handle, forward, aid)
    st, d = _call("PUT", "/domains/%s/aliases/%s" % (BASE, aid or handle), {"forward": forward})
    if st not in (200, 201):
        raise MailError("ImprovMX %s: %s" % (st, json.dumps(d)[:300]))


def delete(handle, aid):
    if FAKE:
        return _fake("DELETE", handle, None, aid)
    st, d = _call("DELETE", "/domains/%s/aliases/%s" % (BASE, aid or handle))
    if st not in (200, 204, 404):
        raise MailError("ImprovMX %s: %s" % (st, json.dumps(d)[:300]))


def list_aliases():
    """All alias names (lowercase local parts) configured for the domain; skips the catch-all '*'."""
    if FAKE:
        st = json.load(open(FAKE)) if os.path.exists(FAKE) else {}
        return sorted(st)
    names, page = set(), 1
    while page <= 200:
        st, d = _call("GET", "/domains/%s/aliases?page=%d&limit=100" % (BASE, page))
        if st != 200:
            raise MailError("ImprovMX %s: %s" % (st, json.dumps(d)[:300]))
        items = d.get("aliases") or []
        for it in items:
            a = (it.get("alias") or "").strip().lower()
            if a and a != "*":
                names.add(a)
        if len(items) < 100:
            break
        page += 1
    return sorted(names)
