"""IMDb trailer scraper — fallback when TMDB has no results."""

import logging
import re

import requests

from trailarr.models.download import TMDBVideo


class ImdbScraper:
    """Scrapes IMDb for trailer video pages that yt-dlp can handle."""

    TIMEOUT = 10
    IMDB_VIDEOS_URL = "https://www.imdb.com/title/{imdb_id}/videogallery/content_type-trailer/"
    MAX_TRAILERS = 5

    def __init__(self) -> None:
        self.log = logging.getLogger("TrailArr.IMDb")
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (compatible; Trailarr/1.0)",
            "Accept-Language": "en-US,en;q=0.9",
        })

    @property
    def name(self) -> str:
        return "IMDb"

    def get_trailers(self, tmdb_id: int, imdb_id: str | None = None) -> list[TMDBVideo]:
        """Extract trailer URLs from IMDb video gallery page."""
        if not imdb_id:
            self.log.debug("No IMDb ID provided for tmdb_id=%d, skipping", tmdb_id)
            return []

        url = self.IMDB_VIDEOS_URL.format(imdb_id=imdb_id)
        try:
            resp = self.session.get(url, timeout=self.TIMEOUT)
            resp.raise_for_status()
        except requests.RequestException as e:
            self.log.warning("Failed to fetch IMDb videos for %s: %s", imdb_id, e)
            return []

        # Extract /video/vi<digits> links from the page
        video_ids = re.findall(r'/video/(vi\d+)', resp.text)
        unique_ids = list(dict.fromkeys(video_ids))  # Deduplicate preserving order

        trailers: list[TMDBVideo] = []
        for vid in unique_ids[:self.MAX_TRAILERS]:
            video_url = f"https://www.imdb.com/video/{vid}/"
            trailers.append(TMDBVideo(
                tmdb_id=tmdb_id,
                iso_639_1="en",
                iso_3166_1="US",
                name=f"IMDb Trailer {vid}",
                type="Trailer",
                official=True,
                url=video_url,
            ))

        self.log.info("Found %d trailer URLs on IMDb for %s", len(trailers), imdb_id)
        return trailers

    def test(self) -> bool:
        """Test connection to IMDb."""
        try:
            resp = self.session.get("https://www.imdb.com/", timeout=self.TIMEOUT)
            return resp.status_code == 200
        except requests.RequestException:
            return False

    def close(self) -> None:
        """Close the session."""
        if self.session:
            self.session.close()
            self.session = None
