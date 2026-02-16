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

    def __init__(self, api_key: str = None, run_state=None, state_manager=None) -> None:
        self.log = logging.getLogger("TrailArr.TMDB")
        self.session = requests.Session()
        self.session.headers.update(self.HEADERS)
        self.session.params = {"api_key": api_key if api_key else API_KEY}
        self.run_state = run_state
        self.state_manager = state_manager

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

                # Track request count if run_state is available
                if self.run_state:
                    self.run_state.request_count += 1

                # Handle authentication errors
                if res.status_code in (401, 403):
                    error_msg = f"TMDB authentication failed ({res.status_code})"
                    self.log.error(error_msg)
                    if self.run_state:
                        self.run_state.auth_failed = True
                        self.run_state.errors.append(error_msg)
                    return {}

                # Handle rate limiting
                if res.status_code == 429:
                    retry_after = res.headers.get('Retry-After')
                    warning_msg = f"TMDB rate limited (retry after: {retry_after})"
                    self.log.warning(warning_msg)
                    if self.run_state:
                        self.run_state.warnings.append(warning_msg)
                    if self.state_manager:
                        self.state_manager.set_rate_limit('TMDB', retry_after)
                    return {}

                # Handle 404 - not an error, just no data
                if res.status_code == 404:
                    self.log.debug("Resource not found: %s", url)
                    return {}

                # Handle server errors
                if res.status_code >= 500:
                    warning_msg = f"TMDB server error ({res.status_code}) for {url}"
                    self.log.warning(warning_msg)
                    if self.run_state:
                        self.run_state.warnings.append(warning_msg)
                    return {}

                # Raise for other HTTP errors
                res.raise_for_status()
                return res.json()

            except requests.Timeout:
                tries_remaining -= 1
                if tries_remaining > 0:
                    self.log.debug(
                        "Request to %s timed out after %ss. Retrying %s more times.", url, time_out, tries_remaining
                    )
                    continue
                else:
                    warning_msg = f"TMDB timeout after {time_out}s (retries exhausted)"
                    self.log.warning(warning_msg)
                    if self.run_state:
                        self.run_state.warnings.append(warning_msg)
            except requests.exceptions.RequestException as e:
                warning_msg = f"TMDB request failed: {e}"
                self.log.warning(warning_msg)
                if self.run_state:
                    self.run_state.warnings.append(warning_msg)
                return {}

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

    def get_movie(self, movie_id: int) -> dict:
        """
        Get movie details from TMDB.

        Returns dict with keys: title, original_title, release_date, etc.
        Returns empty dict on failure.
        """
        endpoint = f"movie/{movie_id}"
        return self._get(endpoint=endpoint)

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
        """Get list of trailers given a tmdb movie id.

        Filters to only 'Trailer' type (excludes Teaser, Featurette, Clip, etc.)
        and prioritizes official trailers with "Official" in the name.
        """
        self.log.debug("Getting trailers for movie: %s", tmdb_id)

        # Filter to only trailers (excludes teasers, featurettes, clips, etc.)
        trailers = [video for video in self._get_videos(tmdb_id) if video.type == "Trailer"]

        # Prioritize trailers with "Official" in the name
        official_named = [t for t in trailers if t.name and 'official' in t.name.lower()]
        other_trailers = [t for t in trailers if t.name and 'official' not in t.name.lower()]

        # Return official-named first, then others
        return official_named + other_trailers

    def get_page(self, movie_id: int) -> str:
        """Get TMDB page for movie."""
        return f"{PAGE_URL}{movie_id}/videos?active_nav_item=Trailers"
