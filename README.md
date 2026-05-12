# anime-qb-smart-downloader

`anime-qb-smart-downloader` is a Python command-line tool for fetching anime releases from RSS feeds, parsing release metadata, matching entries against user rules, scoring candidates, and sending the best result to qBittorrent through its Web API.

The current codebase is an MVP with a working download pipeline, local SQLite persistence, a dry-run mode for rule tuning, and a minimal automatic fallback flow for stalled downloads.

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
- Monitoring can flag suspicious downloads and submit the next stored fallback candidate.
- Fallback handling is intentionally minimal and is not a full retry state machine.

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
- `search_sources`: optional active search providers such as Nyaa and Torznab for manual search/download
- `fallback_policy`: thresholds for suspicious download detection
- `probe_policy`: optional short qBittorrent probe settings for manual candidate selection
- `title_aliases`: local multilingual title aliases for manual search and download
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

By default, the `download` command searches entries visible from your configured `rss_sources`. If active search sources are enabled, it can also query those sources.

### RSS, Nyaa, and Torznab search sources

`rss_sources` are best suited for ongoing subscriptions and automatic tracking. The automatic rule flow still only uses configured RSS feeds, so scheduled downloads remain predictable.

Manual `search` and `download` can also use active search sources. Nyaa and Torznab support can be enabled like this:

```yaml
search_sources:
  nyaa:
    enabled: true
    base_url: "https://nyaa.si"
    default_category: "1_2"
    timeout_seconds: 15
  torznab:
    enabled: false
    endpoints:
      - name: "jackett-nyaa"
        url: "http://127.0.0.1:9117/api/v2.0/indexers/nyaa/results/torznab/"
        api_key: "change-me"
        categories: []
        timeout_seconds: 15
```

When active search sources are enabled, manual `search` and `download` merge results from configured RSS feeds, Nyaa RSS search, and all enabled Torznab endpoints. The same parsing, title alias expansion, filtering, scoring, sorting, and duplicate removal are applied afterward.

RSS is generally better for following new releases from known feeds. Nyaa and Torznab are useful for active manual searches and backfilling older episodes. Torznab is intended for Jackett / Prowlarr and similar indexer aggregators; its actual coverage, categories, and result quality depend on the endpoints you configure. Nyaa and Torznab still depend on network reachability and current indexer results, and they do not guarantee that a result has active seeds.

### Multilingual title aliases

Manual `search` and `download` can expand a user query through local `title_aliases`. This lets Chinese, English, Japanese, and romanized names point to the same RSS title set.

Example:

```yaml
title_aliases:
  - canonical: "一拳超人"
    aliases:
      - "一拳超人"
      - "一击男"
      - "One Punch Man"
      - "One-Punch Man"
      - "Wanpanman"
      - "ワンパンマン"
```

With this config, searches for `一拳超人`, `One Punch Man`, `One-Punch Man`, or `ワンパンマン` can match RSS entries containing any alias in the group. Matching is case-insensitive and tolerant of common spacing / hyphen differences such as `One Punch Man` vs `One-Punch Man`.

This first version is local-only. It does not call external title databases, so aliases must be configured before they can be expanded. The automatic anime rule flow still uses the existing `anime.aliases` rules and is not changed by `title_aliases`.

Probe the top candidates in qBittorrent before choosing:

```bash
aqsd download "Example Anime" --episode 01 --probe
```

The probe flow temporarily adds the top candidates to qBittorrent, waits for `probe_policy.duration_seconds`, reads real qBittorrent state, and keeps the candidate with the best probe score. The score uses connected seeds, peers, download speed, availability, and progress delta.

`probe_policy` controls the probe behavior:

```yaml
probe_policy:
  enabled: false
  max_candidates: 3
  duration_seconds: 30
  min_speed_kbps: 50
  delete_losers: true
```

Important probe notes:

- Probe is a small trial download, not a zero-cost health check.
- `download --probe` enables probing for that manual command. Setting `probe_policy.enabled: true` also enables probing for manual `download`.
- Automatic one-shot and daemon downloads do not use probe by default.
- If qBittorrent rejects one probe candidate, the remaining candidates are still tested.
- If every probe add fails, the command falls back to the original highest-scoring candidate.
- If `delete_losers` is true, probe losers are deleted from qBittorrent with downloaded data.

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

### Minimal fallback switching

When daemon monitoring sees an active qBittorrent task with low speed, no seeds, or stalled progress, it marks the current task as `fallback_pending` and looks for the next `unused` row in `fallback_candidates`.

If a fallback candidate exists, the monitor marks that candidate as `used`, submits it to qBittorrent, marks the original task as `fallback_submitted`, and creates a new `download_tasks` row with status `submitted`. The new task inherits the original anime name, episode, selection mode, category, and save path, with `fallback_count` incremented by one.

If `fallback_policy.delete_failed_torrent` is `true` and the old task has a known qBittorrent hash, the monitor asks qBittorrent to delete the old torrent and downloaded files after the fallback is submitted. If no fallback candidate is available, the original task becomes `failed` with `last_error` set to `no fallback candidates available`.

Limitations:

- Fallback candidates come only from the pool saved when the original task was created.
- qBittorrent submission failures do not create a new successful task; the fallback candidate is marked `failed` and the original task keeps a failure reason.
- This is a minimal replacement loop, not a complex retry scheduler.

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
- A fallback candidate pool is stored for each task and the daemon can submit the next unused fallback candidate when monitoring marks the current task as suspicious.
