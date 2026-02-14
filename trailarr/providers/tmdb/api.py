"""TMDB API Connector."""

import logging

import requests

from trailarr.models.download import TMDBVideo

API_KEY = "28c936c57b653df80585b30667c1aa2d"
BASE_URL = "https://api.themoviedb.org/3/"
PAGE_URL = "https://www.themoviedb.org/movie/"
YOUTUBE_BASE_URL = "https://www.youtube.com/watch?v="
VIMEO_BASE_URL = "https://vimeo.com/"


class TmdbApi:
    """TMDB API interface — implements TrailerProvider protocol."""

    TIMEOUT = 5
    RETRIES = 3
    HEADERS = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Connection": "close",
    }

    def __init__(self, api_key: str = None) -> None:
        self.log = logging.getLogger("TrailArr.TMDB")
        self.session = requests.Session()
        self.session.headers.update(self.HEADERS)
        self.session.params = {"api_key": api_key if api_key else API_KEY}

    @property
    def name(self) -> str:
        return "TMDB"

    def _get(self, endpoint: str, timeout: int = None, params: dict = None) -> dict:
        tries_remaining = self.RETRIES
        time_out = timeout if timeout else self.TIMEOUT
        url = f"{BASE_URL}{endpoint}"

        while tries_remaining > 0:
            try:
                res = self.session.get(url=url, params=params, timeout=time_out)
                res.raise_for_status()
                return res.json()
            except requests.Timeout:
                tries_remaining -= 1
                if tries_remaining > 0:
                    self.log.warning(
                        "Request to %s timed out after %ss. Retrying %s more times.", url, time_out, tries_remaining
                    )
                    continue
            except requests.exceptions.RequestException as e:
                self.log.error("Failed to get %s. Error: %s", url, e)
                return {}

        self.log.error("Request to %s timed out after %ss. Retries exhausted.", url, time_out)
        return {}

    def _parse_videos(self, tmdb_id: int, video_data: dict) -> TMDBVideo | None:
        """Parse TMDB results into TMDBVideo. Returns None for unsupported sites."""
        site = video_data.get("site", "")
        key = video_data.get("key", "")

        if site == "YouTube" and key:
            url = f"{YOUTUBE_BASE_URL}{key}"
        elif site == "Vimeo" and key:
            url = f"{VIMEO_BASE_URL}{key}"
        else:
            self.log.debug("Skipping unsupported video site: %s (key: %s)", site, key)
            return None

        return TMDBVideo(
            tmdb_id=tmdb_id,
            iso_639_1=video_data.get("iso_639_1"),
            iso_3166_1=video_data.get("iso_3166_1"),
            name=video_data.get("name"),
            type=video_data.get("type"),
            official=video_data.get("official"),
            url=url,
        )

    def test(self) -> bool:
        """Test connection."""
        resp = self._get(endpoint="configuration")
        if not resp or "images" not in resp:
            return False
        self.log.info("Test Success.")
        return True

    def close(self) -> None:
        """Close the session."""
        if self.session:
            self.session.close()
            self.session = None

    def __del__(self) -> None:
        self.close()

    def _get_videos(self, movie_id: int) -> list[TMDBVideo]:
        """Get list of videos given a tmdb movie id."""
        endpoint = f"movie/{movie_id}/videos"
        res = self._get(endpoint=endpoint)
        videos = []

        if not res or "results" not in res:
            self.log.warning("No videos found for movie: %s", movie_id)
            return videos

        for video_data in res["results"]:
            if video := self._parse_videos(movie_id, video_data):
                videos.append(video)

        return videos

    def get_trailers(self, tmdb_id: int, imdb_id: str | None = None) -> list[TMDBVideo]:
        """Get list of trailers given a tmdb movie id."""
        self.log.debug("Getting trailers for movie: %s", tmdb_id)
        return [video for video in self._get_videos(tmdb_id) if video.type == "Trailer"]

    def get_page(self, movie_id: int) -> str:
        """Get TMDB page for movie."""
        return f"{PAGE_URL}{movie_id}/videos?active_nav_item=Trailers"
