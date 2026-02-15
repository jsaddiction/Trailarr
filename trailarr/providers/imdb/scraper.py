"""IMDb trailer scraper — fallback when TMDB has no results."""

import logging
import re

import requests

from trailarr.models.download import TMDBVideo


class ImdbScraper:
    """Scrapes IMDb for trailer video pages that yt-dlp can handle."""

    TIMEOUT = 10
    IMDB_VIDEOS_URL = "https://www.imdb.com/title/{imdb_id}/videogallery/"
    MAX_TRAILERS = 5

    def __init__(self, run_state=None, state_manager=None) -> None:
        self.log = logging.getLogger("TrailArr.IMDb")
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        })
        self.run_state = run_state
        self.state_manager = state_manager

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
        except requests.Timeout as e:
            warning_msg = f"IMDb timeout for {imdb_id}: {e}"
            self.log.warning(warning_msg)
            if self.run_state:
                self.run_state.warnings.append(warning_msg)
            return []
        except requests.RequestException as e:
            warning_msg = f"IMDb request failed for {imdb_id}: {e}"
            self.log.warning(warning_msg)
            if self.run_state:
                self.run_state.warnings.append(warning_msg)
            return []

        # Track request count
        if self.run_state:
            self.run_state.request_count += 1

        # Handle non-200 responses
        if resp.status_code == 401 or resp.status_code == 403:
            error_msg = f"IMDb authentication failed ({resp.status_code}) for {imdb_id}"
            self.log.error(error_msg)
            if self.run_state:
                self.run_state.auth_failed = True
                self.run_state.errors.append(error_msg)
            return []

        if resp.status_code == 429:
            retry_after = resp.headers.get('Retry-After')
            warning_msg = f"IMDb rate limited for {imdb_id} (retry after: {retry_after})"
            self.log.warning(warning_msg)
            if self.run_state:
                self.run_state.warnings.append(warning_msg)
            if self.state_manager:
                self.state_manager.set_rate_limit('IMDb', retry_after)
            return []

        if resp.status_code == 404:
            self.log.debug("IMDb page not found for %s", imdb_id)
            return []

        if resp.status_code >= 500:
            warning_msg = f"IMDb server error ({resp.status_code}) for {imdb_id}"
            self.log.warning(warning_msg)
            if self.run_state:
                self.run_state.warnings.append(warning_msg)
            return []

        if resp.status_code != 200:
            warning_msg = f"IMDb returned {resp.status_code} for {imdb_id}: {resp.reason}"
            self.log.warning(warning_msg)
            if self.run_state:
                self.run_state.warnings.append(warning_msg)
            return []

        # Extract video IDs with their type labels from aria-label attributes
        # Pattern: aria-label="Trailer..." followed by href="/video/vi..."
        # We only want actual trailers, not teasers, clips, featurettes, interviews, etc.
        pattern = r'aria-label="(Trailer)([^"]*)"[^>]*?href="/video/(vi\d+)'
        matches = re.findall(pattern, resp.text, re.IGNORECASE)

        # Separate into official and non-official, filter out teasers
        official_trailers = []
        other_trailers = []
        seen_ids = set()

        for video_type, title_suffix, vid in matches:
            if vid in seen_ids:
                continue

            # Skip teasers
            if 'teaser' in title_suffix.lower():
                continue

            seen_ids.add(vid)
            video_url = f"https://www.imdb.com/video/{vid}/"
            video_name = f"{video_type.title()}{title_suffix.strip()}"

            trailer = TMDBVideo(
                tmdb_id=tmdb_id,
                iso_639_1="en",
                iso_3166_1="US",
                name=f"IMDb {video_name}",
                type="Trailer",
                official=True,
                url=video_url,
            )

            # Prioritize official trailers
            if 'official' in title_suffix.lower():
                official_trailers.append(trailer)
            else:
                other_trailers.append(trailer)

        # Return official trailers first, then others, up to MAX_TRAILERS
        trailers = (official_trailers + other_trailers)[:self.MAX_TRAILERS]

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
