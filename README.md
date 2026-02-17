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
usage: Trailarr [-h] [-v] [-t ID] [-a] [-q] [--migrate]

options:
  -h, --help        Show this help message and exit
  -v, --version     Show version number
  -t ID, --tmdb ID  Process a specific movie by TMDB ID
  -a, --all         Process all movies in Radarr
  -q, --quiet       Suppress console output
  --migrate         Run pending data migrations
```

**Examples:**

```bash
# Process all movies (great for initial library setup)
docker exec radarr /config/scripts/Trailarr/trailarr_cli.py --all

# Process a single movie by TMDB ID
docker exec radarr /config/scripts/Trailarr/trailarr_cli.py --tmdb 550

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
