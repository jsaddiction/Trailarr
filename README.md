# Trailarr

Automatically download and manage the best quality movie trailers for your Radarr library.

Trailarr searches multiple trailer providers, downloads the best available version, and places it alongside your movie files — ready for Plex, Jellyfin, Kodi, or any media player that supports local trailers.

## Features

- **Multi-provider search** — Queries TMDB, IMDb, and Apple TV for the widest selection of trailers
- **Quality-first selection** — Analyzes resolution, codec, and bitrate to pick the best trailer available (supports up to 4K)
- **Codec-aware scoring** — Prefers modern codecs (AV1 > H.265 > VP9 > H.264) at equivalent quality
- **Automatic upgrades** — Re-evaluates trailers on each run and upgrades when a better version is found
- **Radarr integration** — Runs as a Radarr custom script on download, upgrade, and rename events
- **CLI mode** — Process your entire library or a single movie on demand
- **Kodi sync** — Optionally updates Kodi with trailer paths via JSON-RPC
- **Smart caching** — Tracks downloaded trailers and provider queries to avoid redundant work
- **Resilient** — Retries broken downloads, handles rate limits, and continues past individual failures

## Quick Start

### 1. Install

Run inside your Radarr container (LinuxServer.io image):

```bash
curl -fsSL https://raw.githubusercontent.com/jsaddiction/Trailarr/main/installer/installer.sh | bash
```

This installs dependencies, clones the repo, and registers Trailarr as a Radarr custom script.

### 2. Configure (optional)

Copy the example config and edit as needed:

```bash
cp /config/scripts/Trailarr/settings.ini.example /config/scripts/Trailarr/settings.ini
```

```ini
[LOGS]
log_level: INFO

[TRAILERS]
# Maximum resolution (360, 480, 720, 1080, 2160)
max_resolution: 1080

[KODI]
kodi_name: Living Room
kodi_ip: 192.168.1.100
kodi_port: 8080
kodi_user:
kodi_pass:
kodi_notify: True
```

### 3. Use

Trailarr runs automatically when Radarr downloads, upgrades, or renames a movie. No action needed.

To process your existing library:

```bash
# Inside the Radarr container
/config/scripts/Trailarr/trailarr_cli.py --all
```

## CLI Usage

```
usage: Trailarr [-h] [-v] [-t ID] [-y KEY] [-a] [-f] [-q] [--migrate]

options:
  -h, --help        Show this help message and exit
  -v, --version     Show version number
  -t ID, --tmdb ID  Process a specific movie by TMDB ID (always forces)
  -y KEY, --youtube KEY
                    With --tmdb: use this YouTube video key or URL as the trailer
  -a, --all         Process all movies in Radarr
  -f, --force       Bypass caches, retry TTLs, and source blocks for this run
  -q, --quiet       Suppress console output
  --migrate         Run pending data migrations
```

A manual `--tmdb` run is treated as a deliberate "do this one now," so it
**always forces**: it bypasses the provider query cache, per-provider rate
limits and failure backoffs, the broken-URL retry TTL, and the 24h source
block, then re-discovers and re-attempts the movie. It will **not** replace a
trailer that is already correctly in place — force fills gaps, it does not
re-download good files. `--force` applies the same bypass to `--all` for a
deliberate full refresh. The Radarr-triggered path is never forced, so
automated imports stay throttled.

`--tmdb ID --youtube KEY` is the manual fallback for a movie whose provider
trailers are all dead or missing: find a trailer on YouTube yourself and pass
its key (or URL). Trailarr downloads it through the normal pipeline, puts it in
place, and updates Kodi. The pick is not pinned — if a provider later returns a
working trailer that scores higher, a normal run upgrades to it. TMDB's API is
read-only, so the run logs the movie's TMDB videos page for you to add the key
there and share it with other users.

**Examples:**

```bash
# Process all movies (great for initial library setup)
docker exec radarr /config/scripts/Trailarr/trailarr_cli.py --all

# Process a single movie by TMDB ID (forces past all caches/blocks)
docker exec radarr /config/scripts/Trailarr/trailarr_cli.py --tmdb 550

# Use a hand-picked YouTube video when the movie's provider trailers are dead
docker exec radarr /config/scripts/Trailarr/trailarr_cli.py --tmdb 949640 --youtube 80oxrgqa4pc

# Force a full re-discovery of the whole library (ignores all caches/TTLs)
docker exec radarr /config/scripts/Trailarr/trailarr_cli.py --all --force

# Quiet mode for cron jobs (logs still written to file)
docker exec radarr /config/scripts/Trailarr/trailarr_cli.py --all --quiet
```

## How It Works

For each movie, Trailarr:

1. Queries all trailer providers (TMDB, IMDb, Apple TV) and deduplicates results
2. Downloads new trailers via yt-dlp, retries previously broken ones if eligible
3. Analyzes each download with FFmpeg (resolution, codec, bitrate, frame rate)
4. Scores quality using a bits-per-pixel metric weighted by codec efficiency
5. Selects the best trailer and places it as `MovieName-trailer.mp4` in the movie directory
6. Optionally syncs the trailer path to Kodi

Logs are written to `/config/logs/Trailarr.txt` (visible in the Radarr UI under System > Logs > Files).

## Requirements

- [Radarr](https://radarr.video/) running in a [LinuxServer.io](https://docs.linuxserver.io/images/docker-radarr/) Docker container
- Python 3.12+ (included in the container)
- `yt-dlp`, `ffmpeg`, `ffprobe` (installed by the installer)

## License

MIT
