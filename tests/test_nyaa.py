from __future__ import annotations

import unittest

from aqsd.config import NyaaSearchSourceSettings
from aqsd.nyaa import build_nyaa_rss_url


class NyaaTests(unittest.TestCase):
    def test_build_nyaa_rss_url_includes_query_category_and_page(self) -> None:
        settings = NyaaSearchSourceSettings(
            enabled=True,
            base_url="https://nyaa.si/",
            default_category="1_2",
            timeout_seconds=15,
        )

        url = build_nyaa_rss_url(settings, "One Punch Man", page=2)

        self.assertEqual(url, "https://nyaa.si/?page=rss&q=One+Punch+Man&c=1_2&p=2")


if __name__ == "__main__":
    unittest.main()
