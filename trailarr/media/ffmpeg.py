"""FFMpeg CLI module."""

import logging
import subprocess
import json
import hashlib
from pathlib import Path

from trailarr.models.download import FileDetails
from trailarr.media.exceptions import FfmpegError

FFPROBE_TIMEOUT = 30


class FfmpegAPI:
    """FFMpeg CLI interface."""

    def __init__(self) -> None:
        self.log = logging.getLogger("TrailArr.FFMpeg")

    @staticmethod
    def _calc_height(v_streams: list[dict]) -> int | None:
        """Calculate height given a list of video streams."""
        for stream in v_streams:
            if height := stream.get("height"):
                return int(height)
        return None

    @staticmethod
    def _calc_width(v_streams: list[dict]) -> int | None:
        """Calculate width given a list of video streams."""
        for stream in v_streams:
            if width := stream.get("width"):
                return int(width)
        return None

    @staticmethod
    def _calc_duration(format_details: dict, path: Path) -> float | None:
        """Calculate duration from format details, falling back to ffprobe."""
        if duration := format_details.get("duration"):
            try:
                return float(duration)
            except ValueError:
                pass

        # Fallback to calling ffprobe directly (avoids recursive instantiation)
        cmd = [
            "ffprobe", "-v", "fatal",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(path),
        ]
        try:
            result = subprocess.run(cmd, stdout=subprocess.PIPE, check=True, timeout=FFPROBE_TIMEOUT)
            return float(result.stdout)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, ValueError):
            return None

    @staticmethod
    def _calc_frames(v_streams: list[dict]) -> int | None:
        """Calculate frames given a list of video streams."""
        for stream in v_streams:
            if frames := stream.get("nb_frames"):
                return int(frames)
        return None

    @staticmethod
    def _calc_bitrate(format_details: dict) -> int | None:
        """Calculate bitrate given a list of video streams."""
        if bitrate := format_details.get("bit_rate"):
            try:
                return int(bitrate)
            except ValueError:
                pass
        return None

    def calc_hash(self, file: Path) -> str | None:
        """Calculate partial MD5 hash using first+middle+last 64KB chunks.

        This is ~25x faster than full hash for large files (500MB trailer: 1.5s → 0.06s).
        For files smaller than 192KB, falls back to full hash.

        Args:
            file: Path to file to hash

        Returns:
            MD5 hash hex string, or None if file doesn't exist
        """
        self.log.debug("Calculating hash for: %s", file)
        if not file or not file.exists():
            return None

        file_size = file.stat().st_size

        # Small files - hash entirely (fast enough)
        if file_size < 192 * 1024:  # Less than 192KB
            with open(file, "rb") as f:
                return hashlib.md5(f.read()).hexdigest()

        # Large files - hash first + middle + last 64KB chunks
        chunk_size = 64 * 1024
        with open(file, "rb") as f:
            # First 64KB
            first = f.read(chunk_size)

            # Middle 64KB
            f.seek(file_size // 2 - chunk_size // 2)
            middle = f.read(chunk_size)

            # Last 64KB
            f.seek(-chunk_size, 2)
            last = f.read(chunk_size)

        return hashlib.md5(first + middle + last).hexdigest()

    def _parse_video_details(self, video_details: dict, file_hash: str = None) -> FileDetails | None:
        """Parse ffprobe video details."""
        if "format" not in video_details:
            return None

        a_streams = [x for x in video_details.get("streams", []) if x.get("codec_type", "").lower() == "audio"]
        v_streams = [x for x in video_details.get("streams", []) if x.get("codec_type", "").lower() == "video"]
        format_details = video_details.get("format", {})

        file_path = Path(format_details.get("filename", "")).resolve()
        codec_name = v_streams[0].get("codec_name") if v_streams else None

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
            result = subprocess.run(cmd, stdout=subprocess.PIPE, check=True, timeout=FFPROBE_TIMEOUT)
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
        """Get video details."""
        self.log.debug("Getting video details for: %s", path)
        cmd = ["ffprobe", "-v", "fatal", "-print_format", "json", "-show_format", "-show_streams", "-show_error", str(path)]
        try:
            result = subprocess.run(cmd, stdout=subprocess.PIPE, check=True, timeout=FFPROBE_TIMEOUT)
            data = json.loads(result.stdout.decode())
        except subprocess.CalledProcessError as e:
            raise FfmpegError(f"Failed to get video details: Error: {e}") from e
        except (json.JSONDecodeError, subprocess.TimeoutExpired) as e:
            raise FfmpegError(f"Failed to parse video details: Error: {e}") from e

        return self._parse_video_details(data, file_hash)

    def get_duration(self, path: Path) -> float:
        """Get video duration."""
        self.log.debug("Getting duration for: %s", path)
        cmd = [
            "ffprobe", "-v", "fatal",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(path),
        ]
        try:
            result = subprocess.run(cmd, stdout=subprocess.PIPE, check=True, timeout=FFPROBE_TIMEOUT)
            return float(result.stdout)
        except subprocess.CalledProcessError as e:
            raise FfmpegError(f"Failed to get duration: Error: {e}") from e
        except (ValueError, subprocess.TimeoutExpired) as e:
            raise FfmpegError(f"Failed to get duration: Error: {e}") from e
