#!/usr/bin/env python
"""Video Models"""

from dataclasses import dataclass, field
from pathlib import Path

CODEC_WEIGHTS = {
    "mpeg4": 0.6,
    "h263": 0.6,
    "h264": 1.0,
    "h265": 1.5,
    "vp8": 0.9,
    "vp9": 1.3,
    "av1": 1.7,
}


@dataclass
class FileDetails:
    """Download History Model"""

    broken: bool = field(repr=False, compare=False)
    hash: str = field(repr=False, default=None, compare=True)
    path: Path = field(repr=True, default=None, compare=False)
    height: int = field(default=None)
    width: int = field(default=None)
    duration: int = field(default=None)
    frames: int = field(default=None)
    bitrate: int = field(default=None)
    codec_name: str = field(default=None)
    forced: bool = field(default=False)

    @property
    def frame_rate(self) -> float:
        """Calculate frame rate."""
        if self.frames and self.duration:
            return self.frames / self.duration

        return 0.0

    @property
    def total_pixels(self) -> int:
        """Calculate number of pixels."""
        if self.height and self.width and self.duration:
            return self.height * self.width * self.duration

        return 0

    @property
    def total_bits(self) -> int:
        """Calculate total bits."""
        if self.bitrate and self.duration:
            return self.bitrate * self.duration

        return 0

    @property
    def quality_score(self) -> float:
        """Calculate quality score. Based on Bits per Pixel."""
        if self.total_pixels and self.total_bits:
            codec_weight = CODEC_WEIGHTS.get(self.codec_name, 1.0)
            return (self.total_bits / self.total_pixels) * codec_weight

        return 0.0


@dataclass
class TMDBVideo:
    """TMDB Video"""

    tmdb_id: int = field(repr=False, compare=True)
    iso_639_1: str = field(repr=False, compare=False)
    iso_3166_1: str = field(repr=False, compare=False)
    name: str = field(repr=True, compare=False)
    type: str = field(repr=True, compare=False)
    official: bool = field(repr=False, compare=False)
    url: str = field(repr=True, compare=True)


@dataclass
class Download:
    """Yt-Download Model"""

    # TMDB Details
    tmdb: TMDBVideo = field(repr=False, default=None, compare=False)
    file: FileDetails = field(repr=False, default=None, compare=False)
