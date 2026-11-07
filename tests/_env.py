"""Import first: points the service at a throw-away data directory and a fixed test domain."""
import os, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TMP = tempfile.mkdtemp(prefix="ecards-test-")
os.environ.update({
    "FAR_BASE_DOMAIN": "cards.test", "FAR_SITE_NAME": "TestCards", "FAR_CONTACT": "hello@cards.test",
    "FAR_SCHEME": "https", "FAR_DB": TMP + "/far.db", "FAR_USERS_ROOT": TMP + "/users", "FAR_ASSETS": TMP + "/assets",
    "FAR_LOG_DIR": TMP + "/log", "FAR_SECRET": "test-secret", "FAR_RESERVED_FILE": TMP + "/reserved.txt",
    "FAR_ADMINS": "admin@cards.test", "FAR_OUTBOX": TMP + "/outbox.txt",
})
for sub in ("users", "assets", "log"):
    os.makedirs(TMP + "/" + sub, exist_ok=True)
for p in (ROOT, ROOT / "service"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))
