from __future__ import annotations

import unittest

from aqsd.config import TorznabEndpointSettings
from aqsd.torznab import build_torznab_search_url, parse_torznab_xml


TORZNAB_XML = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:torznab="http://torznab.com/schemas/2015/feed">
  <channel>
    <item>
      <title>[Indexer] Example Anime - 01 [1080p]</title>
      <link>https://indexer.test/details/1</link>
      <guid>ABCDEF1234567890</guid>
      <pubDate>Tue, 12 May 2026 10:00:00 +0000</pubDate>
      <enclosure url="magnet:?xt=urn:btih:ABCDEF1234567890" type="application/x-bittorrent" />
      <torznab:attr name="seeders" value="42" />
      <torznab:attr name="infohash" value="ABCDEF1234567890" />
    </item>
  </channel>
</rss>
"""


class TorznabTests(unittest.TestCase):
    def test_build_torznab_search_url_includes_required_params_and_categories(self) -> None:
        endpoint = TorznabEndpointSettings(
            name="jackett-nyaa",
            url="http://127.0.0.1:9117/api/v2.0/indexers/nyaa/results/torznab/",
            api_key="secret",
            categories=["5070", "100001"],
            timeout_seconds=15,
        )

        url = build_torznab_search_url(endpoint, "One Punch Man")

        self.assertEqual(
            url,
            "http://127.0.0.1:9117/api/v2.0/indexers/nyaa/results/torznab/?t=search&q=One+Punch+Man&apikey=secret&cat=5070%2C100001",
        )

    def test_parse_torznab_xml_reads_title_link_seeders_hash_and_enclosure(self) -> None:
        candidates = parse_torznab_xml(TORZNAB_XML, source_name="jackett-nyaa")

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].title, "[Indexer] Example Anime - 01 [1080p]")
        self.assertEqual(candidates[0].url, "magnet:?xt=urn:btih:ABCDEF1234567890")
        self.assertEqual(candidates[0].source, "jackett-nyaa")
        self.assertEqual(candidates[0].seeders, 42)
        self.assertEqual(candidates[0].info_hash, "ABCDEF1234567890")
        self.assertIsNotNone(candidates[0].published_at)


if __name__ == "__main__":
    unittest.main()
