#!/usr/bin/env python
"""YT-DLP Downloader CLI Interface"""

import logging
import subprocess
from pathlib import Path


class YTDLPError(Exception):
    """Base YT-DLP Exception"""


class YouTubeDLP:
    """YT-DLP Downloader CLI Interface"""

    def __init__(self, temp_directory: Path):
        self.log = logging.getLogger("TrailArr.YT-DLP")
        self.temp_directory = temp_directory
        # self.upgrade()

    def upgrade(self) -> None:
        """Upgrade YT-DLP"""
        self.log.info("Getting updates for YT-DLP")
        cmd = ["yt-dlp", "--update-to", "master"]
        try:
            result = subprocess.run(cmd, stdout=subprocess.PIPE, check=True)
            data = result.stdout.decode()
        except subprocess.CalledProcessError as e:
            raise YTDLPError("Failed to update YT-DLP") from e

        update_str = data.strip().split("\n")[-1]
        self.log.info("YT-DLP Update Status: '%s'", update_str)

    def test(self) -> bool:
        """Test YT-DLP connection"""
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
        """Download video from url, return downloaded file path"""
        self.log.info("Downloading video from %s", url)
        cmd = [
            "yt-dlp",
            "--quiet",
            "--no-simulate",
            "-N",
            "5",
            "-S",
            "res:1080",
            # "res:1080,codec:h264,hdr:SDR",
            "--remux-video",
            "mp4",
            "-O",
            "after_move:filepath",
            "-P",
            self.temp_directory,
            "-o",
            "%(id)s-%(epoch)s.%(ext)s",
            url,
        ]
        try:
            result = subprocess.run(cmd, check=True, capture_output=True)
            path_str = result.stdout.decode()
        except subprocess.CalledProcessError as e:
            raise YTDLPError(f"Failed to download {url}") from e

        return Path(path_str.strip()).resolve()
