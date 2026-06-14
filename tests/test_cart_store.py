from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from aqsd.cart_store import CartStore
from aqsd.models import Cart, CartEvent, CartItem


class CartStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.path = Path(self.tmp) / "carts.json"

    def test_save_and_get(self) -> None:
        store = CartStore(self.path)
        cart = Cart(
            cart_id="test-1",
            anime_name="Test Anime",
            episode="01",
            items=[CartItem(title="Test Item", magnet="magnet:?xt=urn:btih:abc", url="http://x")],
        )
        store.save(cart)
        loaded = store.get("test-1")
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.cart_id, "test-1")
        self.assertEqual(loaded.anime_name, "Test Anime")
        self.assertEqual(len(loaded.items), 1)

    def test_list_all(self) -> None:
        store = CartStore(self.path)
        store.save(Cart(cart_id="a", anime_name="A"))
        store.save(Cart(cart_id="b", anime_name="B"))
        carts = store.list_all()
        self.assertEqual(len(carts), 2)

    def test_delete(self) -> None:
        store = CartStore(self.path)
        store.save(Cart(cart_id="x"))
        self.assertTrue(store.delete("x"))
        self.assertIsNone(store.get("x"))
        self.assertFalse(store.delete("x"))

    def test_list_by_status(self) -> None:
        store = CartStore(self.path)
        store.save(Cart(cart_id="a", status="idle"))
        store.save(Cart(cart_id="b", status="downloading"))
        store.save(Cart(cart_id="c", status="done"))
        downloading = store.list_by_status("downloading")
        self.assertEqual(len(downloading), 1)
        self.assertEqual(downloading[0].cart_id, "b")


if __name__ == "__main__":
    unittest.main()
