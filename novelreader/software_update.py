# -*- coding: utf-8 -*-
"""Secure GitHub Release checks and installer downloads for QYReader."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

from . import __version__


LATEST_RELEASE_API = "https://api.github.com/repos/superadminist/QYReader/releases/latest"
PROJECT_URL = "https://github.com/superadminist/QYReader"
RELEASES_URL = f"{PROJECT_URL}/releases"
API_VERSION = "2026-03-10"
MAX_RELEASE_BYTES = 1024 * 1024
MAX_CHECKSUM_BYTES = 64 * 1024
MAX_INSTALLER_BYTES = 512 * 1024 * 1024
_VERSION_PATTERN = re.compile(r"^v?(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")


class SoftwareUpdateError(Exception):
    def __init__(self, code: str, message: str, retryable: bool = False):
        super().__init__(message)
        self.code = code
        self.user_message = message
        self.retryable = retryable


@dataclass(frozen=True)
class ReleaseInfo:
    version: str
    tag: str
    release_url: str
    published_at: str
    installer_name: str
    installer_url: str
    installer_size: int
    checksum_url: str
    release_notes: str = ""

    @property
    def is_newer(self) -> bool:
        return version_tuple(self.version) > version_tuple(__version__)


def version_tuple(value: str) -> tuple[int, int, int]:
    match = _VERSION_PATTERN.fullmatch(str(value or "").strip())
    if not match:
        raise ValueError(f"Unsupported semantic version: {value!r}")
    return tuple(int(part) for part in match.groups())


def is_newer_version(candidate: str, current: str = __version__) -> bool:
    return version_tuple(candidate) > version_tuple(current)


def default_update_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA")
    root = Path(base) if base else Path(tempfile.gettempdir())
    return root / "QYReader" / "updates"


class SoftwareUpdateService:
    def __init__(
        self,
        *,
        current_version: str = __version__,
        update_dir: str | os.PathLike[str] | None = None,
        opener: Callable | None = None,
    ):
        version_tuple(current_version)
        self.current_version = current_version
        self.update_dir = Path(update_dir) if update_dir else default_update_dir()
        self._opener = opener or urllib.request.urlopen

    def check_latest(self) -> ReleaseInfo:
        request = urllib.request.Request(
            LATEST_RELEASE_API,
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": f"QYReader/{self.current_version}",
                "X-GitHub-Api-Version": API_VERSION,
            },
        )
        try:
            payload = json.loads(self._read_limited(request, MAX_RELEASE_BYTES).decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise SoftwareUpdateError(
                "UPDATE_CHECK_FAILED", "无法连接 GitHub 检查更新，请确认网络后重试。", True
            ) from exc
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise SoftwareUpdateError(
                "UPDATE_RESPONSE_INVALID", "GitHub 返回的版本信息无法识别。", True
            ) from exc

        if not isinstance(payload, dict):
            raise SoftwareUpdateError("UPDATE_RESPONSE_INVALID", "GitHub 返回的版本信息无法识别。", True)
        tag = str(payload.get("tag_name") or "").strip()
        try:
            version_tuple(tag)
        except ValueError as exc:
            raise SoftwareUpdateError("UPDATE_VERSION_INVALID", "最新正式版的版本号格式不正确。") from exc
        version = tag[1:] if tag.lower().startswith("v") else tag
        release_url = str(payload.get("html_url") or "")
        if not self._trusted_release_url(release_url):
            raise SoftwareUpdateError("UPDATE_URL_INVALID", "最新版本的发布地址不安全。")

        installer_name = f"QYReader-Setup-{version}.exe"
        installer_url = ""
        checksum_url = ""
        installer_size = 0
        assets = payload.get("assets")
        if not isinstance(assets, list):
            assets = []
        for asset in assets:
            if not isinstance(asset, dict):
                continue
            name = asset.get("name")
            url = str(asset.get("browser_download_url") or "")
            if name == installer_name:
                installer_url = url
                size = asset.get("size")
                installer_size = size if isinstance(size, int) else 0
            elif name == "SHA256SUMS.txt":
                checksum_url = url

        info = ReleaseInfo(
            version=version,
            tag=tag,
            release_url=release_url,
            published_at=str(payload.get("published_at") or ""),
            installer_name=installer_name,
            installer_url=installer_url,
            installer_size=installer_size,
            checksum_url=checksum_url,
            release_notes=self._release_notes(payload.get("body")),
        )
        if is_newer_version(info.version, self.current_version):
            if not self._trusted_asset_url(info.installer_url, info.tag, info.installer_name):
                raise SoftwareUpdateError(
                    "UPDATE_ASSET_MISSING", "新版本尚未提供匹配的 Windows 安装包，请稍后重试。", True
                )
            if not self._trusted_asset_url(info.checksum_url, info.tag, "SHA256SUMS.txt"):
                raise SoftwareUpdateError(
                    "UPDATE_CHECKSUM_MISSING", "新版本缺少 SHA256 校验文件，已拒绝下载。"
                )
            if not 0 < info.installer_size <= MAX_INSTALLER_BYTES:
                raise SoftwareUpdateError("UPDATE_SIZE_INVALID", "新版本安装包大小异常，已拒绝下载。")
        return info

    def download(
        self,
        release: ReleaseInfo,
        progress: Callable[[int, int], None] | None = None,
    ) -> Path:
        if not is_newer_version(release.version, self.current_version):
            raise SoftwareUpdateError("UPDATE_NOT_AVAILABLE", "当前没有可安装的新版本。")
        if not self._trusted_asset_url(release.installer_url, release.tag, release.installer_name):
            raise SoftwareUpdateError("UPDATE_URL_INVALID", "安装包下载地址不安全。")
        if not self._trusted_asset_url(release.checksum_url, release.tag, "SHA256SUMS.txt"):
            raise SoftwareUpdateError("UPDATE_URL_INVALID", "校验文件下载地址不安全。")

        checksum_request = self._asset_request(release.checksum_url)
        try:
            checksum_text = self._read_limited(checksum_request, MAX_CHECKSUM_BYTES).decode("ascii")
        except (urllib.error.URLError, TimeoutError, OSError, UnicodeError) as exc:
            raise SoftwareUpdateError(
                "UPDATE_DOWNLOAD_FAILED", "无法下载新版本校验文件，请稍后重试。", True
            ) from exc
        expected_hash = self._checksum_for(checksum_text, release.installer_name)

        self.update_dir.mkdir(parents=True, exist_ok=True)
        destination = self.update_dir / release.installer_name
        if destination.is_file() and self._sha256(destination) == expected_hash:
            if progress:
                progress(destination.stat().st_size, destination.stat().st_size)
            return destination

        temporary = destination.with_suffix(destination.suffix + ".part")
        temporary.unlink(missing_ok=True)
        downloaded = 0
        request = self._asset_request(release.installer_url)
        try:
            with self._opener(request, timeout=30) as response, temporary.open("wb") as stream:
                while True:
                    chunk = response.read(128 * 1024)
                    if not chunk:
                        break
                    downloaded += len(chunk)
                    if downloaded > MAX_INSTALLER_BYTES:
                        raise SoftwareUpdateError("UPDATE_SIZE_INVALID", "新版本安装包超过安全大小限制。")
                    stream.write(chunk)
                    if progress:
                        progress(downloaded, release.installer_size)
            if release.installer_size and downloaded != release.installer_size:
                raise SoftwareUpdateError(
                    "UPDATE_DOWNLOAD_INCOMPLETE", "新版本安装包下载不完整，请重新下载。", True
                )
            if self._sha256(temporary) != expected_hash:
                raise SoftwareUpdateError(
                    "UPDATE_CHECKSUM_FAILED", "新版本安装包校验失败，文件已丢弃。", True
                )
            os.replace(temporary, destination)
            return destination
        except SoftwareUpdateError:
            temporary.unlink(missing_ok=True)
            raise
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            temporary.unlink(missing_ok=True)
            raise SoftwareUpdateError(
                "UPDATE_DOWNLOAD_FAILED", "新版本安装包下载失败，请稍后重试。", True
            ) from exc

    def _read_limited(self, request: urllib.request.Request, limit: int) -> bytes:
        with self._opener(request, timeout=15) as response:
            data = response.read(limit + 1)
        if len(data) > limit:
            raise SoftwareUpdateError("UPDATE_RESPONSE_TOO_LARGE", "更新服务器返回的数据异常。")
        return data

    @staticmethod
    def _release_notes(value: object) -> str:
        """Keep release notes readable and bounded before sending them to WebEngine."""
        if not isinstance(value, str):
            return ""
        cleaned = "".join(
            character
            for character in value.replace("\r\n", "\n").replace("\r", "\n")
            if character in {"\n", "\t"} or ord(character) >= 32
        ).strip()
        if len(cleaned) <= 12_000:
            return cleaned
        return cleaned[:11_999].rstrip() + "…"

    def _asset_request(self, url: str) -> urllib.request.Request:
        return urllib.request.Request(url, headers={"User-Agent": f"QYReader/{self.current_version}"})

    @staticmethod
    def _checksum_for(text: str, installer_name: str) -> str:
        for line in text.splitlines():
            match = re.fullmatch(r"([0-9A-Fa-f]{64}) \*(.+)", line.strip())
            if match and match.group(2) == installer_name:
                return match.group(1).upper()
        raise SoftwareUpdateError(
            "UPDATE_CHECKSUM_INVALID", "SHA256 校验文件中没有匹配当前安装包的记录。"
        )

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest().upper()

    @staticmethod
    def _trusted_release_url(url: str) -> bool:
        parsed = urlparse(url)
        return (
            parsed.scheme == "https"
            and parsed.hostname == "github.com"
            and parsed.path.startswith("/superadminist/QYReader/releases/")
        )

    @staticmethod
    def _trusted_asset_url(url: str, tag: str, name: str) -> bool:
        parsed = urlparse(url)
        expected = f"/superadminist/QYReader/releases/download/{tag}/{name}"
        return parsed.scheme == "https" and parsed.hostname == "github.com" and parsed.path == expected
