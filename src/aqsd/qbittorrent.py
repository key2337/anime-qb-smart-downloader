from __future__ import annotations

from typing import Any

import requests


class QBittorrentAddTorrentError(RuntimeError):
    pass


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
        self._raise_for_add_failure(
            response,
            input_value=url,
            category=category,
            save_path=save_path,
            tags=tags,
            paused=paused,
        )

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
        self._raise_for_add_failure(
            response,
            input_value=filename,
            category=category,
            save_path=save_path,
            tags=tags,
            paused=paused,
            input_kind="torrent_file",
        )

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

    def resume_torrents(self, hashes: str) -> None:
        response = self.session.post(
            f"{self.base_url}/api/v2/torrents/resume",
            data={"hashes": hashes},
            timeout=10,
        )
        response.raise_for_status()

    def _raise_for_add_failure(
        self,
        response: requests.Response,
        *,
        input_value: str | None,
        category: str | None,
        save_path: str | None,
        tags: str | None,
        paused: bool,
        input_kind: str | None = None,
    ) -> None:
        body = response.text.strip()
        kind = input_kind or self._classify_add_input(input_value)
        details = self._format_add_context(
            status=response.status_code,
            body=body,
            input_kind=kind,
            input_value=input_value,
            category=category,
            save_path=save_path,
            tags=tags,
            paused=paused,
        )

        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            raise QBittorrentAddTorrentError(f"qB add request failed: {details}; error={exc}") from exc

        if body == "Fails.":
            raise QBittorrentAddTorrentError(f"qB add failed: {details}")

    @staticmethod
    def _classify_add_input(value: str | None) -> str:
        normalized = (value or "").strip()
        if not normalized:
            return "empty"
        if normalized.casefold().startswith("magnet:"):
            return "magnet"
        return "torrent_url"

    @classmethod
    def _format_add_context(
        cls,
        *,
        status: int,
        body: str,
        input_kind: str,
        input_value: str | None,
        category: str | None,
        save_path: str | None,
        tags: str | None,
        paused: bool,
    ) -> str:
        normalized = (input_value or "").strip()
        magnet_present = normalized.casefold().startswith("magnet:")
        torrent_url_present = bool(normalized) and not magnet_present
        return (
            f"status={status} body={body!r} input={input_kind} "
            f"magnet_present={str(magnet_present).lower()} "
            f"torrent_url_present={str(torrent_url_present).lower()} "
            f"url_empty={str(not bool(normalized)).lower()} "
            f"category={category!r} save_path={save_path!r} tags={tags!r} paused={str(paused).lower()}"
        )
