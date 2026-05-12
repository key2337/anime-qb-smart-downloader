from __future__ import annotations

from email.utils import parsedate_to_datetime
from urllib.parse import urlencode
from xml.etree import ElementTree

import requests

from aqsd.config import TorznabEndpointSettings
from aqsd.models import Candidate
from aqsd.rss import USER_AGENT


TORZNAB_NS = "{http://torznab.com/schemas/2015/feed}"


def build_torznab_search_url(endpoint: TorznabEndpointSettings, query: str) -> str:
    base_url = endpoint.url.rstrip("/")
    params = {
        "t": "search",
        "q": query,
        "apikey": endpoint.api_key,
    }
    if endpoint.categories:
        params["cat"] = ",".join(endpoint.categories)
    return f"{base_url}/?{urlencode(params)}"


def fetch_torznab_candidates(
    endpoint: TorznabEndpointSettings,
    query: str,
    *,
    limit: int | None = None,
) -> list[Candidate]:
    url = build_torznab_search_url(endpoint, query)
    response = requests.get(
        url,
        headers={"User-Agent": USER_AGENT},
        timeout=endpoint.timeout_seconds,
    )
    response.raise_for_status()
    return parse_torznab_xml(response.content, source_name=endpoint.name, limit=limit)


def parse_torznab_xml(content: bytes | str, *, source_name: str = "torznab", limit: int | None = None) -> list[Candidate]:
    root = ElementTree.fromstring(content)
    candidates: list[Candidate] = []

    for item in root.findall(".//item"):
        title = _text(item, "title")
        attrs = _torznab_attrs(item)
        url = _candidate_url(item, attrs)
        if not title or not url:
            continue

        candidates.append(
            Candidate(
                title=title,
                url=url,
                source=source_name,
                info_hash=_first_attr(attrs, "infohash", "info_hash", "hash"),
                published_at=_parse_pub_date(_text(item, "pubDate")),
                seeders=_int_attr(attrs, "seeders", "seeds"),
            )
        )
        if limit is not None and len(candidates) >= limit:
            break

    return candidates


def _text(item: ElementTree.Element, name: str) -> str:
    child = item.find(name)
    if child is None or child.text is None:
        return ""
    return child.text.strip()


def _torznab_attrs(item: ElementTree.Element) -> dict[str, str]:
    attrs: dict[str, str] = {}
    for attr in item.findall(f"{TORZNAB_NS}attr"):
        name = (attr.attrib.get("name") or "").strip().casefold()
        value = (attr.attrib.get("value") or "").strip()
        if name and value:
            attrs[name] = value
    return attrs


def _candidate_url(item: ElementTree.Element, attrs: dict[str, str]) -> str:
    for name in ("magneturl", "magnet", "downloadurl", "download"):
        value = attrs.get(name)
        if value:
            return value

    enclosure = item.find("enclosure")
    if enclosure is not None:
        enclosure_url = (enclosure.attrib.get("url") or "").strip()
        if enclosure_url:
            return enclosure_url

    link = _text(item, "link")
    if link:
        return link
    return _text(item, "guid")


def _first_attr(attrs: dict[str, str], *names: str) -> str | None:
    for name in names:
        value = attrs.get(name.casefold())
        if value:
            return value
    return None


def _int_attr(attrs: dict[str, str], *names: str) -> int:
    value = _first_attr(attrs, *names)
    if value is None:
        return 0
    try:
        return int(value)
    except ValueError:
        return 0


def _parse_pub_date(value: str):
    if not value:
        return None
    try:
        return parsedate_to_datetime(value)
    except (TypeError, ValueError, IndexError):
        return None
