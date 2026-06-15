from __future__ import annotations

import json
import threading
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from aqsd.models import Cart, CartEvent, CartItem


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _cart_from_dict(data: dict[str, Any]) -> Cart:
    items = [CartItem(**item) for item in data.get("items", [])]
    events = [CartEvent(**event) for event in data.get("events", [])]
    return Cart(
        cart_id=data.get("cart_id", ""),
        anime_name=data.get("anime_name", ""),
        episode=data.get("episode", ""),
        items=items,
        tried_hashes=data.get("tried_hashes", []),
        active_hash=data.get("active_hash"),
        active_title=data.get("active_title"),
        fallback_count=data.get("fallback_count", 0),
        max_fallbacks=data.get("max_fallbacks", 3),
        status=data.get("status", "idle"),
        events=events,
        created_at=data.get("created_at", ""),
        probe_duration_seconds=data.get("probe_duration_seconds", 20),
    )


def _cart_to_dict(cart: Cart) -> dict[str, Any]:
    return asdict(cart)


class CartStore:
    def __init__(self, file_path: str | Path) -> None:
        self._file_path = Path(file_path)
        self._lock = threading.Lock()

    def _load(self) -> dict[str, Cart]:
        if not self._file_path.exists():
            return {}
        try:
            raw = json.loads(self._file_path.read_text(encoding="utf-8"))
            carts = [_cart_from_dict(item) for item in raw.get("carts", [])]
            return {cart.cart_id: cart for cart in carts}
        except (json.JSONDecodeError, OSError):
            return {}

    def _save(self, carts: dict[str, Cart]) -> None:
        self._file_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"carts": [_cart_to_dict(cart) for cart in carts.values()]}
        self._file_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def get(self, cart_id: str) -> Cart | None:
        with self._lock:
            carts = self._load()
            return carts.get(cart_id)

    def list_all(self) -> list[Cart]:
        with self._lock:
            carts = self._load()
            return list(carts.values())

    def save(self, cart: Cart) -> None:
        with self._lock:
            carts = self._load()
            carts[cart.cart_id] = cart
            self._save(carts)

    def delete(self, cart_id: str) -> bool:
        with self._lock:
            carts = self._load()
            if cart_id not in carts:
                return False
            del carts[cart_id]
            self._save(carts)
            return True

    def list_by_status(self, *statuses: str) -> list[Cart]:
        with self._lock:
            carts = self._load()
            return [cart for cart in carts.values() if cart.status in statuses]
