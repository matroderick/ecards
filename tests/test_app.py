import io, unittest
import _env
import app as ecards
import build_landing


def call(path, method="GET", host="app.cards.test", body=b"", ctype="application/x-www-form-urlencoded"):
    env = {"REQUEST_METHOD": method, "PATH_INFO": path, "QUERY_STRING": "", "HTTP_HOST": host, "REMOTE_ADDR": "203.0.113.9",
           "CONTENT_LENGTH": str(len(body)), "CONTENT_TYPE": ctype, "wsgi.input": io.BytesIO(body)}
    out = {}
    chunks = ecards.app(env, lambda status, headers: out.update(status=status, headers=dict(headers)))
    return out["status"], out["headers"], b"".join(chunks).decode("utf-8", "replace")


class Pages(unittest.TestCase):
    def test_sign_in_page(self):
        status, _, body = call("/")
        self.assertTrue(status.startswith("200"))
        self.assertIn("TestCards", body)

    def test_terms_and_privacy_follow_config(self):
        for path in ("/terms", "/privacy"):
            status, _, body = call(path)
            self.assertTrue(status.startswith("200"), path)
            self.assertIn("TestCards", body)
            self.assertIn("hello@cards.test", body)
            self.assertNotIn("far.cx", body)
        self.assertIn("yourname.cards.test", call("/terms")[2])

    def test_request_invite_form(self):
        status, _, body = call("/request")
        self.assertTrue(status.startswith("200"))
        self.assertIn("invitation-only", body)
        self.assertIn(".cards.test", body)

    def test_unknown_route_404(self):
        self.assertTrue(call("/nope")[0].startswith("404"))

    def test_admin_requires_sign_in(self):
        status, headers, _ = call("/admin")
        self.assertFalse(status.startswith("200"))


class Landing(unittest.TestCase):
    def test_placeholders_replaced(self):
        tpl = (_env.ROOT / "service" / "landing" / "index.tmpl.html").read_text()
        html = build_landing.render(tpl)
        self.assertNotIn("{{", html)
        self.assertIn("app.cards.test", html)
        self.assertIn("TestCards", html)
        self.assertNotIn("far.cx", html)


if __name__ == "__main__":
    unittest.main()
