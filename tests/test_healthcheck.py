from __future__ import annotations

import unittest
from unittest.mock import patch

from aqsd.config import AppConfig
from aqsd.healthcheck import check_connections, log_config_summary


def _build_config() -> AppConfig:
    return AppConfig.model_validate(
        {
            "qbittorrent": {
                "base_url": "http://127.0.0.1:8080",
                "username": "user",
                "password": "pass",
            },
            "rss_sources": [],
            "metadata_sources": {
                "bangumi": {"enabled": True},
                "anilist": {"enabled": False},
            },
        }
    )


class HealthcheckTests(unittest.TestCase):
    @patch("aqsd.healthcheck.logger.info")
    def test_log_config_summary_reports_config_path_and_metadata_sources(self, mock_logger_info) -> None:
        log_config_summary(_build_config(), config_path="config.yaml")

        rendered_messages = [call.args[0] for call in mock_logger_info.call_args_list]
        self.assertIn("Config loaded: path={}", rendered_messages)
        self.assertIn("Metadata sources:", rendered_messages)
        self.assertIn("  Bangumi: {}", rendered_messages)
        self.assertIn("  AniList: {}", rendered_messages)

    @patch("aqsd.healthcheck.check_qb_connection", return_value=True)
    @patch("aqsd.healthcheck.check_rss_connections", return_value=True)
    def test_check_connections_does_not_fail_due_to_metadata_source_status(self, mock_rss, mock_qb) -> None:
        self.assertTrue(check_connections(_build_config()))
        mock_qb.assert_called_once()
        mock_rss.assert_called_once()


if __name__ == "__main__":
    unittest.main()
