"""Apple TV+ trailer provider implementation."""

import json
import logging

import requests
from bs4 import BeautifulSoup

from trailarr.models.download import TMDBVideo
from trailarr.providers.state import ProviderRunState, ProviderStateManager
from trailarr.providers.tmdb.api import TmdbApi
from .search import search_apple_tv


class AppleTVProvider:
    """
    Apple TV+ trailer provider using web search.

    Provides high-quality trailers (4K, Dolby Vision, h265) from Apple TV+.
    Uses 5-layer safety system to ensure correct movie identification.
    """

    name = "AppleTV"

    def __init__(
        self,
        tmdb_api: TmdbApi,
        run_state: ProviderRunState,
        state_manager: ProviderStateManager,
    ):
        """
        Initialize Apple TV provider.

        Args:
            tmdb_api: TMDB API instance (to fetch movie metadata for search)
            run_state: In-memory run state for tracking requests/errors
            state_manager: DB-backed state manager for rate limits
        """
        self.tmdb_api = tmdb_api
        self.run_state = run_state
        self.state_manager = state_manager
        self.log = logging.getLogger(f"TrailArr.Providers.{self.name}")

        # Configure session with shorter timeouts and connection limits
        # to avoid hanging on Apple TV servers
        from requests.adapters import HTTPAdapter
        from urllib3.util.retry import Retry

        self.session = requests.Session()

        # Configure retries and connection pooling
        retry_strategy = Retry(
            total=2,
            backoff_factor=0.5,
            status_forcelist=[429, 500, 502, 503, 504],
        )
        adapter = HTTPAdapter(
            max_retries=retry_strategy,
            pool_connections=1,  # Limit connection pool
            pool_maxsize=1,
        )
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)

        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Connection': 'close',  # Don't keep connections alive
        })

        # Cached authentication tokens and config from homepage
        self._utsk: str | None = None
        self._utscf: str | None = None
        self._caller: str = "web"
        self._locale: str = "en-US"
        self._pfm: str = "web"
        self._v: str | None = None

    def get_trailers(self, tmdb_id: int, imdb_id: str | None = None) -> list[TMDBVideo]:
        """
        Get trailers from Apple TV+.

        Args:
            tmdb_id: TMDB movie ID
            imdb_id: IMDb ID (unused, kept for protocol compatibility)

        Returns:
            List of TMDBVideo objects (may be empty if no match or errors)
        """
        # Step 1: Get movie metadata from TMDB (need title + year for search)
        movie_data = self.tmdb_api.get_movie(tmdb_id)

        if not movie_data:
            self.log.warning("Could not fetch movie metadata for TMDB ID %s", tmdb_id)
            return []

        title = movie_data.get("title") or movie_data.get("original_title")
        release_date = movie_data.get("release_date")  # Format: "YYYY-MM-DD"

        if not title or not release_date:
            self.log.warning("Missing title or year for TMDB ID %s", tmdb_id)
            return []

        try:
            year = int(release_date.split("-")[0])
        except (ValueError, IndexError):
            self.log.warning("Invalid release_date format for TMDB ID %s: %s", tmdb_id, release_date)
            return []

        self.log.debug("Searching Apple TV for: %s (%s)", title, year)

        # Step 2: Search Apple TV web page (5-layer safety system)
        result = search_apple_tv(title, year, log=self.log)

        if not result:
            self.log.debug("No Apple TV match for: %s (%s)", title, year)
            return []

        apple_id = result["id"]  # umc.cmc.xxxxx

        self.log.info("Found Apple TV match: %s (%s) - %s",
                     result["title"], result["year"], apple_id)

        # Step 3: Fetch trailers from Apple TV movie page
        trailers = self._get_trailers(apple_id)

        if not trailers:
            self.log.debug("No trailers found for Apple TV ID: %s", apple_id)
            return []

        # Step 4: Convert to TMDBVideo format (compatible with existing system)
        tmdb_videos = []
        for idx, trailer in enumerate(trailers, start=1):
            # Use trailer title if available, otherwise default naming
            trailer_name = trailer["title"] if trailer["title"] else f"{result['title']} - Trailer {idx}"

            tmdb_videos.append(TMDBVideo(
                tmdb_id=tmdb_id,
                iso_639_1="en",  # Apple TV is predominantly English
                iso_3166_1="US",
                name=trailer_name,
                type="Trailer",
                official=True,
                url=trailer["url"],
            ))

        self.log.info("Found %d trailer(s) on Apple TV for %s", len(tmdb_videos), result["title"])
        return tmdb_videos

    def _ensure_tokens(self) -> bool:
        """
        Extract utsk and utscf tokens from homepage if not cached.

        Returns:
            True if tokens available, False on failure
        """
        if self._utsk and self._utscf:
            return True  # Already have tokens

        try:
            resp = self.session.get("https://tv.apple.com/us", timeout=10)
        except requests.exceptions.Timeout as e:
            warning_msg = f"Apple TV homepage timeout: {e}"
            self.log.warning(warning_msg)
            self.run_state.warnings.append(warning_msg)
            return False
        except requests.exceptions.RequestException as e:
            warning_msg = f"Apple TV homepage request failed: {e}"
            self.log.warning(warning_msg)
            self.run_state.warnings.append(warning_msg)
            return False

        # Track request count
        self.run_state.request_count += 1

        # Handle authentication errors
        if resp.status_code in (401, 403):
            self.run_state.auth_failed = True
            error_msg = f"Apple TV homepage authentication failed ({resp.status_code})"
            self.run_state.errors.append(error_msg)
            self.log.error(error_msg)
            return False

        # Handle rate limiting
        if resp.status_code == 429:
            retry_after = resp.headers.get('Retry-After')
            warning_msg = f"Apple TV rate limited (retry after: {retry_after})"
            self.log.warning(warning_msg)
            self.run_state.warnings.append(warning_msg)
            self.state_manager.set_rate_limit(self.name, retry_after)
            return False

        # Handle 404 - not an error, just no data
        if resp.status_code == 404:
            self.log.debug("Apple TV homepage not found")
            return False

        # Handle server errors
        if resp.status_code >= 500:
            warning_msg = f"Apple TV server error ({resp.status_code})"
            self.log.warning(warning_msg)
            self.run_state.warnings.append(warning_msg)
            return False

        if resp.status_code != 200:
            warning_msg = f"Apple TV homepage returned {resp.status_code}: {resp.reason}"
            self.log.warning(warning_msg)
            self.run_state.warnings.append(warning_msg)
            return False

        # Parse homepage HTML
        try:
            soup = BeautifulSoup(resp.text, "html.parser")
            script = soup.find("script", id="serialized-server-data")

            if not script:
                self.log.warning("No config data on Apple TV homepage")
                return False

            data = json.loads(script.string)
            config_data = data["data"][0]["data"]

            # Get configuration parameters
            configure_params = config_data.get("configureParams", {})
            self._caller = configure_params.get("caller", "web")
            self._locale = configure_params.get("locale", "en-US")
            self._pfm = configure_params.get("pfm", "web")
            self._v = configure_params.get("v")

            # Tokens are in configuration.applicationProps.requiredParamsMap.Default
            config = config_data.get("configuration", {})
            app_props = config.get("applicationProps", {})
            params_map = app_props.get("requiredParamsMap", {})
            default_params = params_map.get("Default", {})

            self._utsk = default_params.get("utsk")
            self._utscf = default_params.get("utscf")

            if not self._utsk or not self._utscf:
                self.log.warning("Missing utsk or utscf in Apple TV config")
                return False

            self.log.debug("Successfully extracted Apple TV tokens")
            return True

        except (json.JSONDecodeError, KeyError, IndexError, TypeError) as e:
            self.log.exception("Failed to extract Apple TV tokens: %s", e)
            return False

    def _get_trailers(self, apple_id: str) -> list[dict]:
        """
        Fetch trailer data from Apple TV movie detail page.

        Instead of using the unreliable API endpoint, we fetch the movie detail
        page which contains embedded JSON with trailer information in the
        shelves structure.

        Args:
            apple_id: Apple content ID (e.g., umc.cmc.xxxxx)

        Returns:
            List of dicts with keys: title, url, external_id (empty list on failure)
        """
        # Fetch movie detail page using subprocess curl (requests library hangs)
        movie_url = f"https://tv.apple.com/us/movie/{apple_id}"
        self.log.debug("Fetching Apple TV movie page: %s", movie_url)

        try:
            import subprocess
            result = subprocess.run(
                ["curl", "-s", "-L", "-m", "10",
                 "-H", "User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15",
                 "-H", "Accept: text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                 "-H", "Accept-Language: en-US,en;q=0.9",
                 movie_url],
                capture_output=True,
                timeout=15,
                check=True
            )
            html_content = result.stdout.decode('utf-8')
            self.log.debug("Successfully fetched Apple TV page (%d bytes)", len(html_content))
        except subprocess.TimeoutExpired:
            warning_msg = f"Apple TV page timeout for {apple_id}"
            self.log.warning(warning_msg)
            self.run_state.warnings.append(warning_msg)
            return []
        except subprocess.CalledProcessError as e:
            warning_msg = f"Apple TV page request failed for {apple_id}: curl exit code {e.returncode}"
            self.log.warning(warning_msg)
            self.run_state.warnings.append(warning_msg)
            return []
        except FileNotFoundError:
            warning_msg = "curl not found - cannot fetch Apple TV pages"
            self.log.warning(warning_msg)
            self.run_state.warnings.append(warning_msg)
            return []
        except OSError as e:
            warning_msg = f"OS error fetching Apple TV page for {apple_id}: {e}"
            self.log.warning(warning_msg)
            self.run_state.warnings.append(warning_msg)
            return []

        # Track request count
        self.run_state.request_count += 1

        # Parse embedded JSON from movie detail page
        try:
            soup = BeautifulSoup(html_content, "html.parser")
            script = soup.find("script", id="serialized-server-data")

            if not script:
                self.log.warning("No embedded data on Apple TV movie page for %s", apple_id)
                return []

            data = json.loads(script.string)
            self.log.debug("Parsed JSON data structure with %d top-level entries", len(data.get("data", [])))

            # Navigate to shelves in content data (data[1].data.shelves)
            content_data = data.get("data", [])[1].get("data", {}) if len(data.get("data", [])) > 1 else {}
            shelves = content_data.get("shelves", [])
            self.log.debug("Found %d shelves in content data", len(shelves))

            # Collect ALL trailers (support both old and new JSON structures)
            trailers_found = []

            # Search shelves for trailer items
            for shelf in shelves:
                # Method 1: New structure - playlistItems (used by newer movies like Emancipation)
                playlist_items = shelf.get("playlistItems") or []
                for playlist_item in playlist_items:
                    playable = playlist_item.get("playable", {})
                    title = playable.get("title", "")
                    ext_id = playable.get("externalId", "")

                    # Filter to ONLY official trailers (externalId contains 'TRL')
                    if not ext_id or "TRL" not in ext_id.upper():
                        continue

                    assets = playable.get("assets", {})
                    if isinstance(assets, dict):
                        hls_url = assets.get("hlsUrl")
                        if hls_url:
                            trailers_found.append({
                                "title": title,
                                "url": hls_url,
                                "external_id": ext_id,
                            })
                            self.log.debug("Found Apple TV trailer (playlistItems): %s (%s)", title, ext_id)

                # Method 2: Old structure - items.playAction.contentDescriptor.items (used by older movies like Greyhound)
                items = shelf.get("items", [])
                for item in items:
                    # Check if this item contains a trailer
                    play_action = item.get("playAction", {})
                    if not play_action:
                        continue

                    content_desc = play_action.get("contentDescriptor", {})
                    desc_items = content_desc.get("items", [])

                    for desc_item in desc_items:
                        playable = desc_item.get("playable", {})
                        title = playable.get("title", "")
                        ext_id = playable.get("externalId", "")

                        # Filter to ONLY official trailers (externalId contains 'TRL')
                        # This excludes featurettes (FTTE), clips, etc.
                        if not ext_id or "TRL" not in ext_id.upper():
                            continue

                        assets = playable.get("assets", {})
                        if isinstance(assets, dict):
                            hls_url = assets.get("hlsUrl")
                            if hls_url:
                                trailers_found.append({
                                    "title": title,
                                    "url": hls_url,
                                    "external_id": ext_id,
                                })
                                self.log.debug("Found Apple TV trailer (items): %s (%s)", title, ext_id)

            if not trailers_found:
                self.log.warning("No trailers found in shelves for %s (checked %d shelves)", apple_id, len(shelves))

            return trailers_found

        except (json.JSONDecodeError, IndexError, KeyError) as e:
            warning_msg = f"Failed to parse Apple TV movie page for {apple_id}: {e}"
            self.log.warning(warning_msg)
            self.run_state.warnings.append(warning_msg)
            return []
        except (TypeError, AttributeError) as e:
            warning_msg = f"Unexpected error parsing Apple TV page for {apple_id}: {e}"
            self.log.warning(warning_msg)
            self.run_state.warnings.append(warning_msg)
            return []

    def test(self) -> bool:
        """
        Test Apple TV connectivity.

        Returns:
            True if homepage is accessible
        """
        try:
            resp = self.session.get("https://tv.apple.com/us", timeout=10)
            return resp.status_code == 200
        except requests.RequestException as e:
            self.log.exception("Apple TV test failed: %s", e)
            return False

    def close(self) -> None:
        """Close HTTP session."""
        if self.session is not None:
            self.session.close()
            self.session = None
