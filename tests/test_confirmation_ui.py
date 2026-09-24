import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ConfirmationUITests(unittest.TestCase):
    def test_every_confirmation_page_loads_shared_dialog_before_its_page_script(self):
        for page in ("users", "admin", "display"):
            with self.subTest(page=page):
                markup = (ROOT / "templates" / f"{page}.html").read_text()
                self.assertIn('<script src="/static/js/confirm.js"></script>', markup)
                self.assertNotIn("window.confirm(", markup)
                self.assertNotIn("onsubmit=\"return confirm(", markup)
        for script in ("update", "display"):
            javascript = (ROOT / "static" / "js" / f"{script}.js").read_text()
            self.assertIn("window.appConfirm({", javascript)
            self.assertNotIn("window.confirm(", javascript)
