from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from aqsd.database import Database


class SubscriptionDBTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.db = Database(str(Path(self.tmp) / "test.db"))

    def tearDown(self) -> None:
        self.db.close()

    def test_save_and_list_subscriptions(self) -> None:
        sub_id = self.db.save_subscription("葬送的芙莉莲", source_name="mikan-agg", match_name="Frieren")
        self.assertGreater(sub_id, 0)
        subs = self.db.list_subscriptions()
        self.assertEqual(len(subs), 1)
        self.assertEqual(subs[0]["name"], "葬送的芙莉莲")
        self.assertEqual(subs[0]["source_name"], "mikan-agg")

    def test_delete_subscription(self) -> None:
        sub_id = self.db.save_subscription("Test")
        self.assertTrue(self.db.delete_subscription(sub_id))
        self.assertIsNone(self.db.get_subscription(sub_id))

    def test_update_check(self) -> None:
        sub_id = self.db.save_subscription("Test")
        self.db.update_subscription_check(sub_id, last_episode="05")
        sub = self.db.get_subscription(sub_id)
        self.assertIsNotNone(sub["last_check_at"])
        self.assertEqual(sub["last_episode"], "05")

    def test_subscription_events(self) -> None:
        sub_id = self.db.save_subscription("Test")
        self.db.add_subscription_event(sub_id, "cart_created", anime_name="Test", episode="01", details="3 个候选")
        self.db.add_subscription_event(sub_id, "check_done", anime_name="Test", details="无新剧集")
        events = self.db.get_recent_events(limit=10)
        self.assertEqual(len(events), 2)
        self.assertEqual(events[0]["subscription_name"], "Test")


if __name__ == "__main__":
    unittest.main()
