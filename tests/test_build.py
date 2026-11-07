import json, unittest
import _env
import build

PERSON = {"name": "Sam Rivera", "given": "Sam", "family": "Rivera"}
PERSONA = {"label": "Work", "org": "Rivera Studio", "title": "Designer", "email": "sam@example.com",
           "phone": "+44 20 7946 0123", "accent": "#0f766e"}


class Cards(unittest.TestCase):
    def test_vcard(self):
        v = build.make_vcard(PERSON, PERSONA, "", "work", "https://sam.cards.test/work/")
        self.assertTrue(v.startswith("BEGIN:VCARD") and v.rstrip().endswith("END:VCARD"))
        for needle in ("FN:Sam Rivera", "ORG:Rivera Studio", "TITLE:Designer", "sam@example.com"):
            self.assertIn(needle, v)

    def test_page_has_content_and_privacy_contact(self):
        html = build.make_page(PERSON, PERSONA, "work", {"work": PERSONA}, "", "../", "sam.vcf",
                               "data:image/jpeg;base64,", "https://sam.cards.test/work/", "https://sam.cards.test/work/photo.jpg")
        self.assertIn("Sam Rivera", html)
        self.assertIn("Rivera Studio", html)
        self.assertIn("hello@cards.test", html)   # FAR_CONTACT drives the privacy notice

    def test_bad_accent_rejected(self):
        with self.assertRaises(SystemExit):
            build.make_page(PERSON, dict(PERSONA, accent="blue"), "work", {"work": PERSONA}, "", "../", "x.vcf", "", "u", "o")

    def test_demo_cards_are_valid_json(self):
        cfg = json.loads((_env.ROOT / "service" / "demo_cards.json").read_text())
        self.assertIn("people", cfg)


if __name__ == "__main__":
    unittest.main()
