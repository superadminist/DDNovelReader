# -*- coding: utf-8 -*-
from __future__ import annotations

import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from novelreader.software_update import (
    LATEST_RELEASE_API,
    SoftwareUpdateError,
    SoftwareUpdateService,
    is_newer_version,
    version_tuple,
)


def release_payload(version: str, installer: bytes, *, checksum_hash: str | None = None):
    tag = f"v{version}"
    base = f"https://github.com/superadminist/QYReader/releases/download/{tag}"
    name = f"QYReader-Setup-{version}.exe"
    digest = checksum_hash or hashlib.sha256(installer).hexdigest()
    return {
        "tag_name": tag,
        "html_url": f"https://github.com/superadminist/QYReader/releases/tag/{tag}",
        "published_at": "2026-09-14T09:00:00Z",
        "body": "## 本次优化\n\n- 修复悬浮窗暂停错句\n- 设置立即生效",
        "assets": [
            {"name": name, "browser_download_url": f"{base}/{name}", "size": len(installer)},
            {"name": "SHA256SUMS.txt", "browser_download_url": f"{base}/SHA256SUMS.txt", "size": 96},
        ],
        "checksum": f"{digest} *{name}\n".encode("ascii"),
    }


class SoftwareUpdateServiceTests(unittest.TestCase):
    def test_semantic_versions_compare_numerically(self):
        self.assertEqual(version_tuple("v2.10.3"), (2, 10, 3))
        self.assertTrue(is_newer_version("2.0.2", "2.0.1"))
        self.assertFalse(is_newer_version("2.0.1", "2.0.1"))
        with self.assertRaises(ValueError):
            version_tuple("2.0")

    def test_check_and_download_exact_release_assets_with_sha256(self):
        installer = b"signed-by-release-checksum"
        payload = release_payload("2.0.2", installer)
        metadata = {key: value for key, value in payload.items() if key != "checksum"}
        responses = {
            LATEST_RELEASE_API: json.dumps(metadata).encode("utf-8"),
            metadata["assets"][0]["browser_download_url"]: installer,
            metadata["assets"][1]["browser_download_url"]: payload["checksum"],
        }
        requested = []

        def opener(request, timeout):
            requested.append((request.full_url, timeout, request.headers.get("User-agent")))
            return io.BytesIO(responses[request.full_url])

        with tempfile.TemporaryDirectory() as temp:
            service = SoftwareUpdateService(
                current_version="2.0.1", update_dir=temp, opener=opener
            )
            release = service.check_latest()
            progress = []
            path = service.download(release, lambda done, total: progress.append((done, total)))

            self.assertEqual(release.version, "2.0.2")
            self.assertIn("修复悬浮窗暂停错句", release.release_notes)
            self.assertEqual(path.read_bytes(), installer)
            self.assertEqual(progress[-1], (len(installer), len(installer)))
            self.assertEqual(requested[0][0], LATEST_RELEASE_API)
            self.assertEqual(requested[0][2], "QYReader/2.0.1")

    def test_non_newer_release_does_not_require_installer_assets(self):
        payload = {
            "tag_name": "v2.0.0",
            "html_url": "https://github.com/superadminist/QYReader/releases/tag/v2.0.0",
            "published_at": "2026-09-14T04:00:00Z",
            "assets": [],
        }
        service = SoftwareUpdateService(
            current_version="2.0.1",
            opener=lambda _request, timeout: io.BytesIO(json.dumps(payload).encode("utf-8")),
        )
        self.assertEqual(service.check_latest().version, "2.0.0")

    def test_newer_release_without_trusted_assets_is_rejected(self):
        payload = release_payload("2.0.2", b"installer")
        payload["assets"][0]["browser_download_url"] = "https://example.com/QYReader.exe"
        payload.pop("checksum")
        service = SoftwareUpdateService(
            current_version="2.0.1",
            opener=lambda _request, timeout: io.BytesIO(json.dumps(payload).encode("utf-8")),
        )
        with self.assertRaises(SoftwareUpdateError) as raised:
            service.check_latest()
        self.assertEqual(raised.exception.code, "UPDATE_ASSET_MISSING")

    def test_release_notes_are_plain_text_and_bounded(self):
        value = "更新内容\x00\r\n" + ("优化" * 7_000)
        notes = SoftwareUpdateService._release_notes(value)
        self.assertNotIn("\x00", notes)
        self.assertIn("更新内容\n", notes)
        self.assertLessEqual(len(notes), 12_000)
        self.assertTrue(notes.endswith("…"))

    def test_checksum_mismatch_discards_partial_installer(self):
        installer = b"corrupted-installer"
        payload = release_payload("2.0.2", installer, checksum_hash="0" * 64)
        metadata = {key: value for key, value in payload.items() if key != "checksum"}
        responses = {
            LATEST_RELEASE_API: json.dumps(metadata).encode("utf-8"),
            metadata["assets"][0]["browser_download_url"]: installer,
            metadata["assets"][1]["browser_download_url"]: payload["checksum"],
        }

        with tempfile.TemporaryDirectory() as temp:
            service = SoftwareUpdateService(
                current_version="2.0.1",
                update_dir=temp,
                opener=lambda request, timeout: io.BytesIO(responses[request.full_url]),
            )
            release = service.check_latest()
            with self.assertRaises(SoftwareUpdateError) as raised:
                service.download(release)
            self.assertEqual(raised.exception.code, "UPDATE_CHECKSUM_FAILED")
            self.assertEqual(list(Path(temp).iterdir()), [])


if __name__ == "__main__":
    unittest.main()
