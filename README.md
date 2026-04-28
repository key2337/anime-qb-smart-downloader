# anime-qb-smart-downloader

`anime-qb-smart-downloader` is a Python command-line tool for fetching anime releases from RSS feeds, parsing release metadata, matching entries against user rules, scoring candidates, and sending the best result to qBittorrent through its Web API.

The current codebase is an MVP with a working download pipeline, local SQLite persistence, a dry-run mode for rule tuning, and a basic monitoring layer for future fallback handling.

## Features

- Load runtime settings from a YAML config file
- Fetch and normalize RSS entries from one or more enabled sources
- Parse release metadata such as episode, season, group, resolution, subtitle type, source type, and revision markers
- Match releases against anime-specific rules and reusable profiles
- Score candidates by release-group preference, resolution, source, freshness, and seeder count
- Submit the highest-scoring candidate for each episode to qBittorrent
- Store downloaded episodes, candidate history, and task snapshots in SQLite
- Support connection checks, dry-run inspection, one-shot execution, and daemon mode

## Status

- The main RSS -> parse -> match -> score -> submit flow is implemented.
- SQLite persistence is implemented.
- Monitoring can flag suspicious downloads for fallback handling.
- Automatic fallback switching is not fully implemented yet.

## Requirements

- Python 3.11 or newer
- qBittorrent with Web UI enabled
- At least one reachable RSS feed

## Installation

Clone the repository and install it in a virtual environment:

```bash
python -m venv .venv
```

Windows PowerShell:

```powershell
.venv\Scripts\Activate.ps1
```

macOS/Linux:

```bash
source .venv/bin/activate
```

Install the project:

```bash
pip install -e .
```

## Configuration

Copy the example config and edit your local values:

```bash
cp config.example.yaml config.yaml
```

Windows PowerShell:

```powershell
Copy-Item config.example.yaml config.yaml
```

The local `config.yaml` is intentionally ignored by Git.

### Config sections

- `app`: database path, polling interval, log level
- `qbittorrent`: Web API endpoint, username, password, default category, default save path
- `rss_sources`: list of RSS feeds to poll
- `fallback_policy`: thresholds for suspicious download detection
- `profiles`: reusable matching and preference profiles
- `anime`: per-show rules, aliases, filters, preferred groups, and output settings

### qBittorrent settings

Before running the tool, enable qBittorrent Web UI:

1. Open qBittorrent.
2. Go to `Tools` -> `Options` -> `Web UI`.
3. Enable `Web User Interface (Remote control)`.
4. Set a host and port, for example `127.0.0.1:8080`.
5. Create a username and password.
6. Make sure the port is reachable from the machine running this tool.

Then reflect the same values in `config.yaml`:

```yaml
qbittorrent:
  base_url: "http://127.0.0.1:8080"
  username: "your-qb-user"
  password: "your-qb-password"
  default_category: "Anime"
  default_save_path: "/downloads/anime"
```

## Usage

After installing the package, the CLI entry point is `aqsd`.

### Run once

Fetch feeds once, select candidates, and submit matching downloads:

```bash
aqsd --config config.yaml
```

### Search candidates

Search RSS candidates by anime name without sending anything to qBittorrent:

```bash
aqsd search "Example Anime"
```

Filter by episode, resolution, group, subtitle type, and seeder threshold:

```bash
aqsd search "Example Anime" --episode 01 --resolution 1080p --group LoliHouse --subtitle embedded --min-seeders 5 --limit 10
```

Show only RAW / subtitle-free candidates:

```bash
aqsd search "Example Anime" --raw-only
```

### Download the best matching candidate

Search within the configured RSS sources, pick the highest-scoring candidate, and send it to qBittorrent:

```bash
aqsd download "Example Anime" --episode 01 --resolution 1080p --group LoliHouse --subtitle embedded
```

Use stricter seeder and RAW-only filters when needed:

```bash
aqsd download "Example Anime" --raw-only --min-seeders 5 --limit 10
```

The `download` command only searches within entries visible from your configured `rss_sources`. It does not query external indexers beyond those feeds.

### Dry-run mode

Inspect RSS entries, parsing, matching, and scoring without adding any torrent:

```bash
aqsd --config config.yaml --dry-run
```

Typical use cases:

- tune aliases and include/reject keywords
- compare score reasons for different release groups
- verify that only the expected episodes are being matched

### Connection check

Verify RSS access and qBittorrent Web API connectivity without downloading:

```bash
aqsd --config config.yaml --check
```

### Daemon mode

Run continuously using `app.interval_seconds` as the polling interval:

```bash
aqsd --config config.yaml --daemon
```

## Project Layout

```text
anime-qb-smart-downloader/
|-- .github/
|   `-- workflows/
|-- README.md
|-- ROADMAP.md
|-- config.example.yaml
|-- pyproject.toml
|-- src/
|   `-- aqsd/
|-- tests/
`-- data/
```

## Testing

Run the current test suite locally with either command:

```bash
python -m unittest discover -s tests -v
```

```bash
pytest
```

GitHub Actions runs `pytest` on every `push` and `pull_request`.

## Notes

- `data/app.db` is created automatically on first run.
- `config.example.yaml` is safe to commit and should not contain real credentials.
- `config.yaml` is for local use and should not be committed.
- The repository currently focuses on anime RSS workflows and qBittorrent integration, not on post-download media management.
- Adding a torrent to qBittorrent creates a download task record first. It is not treated as completed until the monitor sees the torrent finish.
- Current task states include `queued`, `submitted`, `downloading`, `stalled`, `fallback_pending`, `fallback_submitted`, `completed`, `failed`, and `cancelled`.
