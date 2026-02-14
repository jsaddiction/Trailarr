# Trailarr

Automatically download and manage movie trailers for Radarr.

## Requirements

- Python 3.12+
- `requests` (pip)
- `yt-dlp` and `ffmpeg`/`ffprobe` (system tools, must be on PATH)
- Running Radarr instance

## How it Works

### Called from Radarr (webhook)

On download/upgrade/rename events:

1. Query all trailer providers (TMDB, IMDb) for available trailers
2. Deduplicate against previously downloaded URLs
3. Download new trailers, retry previously broken ones if eligible
4. Analyze video quality (resolution, codec, bitrate) via FFmpeg
5. Select the best quality trailer using codec-weighted scoring
6. Move selected trailer alongside the movie file
7. Optionally sync trailer path to Kodi via JSON-RPC
8. Clean up temp directory

### Called from CLI (cron job)

```bash
python trailarr_cli.py -all              # Process all movies in Radarr
python trailarr_cli.py -tmdb <ID>        # Process a specific movie by TMDB ID
python trailarr_cli.py -all -quiet       # Suppress console output
```

## Installation

See `installer/` for automated setup scripts (Alpine Linux / Docker).

## Configuration

Copy `settings.ini.example` to `settings.ini` and configure:

- `[LOGS]` — Log level
- `[KODI]` — Kodi JSON-RPC connection (optional)
