"""Download and video file models."""

from dataclasses import dataclass, field
from pathlib import Path

CODEC_WEIGHTS = {
    "mpeg4": 0.6,
    "h263": 0.6,
    "h264": 1.0,
    "hevc": 1.5,
    "vp8": 0.9,
    "vp9": 1.3,
    "av1": 1.7,
}


@dataclass
class FileDetails:
    """Video file metadata and quality metrics."""

    broken: bool = field(repr=False, compare=False)
    hash: str | None = field(repr=False, default=None, compare=True)
    path: Path | None = field(repr=True, default=None, compare=False)
    height: int | None = field(default=None)
    width: int | None = field(default=None)
    duration: float | None = field(default=None)
    frames: int | None = field(default=None)
    bitrate: int | None = field(default=None)
    codec_name: str | None = field(default=None)

    @property
    def frame_rate(self) -> float:
        """Calculate frame rate."""
        if self.frames is not None and self.duration is not None and self.duration > 0:
            return self.frames / self.duration
        return 0.0

    @property
    def total_pixels(self) -> float:
        """Calculate number of pixels."""
        if self.height is not None and self.width is not None and self.duration is not None and self.duration > 0:
            return self.height * self.width * self.duration
        return 0.0

    @property
    def total_bits(self) -> float:
        """Calculate total bits."""
        if self.bitrate is not None and self.duration is not None and self.duration > 0:
            return self.bitrate * self.duration
        return 0.0

    @property
    def quality_score(self) -> float:
        """Calculate quality score. Based on Bits per Pixel."""
        if self.total_pixels and self.total_bits:
            codec_weight = CODEC_WEIGHTS.get(self.codec_name.lower() if self.codec_name else None, 1.0)
            return (self.total_bits / self.total_pixels) * codec_weight
        return 0.0


@dataclass
class TMDBVideo:
    """Trailer source metadata."""

    tmdb_id: int = field(repr=False, compare=True)
    iso_639_1: str = field(repr=False, compare=False)
    iso_3166_1: str = field(repr=False, compare=False)
    name: str = field(repr=True, compare=False)
    type: str = field(repr=True, compare=False)
    official: bool = field(repr=False, compare=False)
    url: str = field(repr=True, compare=True)


@dataclass
class Download:
    """Download record combining source metadata with file details."""

    tmdb: TMDBVideo = field(repr=False, default=None, compare=False)
    file: FileDetails = field(repr=False, default=None, compare=False)
    retry_count: int = field(default=0, repr=False, compare=False)
    last_attempted: str | None = field(default=None, repr=False, compare=False)
    created_at: str | None = field(default=None, repr=False, compare=False)

    @property
    def selection_score(self) -> float:
        """
        Calculate selection score for choosing best trailer.

        Combines quality score with name-based filtering and source preferences
        to prefer clean official trailers over commentary/marketing versions
        while still respecting significant quality differences.

        Returns:
            Weighted score (higher is better, 0.0 if broken/invalid)
        """
        if not self.file or self.file.broken:
            return 0.0

        base_score = self.file.quality_score
        if base_score == 0.0:
            return 0.0

        # Start with base quality
        score = base_score

        # Apply name-based penalties/boosts
        if self.tmdb and self.tmdb.name:
            name_lower = self.tmdb.name.lower()

            # Heavy penalty for commentary/special features
            if "commentary" in name_lower or "with commentary" in name_lower:
                score *= 0.5

            # Penalty for marketing fluff
            if "watch now" in name_lower or "available now" in name_lower:
                score *= 0.85

            # Small boost for explicit "official" naming
            if "official" in name_lower:
                score *= 1.1

        return score
