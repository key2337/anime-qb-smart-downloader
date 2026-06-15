"""Minimal Bencode parser for extracting info_hash from .torrent files."""

from __future__ import annotations

import hashlib
from typing import Any


def bencode_decode(data: bytes, offset: int = 0) -> tuple[Any, int]:
    """Decode a bencoded value starting at *offset*. Returns (value, next_offset)."""
    if offset >= len(data):
        raise ValueError("Unexpected end of bencoded data")
    ch = data[offset : offset + 1]
    if ch == b"i":
        return _decode_int(data, offset)
    if ch in b"0123456789":
        return _decode_str(data, offset)
    if ch == b"l":
        return _decode_list(data, offset)
    if ch == b"d":
        return _decode_dict(data, offset)
    raise ValueError(f"Unexpected byte at offset {offset}: {ch!r}")


def extract_info_hash(torrent_bytes: bytes) -> str:
    """Extract the SHA1 info_hash from a .torrent file.

    The info_hash is SHA1 of the bencoded 'info' dictionary — NOT of the
    decoded dict, so we locate the byte range of the 'info' value and hash
    that slice directly.
    """
    info_range = _find_info_value_range(torrent_bytes)
    if info_range is None:
        raise ValueError("No 'info' key found in torrent data")
    start, end = info_range
    return hashlib.sha1(torrent_bytes[start:end]).hexdigest()


def _find_info_value_range(data: bytes) -> tuple[int, int] | None:
    """Locate the byte range [start, end) of the 'info' dictionary value."""
    offset = 0
    while offset < len(data):
        if data[offset : offset + 1] != b"d":
            break
        offset += 1
        while offset < len(data) and data[offset : offset + 1] != b"e":
            key, offset = _decode_str(data, offset)
            if key == b"info":
                val_start = offset
                _, val_end = bencode_decode(data, offset)
                return val_start, val_end
            _, offset = bencode_decode(data, offset)
        offset += 1  # skip 'e'
    return None


def _decode_int(data: bytes, offset: int) -> tuple[int, int]:
    offset += 1  # skip 'i'
    end = data.index(b"e", offset)
    return int(data[offset:end]), end + 1


def _decode_str(data: bytes, offset: int) -> tuple[bytes, int]:
    colon = data.index(b":", offset)
    length = int(data[offset:colon])
    start = colon + 1
    end = start + length
    return data[start:end], end


def _decode_list(data: bytes, offset: int) -> tuple[list[Any], int]:
    offset += 1  # skip 'l'
    result: list[Any] = []
    while offset < len(data) and data[offset : offset + 1] != b"e":
        item, offset = bencode_decode(data, offset)
        result.append(item)
    return result, offset + 1


def _decode_dict(data: bytes, offset: int) -> tuple[dict[bytes, Any], int]:
    offset += 1  # skip 'd'
    result: dict[bytes, Any] = {}
    while offset < len(data) and data[offset : offset + 1] != b"e":
        key, offset = _decode_str(data, offset)
        val, offset = bencode_decode(data, offset)
        result[key] = val
    return result, offset + 1
