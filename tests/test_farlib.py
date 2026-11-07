import unittest
import _env  # noqa: F401
import farlib


class Handles(unittest.TestCase):
    def test_valid_and_invalid(self):
        for ok in ("a", "mat", "my-name", "a1", "x" * 30):
            self.assertIsNone(farlib.handle_error(ok), ok)
        for bad in ("", "-a", "a-", "a--b", "A", "has space", "x" * 31, "www", "admin", "app"):
            self.assertIsNotNone(farlib.handle_error(bad), bad)

    def test_blocked_words(self):
        self.assertIsNotNone(farlib.handle_error("shitty"))


class Hosts(unittest.TestCase):
    def test_tenant_from_host(self):
        self.assertEqual(farlib.tenant_from_host("alex.cards.test"), "alex")
        self.assertEqual(farlib.tenant_from_host("ALEX.cards.test:8443"), "alex")
        self.assertIsNone(farlib.tenant_from_host("cards.test"))
        self.assertIsNone(farlib.tenant_from_host("app.cards.test"))
        self.assertIsNone(farlib.tenant_from_host("alex.other.test"))
        self.assertIsNone(farlib.tenant_from_host("a.b.cards.test"))

    def test_origins(self):
        self.assertEqual(farlib.card_origin("alex"), "https://alex.cards.test")
        self.assertEqual(farlib.app_origin(), "https://app.cards.test")

    def test_log_name(self):
        self.assertEqual(farlib.log_name("cards.test"), "_site")
        self.assertEqual(farlib.log_name("www.cards.test"), "_site")
        self.assertIsNone(farlib.log_name("nobody.cards.test"))   # no such tenant: beacon ignored


class Tokens(unittest.TestCase):
    def test_roundtrip_and_isolation(self):
        t = farlib.derive("alex", "log", 1)
        self.assertTrue(farlib.check_token(t, "alex", "log", 1))
        self.assertFalse(farlib.check_token(t, "sam", "log", 1))
        self.assertFalse(farlib.check_token(t, "alex", "loc", 1))
        self.assertFalse(farlib.check_token(t, "alex", "log", 2))
        self.assertFalse(farlib.check_token("", "alex", "log", 1))


if __name__ == "__main__":
    unittest.main()
