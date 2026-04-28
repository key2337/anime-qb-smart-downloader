from __future__ import annotations

from loguru import logger

from aqsd.config import AppConfig
from aqsd.qbittorrent import QBittorrentClient
from aqsd.rss import inspect_rss


def _format_error(exc: Exception) -> str:
    return f"{exc.__class__.__name__}: {exc}"


def check_qb_connection(config: AppConfig) -> bool:
    client = QBittorrentClient(
        base_url=config.qb.base_url,
        username=config.qb.username,
        password=config.qb.password,
    )

    try:
        client.login()
        version = client.get_version()
    except Exception as exc:
        logger.error("qBittorrent check failed: {}", _format_error(exc))
        return False

    logger.info("qBittorrent OK: base_url={} version={}", config.qb.base_url, version)
    return True


def check_rss_connections(config: AppConfig) -> bool:
    ok = True

    enabled_sources = [source for source in config.rss_sources if source.enabled]
    if not enabled_sources:
        logger.warning("No enabled RSS sources found in config.")
        return True

    for source in enabled_sources:
        try:
            info = inspect_rss(source)
        except Exception as exc:
            logger.error("RSS check failed: source={} error={}", source.name, _format_error(exc))
            ok = False
            continue

        logger.info(
            "RSS OK: source={} status={} version={} entries={} title={}",
            info["name"],
            info["status_code"],
            info["feed_version"],
            info["entries"],
            info["feed_title"] or "-",
        )
        if info["bozo"]:
            logger.warning("RSS parse warning: source={} detail={}", info["name"], info["bozo_exception"])

    return ok


def check_connections(config: AppConfig) -> bool:
    qb_ok = check_qb_connection(config)
    rss_ok = check_rss_connections(config)
    return qb_ok and rss_ok
