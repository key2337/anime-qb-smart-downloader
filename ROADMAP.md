# Roadmap

## v0.1

- Establish the MVP CLI workflow
- Support YAML-based configuration
- Fetch RSS feeds and parse release metadata
- Match releases against anime rules and profiles
- Score candidates and submit the best match to qBittorrent
- Persist downloads and task state in SQLite
- Provide `--check`, `--dry-run`, and `--daemon` modes

## v0.2

- Implement real fallback switching for stalled or unhealthy torrents
- Track candidate retry history per episode
- Improve parser coverage for more release-title variants
- Add richer logging around matching and scoring decisions
- Expand automated tests for downloader, monitor, and database flows

## v0.3

- Add profile presets for common anime workflows
- Support better observability for task history and outcomes
- Improve configuration validation and error reporting
- Consider notification hooks for failures and fallback events
- Prepare packaging and release automation for wider distribution
