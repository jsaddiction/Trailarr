#!/usr/bin/env python
"""FFMpeg CLI module."""

import logging
import subprocess
import json
import hashlib
from pathlib import Path
from src import FileDetails, FfmpegError


class FfmpegAPI:
    """FFMpeg CLI interface."""

    def __init__(self) -> None:
        self.log = logging.getLogger("TrailArr.FFMpeg")

    @staticmethod
    def _calc_height(v_streams: list[dict]) -> int:
        """Calculate height given a list of video streams."""
        for stream in v_streams:
            if height := stream.get("height"):
                return int(height)
        return None

    @staticmethod
    def _calc_width(v_streams: list[dict]) -> int:
        """Calculate width given a list of video streams."""
        for stream in v_streams:
            if width := stream.get("width"):
                return int(width)

        return None

    @staticmethod
    def _calc_duration(format_details: dict, path: Path) -> float:
        """Calculate duration given a list of video streams."""
        # Get duration from format
        if duration := format_details.get("duration"):
            try:
                return float(duration)
            except ValueError:
                pass

        # Fallback to calling ffprobe again
        try:
            return FfmpegAPI().get_duration(path)
        except FfmpegError:
            return None

    @staticmethod
    def _calc_frames(v_streams: list[dict]) -> int:
        """Calculate frames given a list of video streams."""
        for stream in v_streams:
            if frames := stream.get("nb_frames"):
                return int(frames)

        return None

    @staticmethod
    def _calc_bitrate(format_details: dict) -> int:
        """Calculate bitrate given a list of video streams."""
        # Get bitrate from format
        if bitrate := format_details.get("bit_rate"):
            try:
                return int(bitrate)
            except ValueError:
                pass

        return None

    def calc_hash(self, file: Path) -> str:
        """Calculate hash of file."""
        self.log.debug("Calculating hash for: %s", file)
        if file and file.exists():
            with open(file, "rb") as f:
                return hashlib.md5(f.read()).hexdigest()
        return None

    def _parse_video_details(self, video_details: dict, file_hash: str = None) -> FileDetails:
        """Parse ffprobe video details."""
        if "format" not in video_details:
            return None

        # Parse streams
        a_streams = [x for x in video_details.get("streams", []) if x.get("codec_type", "").lower() == "audio"]
        v_streams = [x for x in video_details.get("streams", []) if x.get("codec_type", "").lower() == "video"]
        format_details = video_details.get("format", {})

        # Get file path and codec_name
        file_path = Path(format_details.get("filename", "")).resolve()
        codec_name = v_streams[0].get("codec_name") if v_streams else None

        # Build file details
        details = FileDetails(
            broken=not (a_streams and v_streams),
            path=file_path,
            height=self._calc_height(v_streams),
            width=self._calc_width(v_streams),
            duration=self._calc_duration(format_details, file_path),
            frames=self._calc_frames(v_streams),
            bitrate=self._calc_bitrate(format_details),
            codec_name=codec_name,
            hash=file_hash if file_hash else self.calc_hash(file_path),
        )

        return details

    def test(self) -> bool:
        """Test connection to ffmpeg."""
        cmd = ["ffprobe", "-version"]
        try:
            result = subprocess.run(cmd, stdout=subprocess.PIPE, check=True)
            data = result.stdout.decode()
        except subprocess.CalledProcessError as e:
            self.log.critical("FFMpeg Test Failed: %s", e)
            return False
        except FileNotFoundError as e:
            self.log.critical("FFMpeg Not Found: %s", e)
            return False

        version_str = data.replace("version", "|").replace("Copyright", "|").split("|")[1].strip()

        self.log.info("FFMpeg Version: %s", version_str)
        return True

    def get_video_details(self, path: Path, file_hash: str = None) -> FileDetails | None:
        """Get video details"""
        self.log.debug("Getting video details for: %s", path)
        cmd = ["ffprobe", "-v", "fatal", "-print_format", "json", "-show_format", "-show_streams", "-show_error", path]
        try:
            result = subprocess.run(cmd, stdout=subprocess.PIPE, check=True)
            data = json.loads(result.stdout.decode())
        except subprocess.CalledProcessError as e:
            raise FfmpegError(f"Failed to get video details: Error: {e}") from e

        return self._parse_video_details(data, file_hash)

    def get_duration(self, path: Path) -> float:
        """Get video duration."""
        self.log.debug("Getting duration for: %s", path)
        cmd = [
            "ffprobe",
            "-v",
            "fatal",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            path,
        ]
        try:
            result = subprocess.run(cmd, stdout=subprocess.PIPE, check=True)
            return float(result.stdout)
        except subprocess.CalledProcessError as e:
            raise FfmpegError(f"Failed to get duration: Error: {e}") from e
        except ValueError as e:
            raise FfmpegError(f"Failed to get duration: Error: {e}") from e
