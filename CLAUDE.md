# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Trailarr is a Python CLI tool that automatically downloads and manages movie trailers for Radarr. It fetches trailer metadata from multiple providers (TMDB and IMDb), downloads videos via yt-dlp, selects the best quality version using a codec-weighted scoring algorithm, places trailers alongside movie files, and optionally syncs trailer paths to Kodi media centers.

There is no web server, API, or frontend. It runs as either a Radarr custom script webhook or a manual CLI tool.

## Running the Application

```bash
# Webhook mode (triggered by Radarr with environment variables)
python trailarr.py

# CLI mode
python trailarr_cli.py -all              # Process all movies in Radarr
python trailarr_cli.py -tmdb <ID>        # Process a specific movie by TMDB ID
python trailarr_cli.py -all -quiet       # Suppress console output
```

## Dependencies

- **Python**: 3.12+ (uses `match`/`case`, `X | Y` type unions, `typing.Protocol`)
- **pip**: `pip install -r requirements.txt` (only `requests`)
- **System tools required**: `yt-dlp`, `ffmpeg`/`ffprobe` (must be on PATH)
- **Services**: Running Radarr instance, TMDB API access, optional Kodi

## Architecture

### Entry Points

- `trailarr.py` — Thin wrapper, imports `TrailArr` from `trailarr.app`. Routes Radarr webhook events (`ON_DOWNLOAD`, `ON_RENAME`, `ON_MOVIE_FILE_DELETE`, `ON_TEST`) parsed from environment variables.
- `trailarr_cli.py` — Thin wrapper, imports `main` from `trailarr.cli`.

### Processing Pipeline

`TrailArr.process_movie()` orchestrates per-movie processing:

1. `ProviderRegistry.get_all_trailers()` → query all providers (TMDB + IMDb), combine and deduplicate by URL
2. `DB.select_by_url()` → check against already-downloaded URLs, retry broken downloads if eligible
3. `YouTubeDLP.download()` → download new trailers to `temp/`
4. `FfmpegAPI.get_video_details()` → extract metadata (resolution, codec, bitrate, hash)
5. `DB.insert_download()` → persist trailer metadata
6. `_best_trailer()` → select winner: sort by `quality_score` descending
7. `_move_trailer()` → place as `{movie_stem}-trailer.{ext}` in movie directory
8. `KodiApi.set_trailer_path()` → update Kodi via JSON-RPC (if configured)

### Module Layout (`trailarr/`)

| Module | Class | Role |
|--------|-------|------|
| `app.py` | `TrailArr` | Main application class with processing pipeline |
| `cli.py` | `main()`, `CLIConfig` | CLI entry point and argument parsing |
| `logging.py` | `configure_logging()` | Logging setup (called explicitly, no side effects) |
| `config/parser.py` | `get_config()` | Reads `settings.ini` via `ConfigParser` |
| `config/models.py` | `Config` | Configuration dataclass |
| `models/movie.py` | `Movie` | Movie data model (includes `imdb_id`) |
| `models/download.py` | `FileDetails`, `TMDBVideo`, `Download` | Core data models with retry fields |
| `models/kodi.py` | `MovieDetails`, `Platform`, etc. | Kodi response models and enums |
| `db/database.py` | `DB` | Raw SQLite via `sqlite3` (no ORM), includes retry methods |
| `db/migrations.py` | `run_migrations()` | Lightweight version-table migration framework |
| `providers/base.py` | `TrailerProvider` | Protocol for trailer sources |
| `providers/registry.py` | `ProviderRegistry` | Combines results from all registered providers |
| `providers/tmdb/api.py` | `TmdbApi` | TMDB API client (3 retries on timeout) |
| `providers/imdb/scraper.py` | `ImdbScraper` | IMDb trailer scraper (regex-based, yt-dlp compatible) |
| `downloaders/ytdlp.py` | `YouTubeDLP` | Subprocess wrapper around `yt-dlp` CLI |
| `media/ffmpeg.py` | `FfmpegAPI` | Subprocess wrapper around `ffprobe`/`ffmpeg` |
| `media/exceptions.py` | `FfmpegError` | FFmpeg exception |
| `integrations/radarr/api.py` | `RadarrApi` | HTTP client for Radarr API v3 (auto-reads `/config/config.xml`) |
| `integrations/radarr/environment.py` | `RadarrEnvironment`, `Events` | Parses `Radarr_*` env vars into dataclass |
| `integrations/kodi/api.py` | `KodiApi` | JSON-RPC client for Kodi (optional auth, path mapping) |
| `integrations/kodi/exceptions.py` | `KodiAPIError` | Kodi exception |

### Provider System

Providers implement the `TrailerProvider` protocol and are registered with `ProviderRegistry`. All providers are queried for every movie, results are combined and deduplicated by URL. The quality selection happens downstream via FFmpeg analysis of the actual downloaded files — provider source doesn't affect scoring.

### Database

SQLite at `{project_root}/trailarr.db`, managed tables:

- **`downloads`** — trailer metadata with `UNIQUE(tmdb_id, url) ON CONFLICT REPLACE`. Includes retry columns (`retry_count`, `last_attempted`, `created_at`).
- **`kodi_trailer_cache`** — pending Kodi updates. Entries deleted after successful sync.
- **`schema_version`** — tracks applied migrations.

Schema evolution uses a lightweight migration framework (`db/migrations.py`) with `PRAGMA table_info` checks for idempotent column additions.

### Retry System

Failed downloads are marked `broken=True` with retry tracking. Retries are eligible when `retry_count < 5` and `last_attempted` is older than a jittered TTL (10 ± 3 days random per record). After 5 failed retries (~50-65 days), the download is permanently skipped.

### Quality Scoring

`FileDetails.quality_score = (total_bits / total_pixels) * codec_weight`

Codec weights: AV1 (1.7) > H.265 (1.5) > VP9 (1.3) > H.264 (1.0) > VP8 (0.9) > MPEG4/H.263 (0.6).

### Key Paths and Constants

Defined in `trailarr/__init__.py`:
- `ROOT_DIR` — project root (parent of `trailarr/`)
- `DB_FILE` — `{ROOT_DIR}/trailarr.db`
- `CONFIG_FILE` — `{ROOT_DIR}/settings.ini`
- `LOG_DIR` — `/config/logs` (Docker) or `{ROOT_DIR}/logs` (fallback)
- `TEMP_DIR` — `{ROOT_DIR}/temp`

### Configuration

`settings.ini` (see `settings.ini.example`):
- `[LOGS]` — `log_level`
- `[KODI]` — `kodi_name`, `kodi_ip`, `kodi_port`, `kodi_user`, `kodi_pass`, `kodi_notify`

### Error Handling Pattern

Custom exceptions: `YTDLPError`, `FfmpegError`, `KodiAPIError`. Failed downloads are marked `broken=True` with retry tracking. Kodi failures are cached for retry on next run. The app logs and continues rather than failing on individual movie errors.
