"""Main TrailArr application class."""

import sys
import shutil
import logging
from pathlib import Path

from trailarr import DB_FILE, TEMP_DIR, VIDEO_EXTENSIONS, CONFIG_FILE
from trailarr.config import get_config
from trailarr.logging import configure_logging
from trailarr.models.movie import Movie
from trailarr.models.download import Download, TMDBVideo, FileDetails
from trailarr.db import DB
from trailarr.integrations.radarr import RadarrApi, RadarrEnvironment, Events
from trailarr.downloaders import YouTubeDLP, YTDLPError
from trailarr.media import FfmpegAPI, FfmpegError
from trailarr.integrations.kodi import KodiApi
from trailarr.providers import ProviderRegistry
from trailarr.providers.tmdb import TmdbApi
from trailarr.providers.imdb import ImdbScraper
from trailarr.providers.appletv import AppleTVProvider
from trailarr.providers.state import ProviderStateManager, ProviderRunState
from trailarr.stats import RunStats


class TrailArr:
    """TrailArr Main Class."""

    def __init__(self):
        self.cfg = get_config(CONFIG_FILE)
        configure_logging(self.cfg)

        self.log = logging.getLogger("TrailArr")
        self.env = RadarrEnvironment()
        self.db = DB(DB_FILE)
        self.ytdlp = YouTubeDLP(TEMP_DIR)
        self.ffmpeg = FfmpegAPI()
        self.radarr = RadarrApi()
        self.kodi = KodiApi(self.cfg.kodi_name, self.cfg.kodi_ip, self.cfg.kodi_port, self.cfg.kodi_user, self.cfg.kodi_pass)

        # Initialize provider state management
        self.state_manager = ProviderStateManager(self.db.conn)
        self.run_stats = RunStats()
        self.run_stats.provider_states = {
            'TMDB': ProviderRunState(provider_name='TMDB'),
            'IMDb': ProviderRunState(provider_name='IMDb'),
            'AppleTV': ProviderRunState(provider_name='AppleTV'),
        }

        # Provider registry — queries all providers and combines results
        self.providers = ProviderRegistry(
            state_manager=self.state_manager,
            run_states=self.run_stats.provider_states
        )
        tmdb_api = TmdbApi(
            run_state=self.run_stats.provider_states['TMDB'],
            state_manager=self.state_manager
        )
        self.providers.register(tmdb_api)
        self.providers.register(ImdbScraper(
            run_state=self.run_stats.provider_states['IMDb'],
            state_manager=self.state_manager
        ))
        self.providers.register(AppleTVProvider(
            tmdb_api=tmdb_api,
            run_state=self.run_stats.provider_states['AppleTV'],
            state_manager=self.state_manager
        ))

        # Run migrations (all dependencies initialized above)
        from trailarr.db.migrations import run_migrations
        run_migrations(self.db.conn, radarr_api=self.radarr, ffmpeg_api=self.ffmpeg)

        # Clean stale temp files from any previous interrupted runs
        self._cleanup_temp_folder()

    @property
    def has_write_permission(self) -> bool:
        """Check if the temp folder has write permission."""
        if not TEMP_DIR.is_dir():
            return False
        try:
            test_file = TEMP_DIR / "test.txt"
            test_file.touch()
            test_file.unlink()
        except OSError:
            return False
        self.log.info("Test Success. Write Permission to %s", TEMP_DIR)
        return True

    def exit(self, error: str | None = None) -> None:
        """Exit the program with an error message."""
        self.db.close()
        self.providers.close()
        self._cleanup_temp_folder()
        if error:
            self.log.critical("Exited with Error: %s", error)
            sys.exit(1)

        self.log.info("Completed Successfully")
        sys.exit(0)

    def test(self):
        """Run tests for TrailArr."""
        if not self.has_write_permission:
            self.exit(f"No Write Permission to Temp Folder {TEMP_DIR}. Exiting.")

        if not self.db.test():
            self.exit("Database Test Failed. Exiting.")

        if not self.ytdlp.test():
            self.exit("YouTubeDLP Test Failed. Exiting.")

        if not self.ffmpeg.test():
            self.exit("FFmpeg Test Failed. Exiting.")

        if not self.radarr.test():
            self.exit("Radarr API Test Failed. Exiting.")

    def _move_trailer(self, file: FileDetails, movie: Movie) -> Path | None:
        """Move trailer to movie directory."""
        if not file.path.exists():
            self.log.warning("Trailer file does not exist: %s", file.path)
            return None
        if not movie.directory.exists():
            self.log.warning("Movie directory does not exist: %s", movie.directory)
            return None
        if not movie.file_path.exists():
            self.log.warning("Movie file does not exist: %s", movie.file_path)
            return None

        file_name = f"{Path(movie.file_path).stem}-trailer{file.path.suffix}"
        trailer_path = Path(movie.directory, file_name)
        self.log.info("Moving trailer to %s", trailer_path)
        shutil.move(str(file.path), str(trailer_path))
        return trailer_path

    def _delete_old_trailer(self, file: FileDetails) -> None:
        """Delete old trailer file."""
        if file and file.path.exists():
            self.log.info("Deleting Old Trailer: %s", file.path)
            file.path.unlink()

    def _cleanup_temp_folder(self) -> None:
        """Cleanup the temp folder."""
        if not TEMP_DIR.is_dir():
            return
        self.log.debug("Cleaning up Temp Folder")
        for file in TEMP_DIR.iterdir():
            if not file.is_file():
                continue
            self.log.debug("Deleting: %s", file)
            file.unlink()
        self.log.debug("Temp Folder Cleaned")

    def _remove_unused_trailers(self, tmdb_id: int) -> None:
        """Remove unused trailers from the database."""
        self.log.info("Removing unused trailers for tmdbid %s", tmdb_id)
        self.db.delete_by_tmdb_id(tmdb_id)

    def _get_local_trailer(self, movie: Movie) -> FileDetails | None:
        """Get local file details."""
        self.log.debug("Checking for local trailers in %s", movie.directory)
        local_trailers: list[Path] = []
        if not movie.file_path.exists():
            self.log.warning("Movie file does not exist: %s", movie.file_path)
            return None

        for item in movie.directory.iterdir():
            if item.is_dir():
                continue
            if item == movie.file_path:
                continue
            if item.suffix in VIDEO_EXTENSIONS and "-trailer" in item.name.lower():
                local_trailers.append(item)

        if len(local_trailers) > 1:
            trailer_list = ", ".join([x.name for x in local_trailers])
            self.log.warning("Found more than one trailer file in %s : [%s]", movie.directory, trailer_list)
            return None

        if not local_trailers:
            self.log.info("No local trailers found in %s", movie.directory)
            return None

        local_trailer = local_trailers[0]
        self.log.info("Found Local Trailer: %s", local_trailer.name)
        file_hash = self.ffmpeg.calc_hash(local_trailer)
        if dl := self.db.select_by_hash(file_hash):
            self.log.debug("%s was downloaded previously.", local_trailer.name)
            dl.file.path = local_trailer
            return dl.file

        try:
            return self.ffmpeg.get_video_details(local_trailer, file_hash)
        except FfmpegError as e:
            self.log.error("Failed to get details for %s. Error: %s", local_trailers[0], e)
            return None

    def _download_trailer(self, tmdb_data: TMDBVideo) -> Download | None:
        """Download a trailer into the temp folder."""
        try:
            trailer_path = self.ytdlp.download(tmdb_data.url, max_resolution=self.cfg.max_resolution)
        except YTDLPError as e:
            self.log.error("Failed to download %s. Error: %s", tmdb_data.url, e)
            return Download(tmdb=tmdb_data, file=FileDetails(broken=True))

        try:
            trailer_file = self.ffmpeg.get_video_details(trailer_path)
        except FfmpegError as e:
            self.log.error("Failed to get details for %s. Error: %s", trailer_path, e)
            return Download(tmdb=tmdb_data, file=FileDetails(broken=True))

        return Download(tmdb=tmdb_data, file=trailer_file)

    def _get_new_trailers(self, movie: Movie) -> list[Download]:
        """Download trailers not in db and return list of Downloads."""
        self.log.debug("Getting new trailers for %s", movie)
        downloads: list[Download] = []

        # Query providers - registry checks per-provider TTL internally
        # Returns trailers and set of providers that succeeded
        all_trailers, providers_succeeded = self.providers.get_all_trailers(
            movie.tmdb_id,
            imdb_id=movie.imdb_id,
            db=self.db
        )

        # Download and insert new trailers
        for tmdb_trailer in all_trailers:
            # Skip empty URLs
            if not tmdb_trailer.url:
                continue

            existing = self.db.select_by_url(tmdb_trailer.url)

            if existing:
                if existing.file.broken and self.db.is_retryable(existing):
                    # Broken but eligible for retry
                    self.log.info(
                        "Retrying broken download: %s (attempt %d)",
                        tmdb_trailer.url, existing.retry_count + 1,
                    )
                    dl = self._download_trailer(tmdb_trailer)
                    if dl.file.broken:
                        self.db.mark_broken(tmdb_trailer.tmdb_id, tmdb_trailer.url)
                    else:
                        self.db.insert_download(dl)
                        downloads.append(dl)
                # Already downloaded (success or non-retryable broken), skip
                continue

            # New URL, download it
            dl = self._download_trailer(tmdb_trailer)
            self.db.insert_download(dl)
            if not dl.file.broken:
                downloads.append(dl)

        # Update query timestamp ONLY for providers that succeeded
        # This allows per-provider retry: if IMDb had a 502, only IMDb retries on next run
        if providers_succeeded:
            self.db.update_provider_queries(movie.tmdb_id, providers_succeeded)
            self.log.debug("Updated query timestamps for tmdb_id=%d providers: %s",
                         movie.tmdb_id, ', '.join(sorted(providers_succeeded)))
        else:
            self.log.debug("No providers succeeded for tmdb_id=%d - all will retry on next run", movie.tmdb_id)

        self.log.info("Found %s new trailers for %s", len(downloads), movie)
        return downloads

    def _update_kodi(self, movie: Movie, trailer_path: str):
        """Update Kodi with new trailer."""
        if self.cfg.is_default:
            self.log.warning("Kodi is not configured. Skipping Kodi Update.")
            return

        self.db.insert_kodi_trailer_cache(str(movie.file_path), trailer_path)

        if not self.kodi.is_alive:
            self.log.warning("Kodi is not available. Skipping Kodi Update.")
            return

        for _, db_movie_path, db_trailer_path in self.db.select_kodi_trailer_cache():
            trailer_file_name = Path(db_trailer_path).name

            if kodi_movie := self.kodi.get_movie_by_file(db_movie_path):
                self.log.info("Setting trailer path for %s to %s", kodi_movie, trailer_file_name)
                if not self.kodi.set_trailer_path(kodi_movie.movie_id, db_trailer_path):
                    self.log.warning("Failed to set trailer path in Kodi for %s", trailer_file_name)
                    continue
            else:
                self.log.info("Kodi does not have %s, removing this trailer from cache", db_movie_path)
                self.db.delete_kodi_trailer_cache(db_movie_path)
                continue

            self.db.delete_kodi_trailer_cache(db_movie_path)
            if self.cfg.kodi_notify:
                self.kodi.notify("New Trailer Added", trailer_file_name)

    def _best_trailer(self, tmdb_id: int) -> Download | None:
        """
        Get the best trailer for the given movie.

        Uses selection_score which combines quality metrics with name-based filtering
        to prefer clean official trailers over commentary/marketing versions.
        """
        trailers = self.db.select_by_tmdb_id(tmdb_id)
        if not trailers:
            return None
        trailers = [x for x in trailers if not x.file.broken]
        trailers.sort(key=lambda x: x.selection_score, reverse=True)
        return trailers[0] if trailers else None

    def process_movie(self, movie: Movie):
        """Process the given movie."""
        self.log.info("Processing Movie: %s", movie)
        self.run_stats.movies_processed += 1

        temp_trailers = self._get_new_trailers(movie)
        local_file = self._get_local_trailer(movie)
        best_trailer = self._best_trailer(movie.tmdb_id)

        if not best_trailer:
            self.log.warning("No trailers found for %s", movie)
            return

        self.log.debug("Best Trailer: %s", best_trailer.tmdb.name)

        # Return early if best trailer is already in place
        if local_file and best_trailer.file.hash == local_file.hash:
            self.log.debug("Best trailer is already in place for %s", movie)
            if local_file.path.stem != f"{movie.file_path.stem}-trailer":
                self._move_trailer(local_file, movie)
                self._update_kodi(movie, str(local_file.path))
            return

        # Download trailer if not in temp directory and a best trailer exists
        if best_trailer.file not in [x.file for x in temp_trailers]:
            new_dl = self._download_trailer(best_trailer.tmdb)
            if not new_dl:
                self.log.warning("Failed to download best trailer for %s", movie)
                return

            best_trailer.file = new_dl.file
            self.db.insert_download(new_dl)
            temp_trailers.append(new_dl)

        if not temp_trailers:
            self.log.error("Expected at least one trailer in %s", TEMP_DIR)
            return

        temp_trailer = next(filter(lambda x: x.file == best_trailer.file, temp_trailers), None)
        if not temp_trailer:
            self.log.error("Best trailer not found in temp downloads for %s", movie)
            return

        # Detect upgrade vs new trailer
        if local_file:
            self.run_stats.upgrade_trailer()
            self.log.info(
                "Upgrading trailer for %s (old: %s, new: %s)",
                movie.title,
                local_file.codec_name or "unknown",
                best_trailer.file.codec_name or "unknown"
            )
        else:
            self.run_stats.add_trailer()
            self.log.info("Adding new trailer for %s", movie.title)

        self._delete_old_trailer(local_file)
        new_path = self._move_trailer(temp_trailer.file, movie)
        if not new_path:
            return

        self._update_kodi(movie, str(new_path))

    def process_all(self):
        """Process all movies in Radarr."""
        movies = self.radarr.get_downloaded_movies()
        for movie in movies:
            try:
                self.process_movie(movie)
            except Exception:
                self.log.exception("Failed to process movie: %s", movie.title)
                # Continue to next movie instead of crashing
            finally:
                self._cleanup_temp_folder()

        # Cleanup unused db entries
        radarr_tmdb_ids = {x.tmdb_id for x in movies}
        for tmdb_id in self.db.get_tmdb_ids():
            if tmdb_id not in radarr_tmdb_ids:
                self._remove_unused_trailers(tmdb_id)

    def run(self):
        """Run TrailArr."""
        if event := self.env.event_type:
            self.log.info("Called from Radarr: %s", self.env.event_type.value)
            match event:
                case Events.ON_DOWNLOAD:
                    self.process_movie(
                        Movie(
                            tmdb_id=self.env.tmdb_id,
                            title=self.env.movie_title,
                            year=self.env.movie_year,
                            directory=Path(self.env.movie_file_dir),
                            file_path=Path(self.env.movie_file_path),
                            imdb_id=self.env.imdb_id,
                        )
                    )
                case Events.ON_RENAME:
                    movie = self.radarr.get_movie_by_id(self.env.tmdb_id)
                    if not movie:
                        self.log.warning("TMDB id %s not found in Radarr.", self.env.tmdb_id)
                    else:
                        self.process_movie(movie)
                case Events.ON_MOVIE_FILE_DELETE:
                    if self.env.movie_file_delete_reason.lower() != "upgrade":
                        self._remove_unused_trailers(self.env.tmdb_id)
                case Events.ON_TEST:
                    self.test()
                case _:
                    self.exit(f"Unsupported Event Type. Got '{event}'. Allowed Events: [Download, Rename]")

        self.exit()
