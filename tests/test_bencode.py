from __future__ import annotations

import hashlib
import unittest

from aqsd.bencode import bencode_decode, extract_info_hash


class BencodeTests(unittest.TestCase):
    def test_decode_str(self):
        val, _ = bencode_decode(b"4:spam", 0)
        self.assertEqual(val, b"spam")

    def test_decode_int(self):
        val, _ = bencode_decode(b"i42e", 0)
        self.assertEqual(val, 42)

    def test_decode_list(self):
        val, _ = bencode_decode(b"l4:spami42ee", 0)
        self.assertEqual(val, [b"spam", 42])

    def test_decode_dict(self):
        val, _ = bencode_decode(b"d3:foo3:bar4:qwer4:quuxe", 0)
        self.assertEqual(val, {b"foo": b"bar", b"qwer": b"quux"})

    def test_extract_info_hash(self):
        info = b"d4:name12:test torrent6:lengthi123456ee"
        data = b"d4:info" + info + b"8:announce30:http://tracker.example.come"
        expected = hashlib.sha1(info).hexdigest()
        self.assertEqual(extract_info_hash(data), expected)

    def test_extract_info_hash_no_info(self):
        data = b"d8:announce30:http://tracker.example.come"
        with self.assertRaises(ValueError):
            extract_info_hash(data)


if __name__ == "__main__":
    unittest.main()
