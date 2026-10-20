import os
import stat
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app import audio_content_matches_extension
from database import database
from security import SECURITY_HEADERS, request_has_trusted_origin


def request(method="POST", origin=None, fetch_site=None, base_url="http://localhost:8000/"):
    headers = {}
    if origin is not None:
        headers["origin"] = origin
    if fetch_site is not None:
        headers["sec-fetch-site"] = fetch_site
    return SimpleNamespace(method=method, headers=headers, base_url=base_url)


class BrowserBoundaryTests(unittest.TestCase):
    def test_same_origin_browser_mutation_is_allowed(self):
        self.assertTrue(request_has_trusted_origin(request(origin="http://localhost:8000")))

    def test_cross_origin_browser_mutation_is_rejected(self):
        self.assertFalse(request_has_trusted_origin(request(origin="https://example.test")))
        self.assertFalse(request_has_trusted_origin(request(fetch_site="cross-site")))

    def test_non_browser_client_without_origin_is_allowed(self):
        self.assertTrue(request_has_trusted_origin(request()))

    def test_read_only_request_does_not_require_an_origin(self):
        self.assertTrue(request_has_trusted_origin(request(method="GET", origin="https://example.test")))

    def test_baseline_headers_cover_common_browser_boundaries(self):
        self.assertEqual(SECURITY_HEADERS["X-Content-Type-Options"], "nosniff")
        self.assertIn("frame-ancestors 'none'", SECURITY_HEADERS["Content-Security-Policy"])
        self.assertIn("form-action 'self'", SECURITY_HEADERS["Content-Security-Policy"])


class UploadedAudioTests(unittest.TestCase):
    def test_container_signatures_match_their_extensions(self):
        self.assertTrue(audio_content_matches_extension(b"RIFF\x00\x00\x00\x00WAVE", ".wav"))
        self.assertTrue(audio_content_matches_extension(b"OggS\x00", ".ogg"))
        self.assertTrue(audio_content_matches_extension(b"ID3\x04", ".mp3"))
        self.assertTrue(audio_content_matches_extension(b"\xff\xfb\x90\x64", ".mp3"))

    def test_mismatched_or_unknown_content_is_rejected(self):
        self.assertFalse(audio_content_matches_extension(b"<html>", ".mp3"))
        self.assertFalse(audio_content_matches_extension(b"OggS\x00", ".wav"))
        self.assertFalse(audio_content_matches_extension(b"RIFF\x00\x00\x00\x00WAVE", ".aac"))


@unittest.skipIf(os.name == "nt", "POSIX mode bits are not enforced on Windows")
class PrivateDatabaseTests(unittest.TestCase):
    def test_database_is_owner_readable_and_writable_only(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "leftover.db"
            with (
                patch.object(database, "DB_PATH", str(path)),
                patch.object(database, "DB_DIR", directory),
            ):
                database.init_db()
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)


if __name__ == "__main__":
    unittest.main()
