# anime-qb-smart-downloader

`anime-qb-smart-downloader` is a Python MVP for pulling anime releases from RSS,
filtering and scoring candidates with user-defined rules, and pushing the best
match into qBittorrent through the Web API.

## Features

- Load all runtime settings from `config.yaml`
- Fetch RSS feeds and normalize entries into a candidate pool
- Parse title metadata such as group, episode, resolution, subtitle type, and
  revision markers
- Match releases against anime rules and profile constraints
- Score candidates by seeders, freshness, preferred groups, and quality hints
- Add the highest-scoring candidate for each episode to qBittorrent
- Persist downloaded episodes, candidate history, and active task records in
  SQLite
- Reserve monitoring and fallback task state for the next phase

## Project Layout

```text
anime-qb-smart-downloader/
├─ README.md
├─ pyproject.toml
├─ config.example.yaml
├─ config.yaml
├─ data/
│  └─ app.db
├─ src/
│  └─ aqsd/
│     ├─ __init__.py
│     ├─ main.py
│     ├─ config.py
│     ├─ models.py
│     ├─ rss.py
│     ├─ parser.py
│     ├─ matcher.py
│     ├─ scorer.py
│     ├─ database.py
│     ├─ qbittorrent.py
│     ├─ downloader.py
│     ├─ monitor.py
│     └─ utils.py
└─ tests/
   ├─ test_parser.py
   ├─ test_matcher.py
   └─ test_scorer.py
```

## Quick Start

1. Create and activate a Python 3.11+ virtual environment.
2. Install the package:

   ```bash
   pip install -e .
   ```

3. Edit `config.yaml` with your RSS and qBittorrent settings.
4. Run once:

   ```bash
   aqsd --config config.yaml
   ```

5. Run in daemon mode:

   ```bash
   aqsd --config config.yaml --daemon
   ```

6. Verify RSS and qBittorrent connectivity without adding downloads:

   ```bash
   aqsd --config config.yaml --check
   ```

## Notes

- `config.yaml` is a working copy of `config.example.yaml`.
- `data/app.db` is created and migrated automatically on first run.
- Full fallback switching is not implemented yet; the task schema and monitor
  hooks are already in place for the second phase.

## Testing

```bash
python -m unittest discover -s tests -v
```
