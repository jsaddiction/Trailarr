"""YT-DLP Downloader CLI Interface."""

import logging
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
        except Exception:
            self.log.exception("Unexpected error during yt-dlp update, continuing with current version")

    def test(self) -> bool:
        """Test YT-DLP connection."""
        cmd = ["yt-dlp", "--version"]
        try:
            result = subprocess.run(cmd, stdout=subprocess.PIPE, check=True)
            data = result.stdout.decode()
        except subprocess.CalledProcessError as e:
            self.log.critical("YT-DLP Test Failed: %s", e)
            return False
        except FileNotFoundError as e:
            self.log.critical("YT-DLP Not Found: %s", e)
            return False

        self.log.info("YT-DLP Version: %s", data.strip())
        return True

    def download(self, url: str) -> Path:
        """Download video from url, return downloaded file path."""
        self.log.info("Downloading video from %s", url)
        cmd = [
            "yt-dlp",
            "--quiet",
            "--no-simulate",
            "-N", "5",
            "-S", "res:1080",
            "--remux-video", "mp4",
            "-O", "after_move:filepath",
            "-P", str(self.temp_directory),
            "-o", "%(id)s-%(epoch)s.%(ext)s",
            url,
        ]
        try:
            result = subprocess.run(cmd, check=True, capture_output=True, timeout=600)
            path_str = result.stdout.decode()
        except subprocess.CalledProcessError as e:
            raise YTDLPError(f"Failed to download {url}") from e
        except subprocess.TimeoutExpired as e:
            raise YTDLPError(f"Download timed out for {url}") from e

        return Path(path_str.strip()).resolve()
