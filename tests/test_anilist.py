from __future__ import annotations

import unittest

from aqsd.anilist import parse_anilist_response


class AniListTests(unittest.TestCase):
    def test_parse_anilist_response_extracts_titles_synonyms_year_and_format(self) -> None:
        payload = {
            "data": {
                "Page": {
                    "media": [
                        {
                            "title": {
                                "romaji": "One Punch Man",
                                "english": "One-Punch Man",
                                "native": "ワンパンマン",
                            },
                            "synonyms": ["Wanpanman", "OPM"],
                            "seasonYear": 2015,
                            "format": "TV",
                        }
                    ]
                }
            }
        }

        results = parse_anilist_response(payload)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].canonical, "One Punch Man")
        self.assertEqual(
            results[0].aliases,
            ["One Punch Man", "One-Punch Man", "ワンパンマン", "Wanpanman", "OPM"],
        )
        self.assertEqual(results[0].romaji, "One Punch Man")
        self.assertEqual(results[0].english, "One-Punch Man")
        self.assertEqual(results[0].native, "ワンパンマン")
        self.assertEqual(results[0].year, 2015)
        self.assertEqual(results[0].format, "TV")


if __name__ == "__main__":
    unittest.main()
