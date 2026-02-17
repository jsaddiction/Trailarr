"""YT-DLP Downloader CLI Interface."""

import json
import logging
import re
import subprocess
import sys
from pathlib import Path


class YTDLPError(Exception):
    """Base YT-DLP Exception"""


class YouTubeDLP:
    """YT-DLP Downloader CLI Interface."""

    def __init__(self, temp_directory: Path):
        self.log = logging.getLogger("TrailArr.YT-DLP")
        self.temp_directory = temp_directory
        self.upgrade()

    def upgrade(self) -> None:
        """Non-fatal self-update of yt-dlp to latest version via pip."""
        self.log.info("Checking for yt-dlp updates...")
        # Use pip to update to latest version (includes nightly fixes)
        # --break-system-packages is required in Alpine/Docker environments
        cmd = [sys.executable, "-m", "pip", "install", "-U", "--pre", "--break-system-packages", "yt-dlp"]
        try:
            result = subprocess.run(cmd, capture_output=True, timeout=60)
            stdout = result.stdout.decode().strip()
            stderr = result.stderr.decode().strip()

            if result.returncode == 0:
                # Check if it was already up to date or if it updated
                if "already satisfied" in stdout.lower() or "already up-to-date" in stdout.lower():
                    self.log.debug("yt-dlp is already up to date")
                else:
                    self.log.info("yt-dlp updated successfully")
            else:
                self.log.warning(
                    "yt-dlp update returned code %d: %s",
                    result.returncode, stderr or stdout,
                )
        except subprocess.TimeoutExpired:
            self.log.warning("yt-dlp update timed out after 60s, continuing with current version")
        except FileNotFoundError:
            self.log.warning("pip not found, skipping yt-dlp update")
        except OSError:
            self.log.exception("Unexpected error during yt-dlp update, continuing with current version")

    def test(self) -> bool:
        """Test YT-DLP connection."""
        cmd = ["yt-dlp", "--version"]
        try:
            result = subprocess.run(cmd, stdout=subprocess.PIPE, check=True, timeout=10)
            data = result.stdout.decode()
        except subprocess.CalledProcessError as e:
            self.log.critical("YT-DLP Test Failed: %s", e)
            return False
        except FileNotFoundError as e:
            self.log.critical("YT-DLP Not Found: %s", e)
            return False

        self.log.info("YT-DLP Version: %s", data.strip())
        return True

    def _is_apple_tv_url(self, url: str) -> bool:
        """Check if URL is an Apple TV HLS stream."""
        return "play-edge.itunes.apple.com" in url.lower() or "tv.apple.com" in url.lower()

    def _get_clean_audio_format(self, url: str, max_resolution: int) -> str | None:
        """
        Get explicit format string for Apple TV HLS that excludes audio description tracks.

        Audio description tracks have format IDs ending with underscore (e.g., "English_").
        Clean audio tracks have format IDs without underscore (e.g., "English").

        Returns format string like "12345+67890" or None if unable to determine.
        """
        try:
            # Get format list as JSON
            cmd = ["yt-dlp", "-J", "--no-warnings", url]
            result = subprocess.run(cmd, capture_output=True, timeout=30, check=True)
            data = json.loads(result.stdout.decode())

            formats = data.get("formats", [])

            # Find best video format up to max_resolution
            video_formats = [
                f for f in formats
                if f.get("vcodec") != "none"
                and f.get("height", 0) <= max_resolution
            ]
            best_video = max(video_formats, key=lambda f: (f.get("height", 0), f.get("tbr") or 0)) if video_formats else None

            # Find best audio format WITHOUT underscore in format_id (excludes audio description)
            # Prefer English, then highest bitrate
            # For Apple TV HLS, format IDs contain bitrate hints: stereo-160 > stereo-64 > stereo-32
            audio_formats = [
                f for f in formats
                if f.get("acodec") != "none"
                and f.get("vcodec") == "none"
                and not f.get("format_id", "").endswith("_")  # Exclude audio description tracks
                and f.get("language") == "en"  # Prefer English
            ]

            def audio_quality_key(f):
                """Extract quality score from format - prefer higher bitrate, more channels."""
                format_id = f.get("format_id", "")
                # Extract bitrate from format ID (e.g., "audio-stereo-160" -> 160)
                bitrate_match = re.search(r'-(\d+)$', format_id)
                bitrate = int(bitrate_match.group(1)) if bitrate_match else 0
                channels = f.get("audio_channels") or 2
                return (channels, bitrate)

            best_audio = max(audio_formats, key=audio_quality_key) if audio_formats else None

            if best_video and best_audio:
                format_str = f"{best_video['format_id']}+{best_audio['format_id']}"
                self.log.info("Selected Apple TV formats: video=%s audio=%s",
                             best_video['format_id'], best_audio['format_id'])
                return format_str

        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, json.JSONDecodeError,
                KeyError, ValueError, TypeError) as e:
            self.log.warning("Failed to determine clean audio format for Apple TV: %s", e)

        return None

    def download(self, url: str, max_resolution: int = 1080) -> Path:
        """Download video from url, return downloaded file path.

        Args:
            url: Video URL to download
            max_resolution: Maximum resolution (360, 480, 720, 1080, 2160)
        """
        self.log.info("Downloading video from %s (max resolution: %dp)", url, max_resolution)

        # For Apple TV HLS, explicitly select format to avoid audio description tracks
        format_selector = None
        if self._is_apple_tv_url(url):
            format_selector = self._get_clean_audio_format(url, max_resolution)

        cmd = ["yt-dlp", "--quiet", "--no-simulate", "-N", "5"]

        if format_selector:
            cmd.extend(["-f", format_selector])
        else:
            cmd.extend(["-S", f"res:{max_resolution},lang:en"])

        cmd.extend([
            "--remux-video", "mp4",
            "-O", "after_move:filepath",
            "-P", str(self.temp_directory),
            "-o", "%(id)s-%(epoch)s.%(ext)s",
            url,
        ])

        try:
            result = subprocess.run(cmd, check=True, capture_output=True, timeout=600)
            path_str = result.stdout.decode()
        except subprocess.CalledProcessError as e:
            raise YTDLPError(f"Failed to download {url}") from e
        except subprocess.TimeoutExpired as e:
            raise YTDLPError(f"Download timed out for {url}") from e

        return Path(path_str.strip()).resolve()
