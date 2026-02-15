"""Media processing package."""

from trailarr.media.ffmpeg import FfmpegAPI
from trailarr.media.exceptions import FfmpegError

__all__ = ["FfmpegAPI", "FfmpegError"]
