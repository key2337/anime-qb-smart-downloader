from __future__ import annotations

import unittest
from unittest.mock import Mock

from requests import HTTPError

from aqsd.qbittorrent import QBittorrentAddTorrentError, QBittorrentClient


class QBittorrentTests(unittest.TestCase):
    def test_add_torrent_failure_body_includes_status_body_and_context(self) -> None:
        client = QBittorrentClient("http://127.0.0.1:8080", "user", "pass")
        response = Mock()
        response.status_code = 200
        response.text = "Fails."
        response.raise_for_status.return_value = None
        client.session.post = Mock(return_value=response)

        with self.assertRaises(QBittorrentAddTorrentError) as exc:
            client.add_torrent(
                "magnet:?xt=urn:btih:ABC123",
                category="Anime",
                save_path="/downloads/anime",
                tags="task-1",
            )

        message = str(exc.exception)
        self.assertIn("status=200", message)
        self.assertIn("body='Fails.'", message)
        self.assertIn("input=magnet", message)
        self.assertIn("magnet_present=true", message)
        self.assertIn("torrent_url_present=false", message)
        self.assertIn("save_path='/downloads/anime'", message)

    def test_add_torrent_http_error_includes_status_body_and_original_error(self) -> None:
        client = QBittorrentClient("http://127.0.0.1:8080", "user", "pass")
        response = Mock()
        response.status_code = 403
        response.text = "Forbidden"
        response.raise_for_status.side_effect = HTTPError("403 Client Error: Forbidden")
        client.session.post = Mock(return_value=response)

        with self.assertRaises(QBittorrentAddTorrentError) as exc:
            client.add_torrent("https://example.test/file.torrent")

        message = str(exc.exception)
        self.assertIn("status=403", message)
        self.assertIn("body='Forbidden'", message)
        self.assertIn("input=torrent_url", message)
        self.assertIn("403 Client Error: Forbidden", message)


if __name__ == "__main__":
    unittest.main()
