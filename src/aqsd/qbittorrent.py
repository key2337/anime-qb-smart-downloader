from __future__ import annotations

from typing import Any

import requests


class QBittorrentClient:
    def __init__(self, base_url: str, username: str, password: str):
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        self.session = requests.Session()

    def login(self) -> None:
        response = self.session.post(
            f"{self.base_url}/api/v2/auth/login",
            data={"username": self.username, "password": self.password},
            timeout=10,
        )
        response.raise_for_status()
        if response.text.strip() != "Ok.":
            raise RuntimeError(f"qBittorrent login failed: {response.text}")

    def get_version(self) -> str:
        response = self.session.get(f"{self.base_url}/api/v2/app/version", timeout=10)
        response.raise_for_status()
        return response.text.strip()

    def add_torrent(
        self,
        url: str,
        category: str | None = None,
        save_path: str | None = None,
        tags: str | None = None,
        paused: bool = False,
    ) -> None:
        payload: dict[str, Any] = {"urls": url}
        if category:
            payload["category"] = category
        if save_path:
            payload["savepath"] = save_path
        if tags:
            payload["tags"] = tags
        if paused:
            payload["paused"] = "true"

        response = self.session.post(
            f"{self.base_url}/api/v2/torrents/add",
            data=payload,
            timeout=20,
        )
        response.raise_for_status()

    def add_torrent_file(
        self,
        filename: str,
        content: bytes,
        category: str | None = None,
        save_path: str | None = None,
        tags: str | None = None,
        paused: bool = False,
    ) -> None:
        payload: dict[str, Any] = {}
        if category:
            payload["category"] = category
        if save_path:
            payload["savepath"] = save_path
        if tags:
            payload["tags"] = tags
        if paused:
            payload["paused"] = "true"

        response = self.session.post(
            f"{self.base_url}/api/v2/torrents/add",
            data=payload,
            files={"torrents": (filename, content, "application/x-bittorrent")},
            timeout=20,
        )
        response.raise_for_status()

    def list_torrents(self) -> list[dict[str, Any]]:
        response = self.session.get(f"{self.base_url}/api/v2/torrents/info", timeout=10)
        response.raise_for_status()
        return response.json()

    def delete_torrent(self, torrent_hash: str, delete_files: bool = False) -> None:
        response = self.session.post(
            f"{self.base_url}/api/v2/torrents/delete",
            data={"hashes": torrent_hash, "deleteFiles": str(delete_files).lower()},
            timeout=10,
        )
        response.raise_for_status()

    def pause_torrents(self, hashes: str) -> None:
        response = self.session.post(
            f"{self.base_url}/api/v2/torrents/pause",
            data={"hashes": hashes},
            timeout=10,
        )
        response.raise_for_status()
