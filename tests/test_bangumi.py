from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

import requests

from aqsd.bangumi import parse_bangumi_search_response, search_bangumi_titles
from aqsd.config import AppConfig, load_config


class BangumiTests(unittest.TestCase):
    def test_parse_bangumi_response_extracts_name_name_cn_and_aliases(self) -> None:
        payload = {
            "data": [
                {
                    "id": 123,
                    "name": "Angel Beats!",
                    "name_cn": "天使的心跳",
                    "date": "2010-04-03",
                    "rank": 27,
                    "rating": {"score": 8.1},
                    "infobox": [
                        {"key": "别名", "value": [{"v": "エンジェルビーツ"}, {"v": "AB!"}]},
                        {"key": "英文名", "value": "Angel Beats!"},
                    ],
                }
            ]
        }

        results = parse_bangumi_search_response(payload)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].subject_id, 123)
        self.assertEqual(results[0].name, "Angel Beats!")
        self.assertEqual(results[0].name_cn, "天使的心跳")
        self.assertEqual(results[0].date, "2010-04-03")
        self.assertEqual(results[0].rank, 27)
        self.assertEqual(results[0].score, 8.1)
        self.assertIn("Angel Beats!", results[0].aliases)
        self.assertIn("天使的心跳", results[0].aliases)
        self.assertIn("エンジェルビーツ", results[0].aliases)
        self.assertIn("AB!", results[0].aliases)

    def test_parse_bangumi_response_extracts_array_aliases_from_infobox(self) -> None:
        payload = {
            "data": [
                {
                    "id": 1,
                    "name": "Kanon",
                    "name_cn": "雪之少女",
                    "infobox": [
                        {"key": "别名", "value": [{"v": "カノン"}, {"v": "Kanon 2006"}]},
                    ],
                }
            ]
        }

        results = parse_bangumi_search_response(payload)

        self.assertEqual(results[0].aliases, ["Kanon", "雪之少女", "カノン", "Kanon 2006"])

    def test_parse_bangumi_response_extracts_string_aliases_from_infobox(self) -> None:
        payload = {
            "data": [
                {
                    "id": 2,
                    "name": "Clannad",
                    "name_cn": "团子大家族",
                    "infobox": [
                        {"key": "中文名", "value": "团子大家族"},
                        {"key": "别名", "value": "クラナド"},
                    ],
                }
            ]
        }

        results = parse_bangumi_search_response(payload)

        self.assertIn("クラナド", results[0].aliases)
        self.assertIn("团子大家族", results[0].aliases)

    def test_search_bangumi_titles_http_failure_returns_empty_results(self) -> None:
        session = Mock()
        session.post.side_effect = requests.RequestException("boom")

        results = search_bangumi_titles("天使的心跳", session=session)

        self.assertEqual(results, [])

    def test_config_uses_safe_bangumi_defaults_when_missing(self) -> None:
        config = AppConfig.model_validate(
            {
                "qbittorrent": {
                    "base_url": "http://127.0.0.1:8080",
                    "username": "user",
                    "password": "pass",
                }
            }
        )

        self.assertFalse(config.metadata_sources.bangumi.enabled)
        self.assertEqual(config.metadata_sources.bangumi.timeout_seconds, 8)
        self.assertEqual(config.metadata_sources.bangumi.max_results, 5)

    def test_load_config_reads_bangumi_enabled_from_yaml(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"
            config_path.write_text(
                """
qbittorrent:
  base_url: "http://127.0.0.1:8080"
  username: "user"
  password: "pass"
metadata_sources:
  bangumi:
    enabled: true
    timeout_seconds: 8
    max_results: 5
  anilist:
    enabled: true
""".strip(),
                encoding="utf-8",
            )

            config = load_config(config_path)

        self.assertTrue(config.metadata_sources.bangumi.enabled)
        self.assertTrue(config.metadata_sources.anilist.enabled)


if __name__ == "__main__":
    unittest.main()
