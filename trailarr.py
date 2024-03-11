#!/usr/bin/env python
"""Main Entry Point for TrailArr"""

import sys
import shutil
import logging
from pathlib import Path

from src import (
    Movie,
    Download,
    TMDBVideo,
    FileDetails,
    DB,
    RadarrApi,
    TmdbApi,
    YouTubeDLP,
    YTDLPError,
    FfmpegAPI,
    FfmpegError,
    RadarrEnvironment,
    DB_FILE,
    TEMP_DIR,
    VIDEO_EXTENSIONS,
    Events,
    KodiApi,
    CFG,
)


class TrailArr:
    """TrailArr Main Class"""

    def __init__(self):
        self.log = logging.getLogger("TrailArr")
        self.env = RadarrEnvironment()
        self.db = DB(DB_FILE)
        self.ytdlp = YouTubeDLP(TEMP_DIR)
        self.ffmpeg = FfmpegAPI()
        self.tmdb = TmdbApi()
        self.radarr = RadarrApi()
        self.kodi = KodiApi(CFG.kodi_name, CFG.kodi_ip, CFG.kodi_port, CFG.kodi_user, CFG.kodi_pass)

    @property
    def has_write_permission(self) -> bool:
        """Check if the temp folder has write permission"""
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

    def exit(self, error: str = None) -> None:
        """Exit the program with an error message"""
        self.db.close()
        self.tmdb.close()
        # self.radarr.close()
        self._cleanup_temp_folder()
        if error:
            self.log.critical("Exited with Error: %s", error)
            sys.exit(1)

        # self.log.info("Completed Successfully")
        # sys.exit(0)

    def test(self):
        """Run tests for TrailArr"""
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

        if not self.tmdb.test():
            self.exit("TMDB API Test Failed. Exiting.")

    def _move_trailer(self, file: FileDetails, movie: Movie) -> Path | None:
        """Move trailer to movie directory"""
        if not file.path.exists():
            self.log.warning("Trailer file does not exist: %s", file.path)
            return None
        if not movie.directory.exists():
            self.log.warning("Movie directory does not exist: %s", movie.directory)
            return None
        if not movie.file_path.exists():
            self.log.warning("Movie file does not exist: %s", movie.file_path)
            return None

        # Calculate new file path and move the trailer
        file_name = f"{Path(movie.file_path).stem}-trailer{file.path.suffix}"
        trailer_path = Path(movie.directory, file_name)
        self.log.info("Moving trailer to %s", trailer_path)
        shutil.move(str(file.path), str(trailer_path))
        return trailer_path

    def _delete_old_trailer(self, file: FileDetails) -> None:
        """Delete old trailer file"""
        if file and file.path.exists():
            self.log.info("Deleting Old Trailer: %s", file.path)
            file.path.unlink()

    def _cleanup_temp_folder(self) -> None:
        """Cleanup the temp folder"""
        self.log.debug("Cleaning up Temp Folder")
        for file in TEMP_DIR.iterdir():
            if not file.is_file():
                continue
            self.log.debug("Deleting: %s", file)
            file.unlink()
        self.log.debug("Temp Folder Cleaned")

    def _remove_unused_trailers(self, tmdb_id: int) -> None:
        """Remove unused trailers from the database"""
        self.log.info("Removing unused trailers for tmdbid %s", tmdb_id)
        self.db.delete_by_tmdb_id(tmdb_id)

    def _get_local_trailer(self, movie: Movie) -> FileDetails | None:
        """Get local file details"""
        self.log.info("Checking for local trailers in %s", movie.directory)
        local_trailers: list[Path] = []
        if not movie.file_path.exists():
            self.log.warning("Movie file does not exist: %s", movie.file_path)
            return None

        # Iterate over the directory and find trailers
        for item in movie.directory.iterdir():
            # Skip directories
            if item.is_dir():
                continue

            # Skip the movie file
            if item == movie.file_path:
                continue

            # Check if file is a video and has "-trailer" in the name
            if item.suffix in VIDEO_EXTENSIONS and "-trailer" in item.name.lower():
                local_trailers.append(item)

        # Found more than one trailer file
        if len(local_trailers) > 1:
            trailer_list = ", ".join([x.name for x in local_trailers])
            self.log.warning("Found more than one trailer file in %s : [%s]", movie.directory, trailer_list)
            return None

        # No trailers found
        if not local_trailers:
            self.log.info("No local trailers found in %s", movie.directory)
            return None

        # Check database for existing details
        local_trailer = local_trailers[0]
        self.log.info("Found Local Trailer: %s", local_trailer.name)
        file_hash = self.ffmpeg.calc_hash(local_trailer)
        if dl := self.db.select_by_hash(file_hash):
            self.log.info("%s was downloaded previously.", local_trailer.name)
            dl.file.path = local_trailer
            return dl.file

        # Get details for unknown trailer
        try:
            return self.ffmpeg.get_video_details(local_trailer, file_hash)
        except FfmpegError as e:
            self.log.error("Failed to get details for %s. Error: %s", local_trailers[0], e)
            return None

    def _download_trailer(self, tmdb_data: TMDBVideo) -> Download | None:
        """Download a trailer into the temp folder"""
        try:
            trailer_path = self.ytdlp.download(tmdb_data.url)
        except YTDLPError as e:
            self.log.error("Failed to download %s. Error: %s", tmdb_data.url, e)
            return None

        try:
            trailer_file = self.ffmpeg.get_video_details(trailer_path)
        except FfmpegError as e:
            self.log.error("Failed to get details for %s. Error: %s", trailer_path, e)
            return None

        return Download(tmdb=tmdb_data, file=trailer_file)

    def _get_new_trailers(self, movie: Movie) -> list[Download]:
        """Download trailers not in db and return list of Downloads"""
        self.log.info("Getting new trailers for %s", movie)
        downloads: list[Download] = []
        for tmdb_trailer in self.tmdb.get_trailers(movie.tmdb_id):
            # Skip this result if results already in db
            if self.db.select_by_url(tmdb_trailer.url):  # add tmdb_id to this
                continue

            # Download the trailer
            if dl := self._download_trailer(tmdb_trailer):
                self.db.insert_download(dl)
                downloads.append(dl)

        self.log.info("Found %s new trailers for %s", len(downloads), movie)
        return downloads

    def _update_kodi(self, movie: Movie, trailer_path: str):
        """Update Kodi with new trailer"""
        if CFG.is_default:
            self.log.warning("Kodi is not configured. Skipping Kodi Update.")
            return

        kodi_movie = self.kodi.get_movie_by_file(movie.file_path)
        if not kodi_movie:
            self.log.warning("Kodi does not have %s", movie)
            return

        self.kodi.set_trailer_path(kodi_movie.movie_id, trailer_path)
        if CFG.kodi_notify:
            self.kodi.notify("New Trailer Added", movie)

    def _best_trailer(self, tmdb_id: int) -> Download | None:
        """Get the best trailer for the given movie"""
        trailers = self.db.select_by_tmdb_id(tmdb_id)
        if not trailers:
            return None
        trailers = [x for x in trailers if not x.file.broken]  # Remove broken trailers
        trailers.sort(key=lambda x: (not x.file.forced, x.file.quality_score), reverse=True)
        return trailers[0] if trailers else None

    def process_movie(self, movie: Movie):
        """Process the given movie"""
        self.log.info("Processing Movie: %s", movie)
        temp_trailers = self._get_new_trailers(movie)  # Trailers in the temp directory
        local_file = self._get_local_trailer(movie)  # Trailer in the movie directory
        best_trailer = self._best_trailer(movie.tmdb_id)  # Best trailer in the database

        # Return early if no trailers
        if not best_trailer:
            page_url = self.tmdb.get_page(movie.tmdb_id)
            self.log.warning("TMDB has no trailers listed for %s", movie)
            self.log.info("Add some trailers! %s", page_url)
            return

        self.log.info("Best Trailer on TMDB: %s", best_trailer.tmdb.name)

        # Return early if best trailer is already in place
        if local_file and best_trailer.file.hash == local_file.hash:
            self.log.info("Best trailer is already in place for %s", movie)

            # Ensure trailer filename is correct
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

            best_trailer.file = new_dl.file  # Update best trailer with new file details
            self.db.insert_download(new_dl)  # Insert and overwrites existing data
            temp_trailers.append(new_dl)

        # Ensure best trailer is in temp directory
        if not temp_trailers:
            self.log.error("Expected at least one trailer in %s", TEMP_DIR)
            return

        if temp_trailer := next(filter(lambda x: x.file == best_trailer.file, temp_trailers), None):
            # Delete existing trailer if it exists
            self._delete_old_trailer(local_file)

            # Move new trailer to movie directory
            new_path = self._move_trailer(temp_trailer.file, movie)

        # Update Kodi with new trailer
        self._update_kodi(movie, new_path)

    def process_all(self):
        """Process all movies in Radarr"""
        movies = self.radarr.get_downloaded_movies()
        for movie in movies:
            self.process_movie(movie)
            self._cleanup_temp_folder()

    def run(self):
        """Run TrailArr"""

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
                        )
                    )
                case Events.ON_RENAME:
                    movie = self.radarr.get_movie_by_id(self.env.tmdb_id)
                    self.process_movie(movie)
                case Events.ON_MOVIE_FILE_DELETE:
                    if self.env.movie_file_delete_reason.lower() != "upgrade":
                        self._remove_unused_trailers(self.env.tmdb_id)
                case Events.ON_TEST:
                    self.test()
                case _:
                    self.exit(f"Unsupported Event Type. Got '{event}'. Allowed Events: [Download, Rename]")

        # Script completed successfully. Exit
        self.exit()


if __name__ == "__main__":
    # Run the app
    app = TrailArr()
    try:
        app.run()
    except KeyboardInterrupt:
        app.exit("User Terminated Script.")
