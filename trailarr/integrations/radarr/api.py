"""Radarr API module."""

import logging
import xml.etree.ElementTree as ET
from pathlib import Path

import requests

from trailarr.models.movie import Movie


class RadarrApi:
    """Radarr API interface."""

    def __init__(self, api_key: str = None) -> None:
        self.log = logging.getLogger("TrailArr.Radarr")
        self.api_key = api_key
        self.base_url = None
        self._get_config()

    def _get_config(self) -> None:
        """Read Radarr connection details from config.xml."""
        config_path = Path("/config/config.xml")
        try:
            tree = ET.parse(config_path.resolve())
        except (FileNotFoundError, ET.ParseError) as e:
            self.log.error("Failed to read Radarr config at %s: %s", config_path, e)
            return

        root = tree.getroot()

        url_base = root.findtext("UrlBase", default="").lstrip("/")
        if url_base != "":
            url_base = f"/{url_base}"
        port = root.findtext("Port", default="7878")

        self.base_url = f"http://127.0.0.1:{port}{url_base}/api/v3/"
        self.api_key = root.findtext("ApiKey")

    def _get(self, endpoint: str, params: dict = None) -> dict | list:
        if not self.base_url or not self.api_key:
            self.log.error("Radarr is not configured. Cannot access %s.", endpoint)
            return {}

        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Connection": "close",
            "X-Api-Key": self.api_key,
        }

        try:
            resp = requests.get(url=f"{self.base_url}{endpoint}", headers=headers, timeout=10, params=params)
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            self.log.error("Error accessing %s. Error: %s", endpoint, e)
            return {}

    @staticmethod
    def _parse_movie_data(movie_data: dict) -> Movie:
        return Movie(
            tmdb_id=movie_data.get("tmdbId"),
            title=movie_data.get("title"),
            year=movie_data.get("year"),
            directory=Path(movie_data.get("folderName", "")),
            file_path=Path(movie_data["movieFile"].get("path")) if "movieFile" in movie_data else None,
            imdb_id=movie_data.get("imdbId"),
        )

    def test(self) -> bool:
        """Test connection."""
        resp = self._get(endpoint="system/status")
        if not resp or not resp.get("version"):
            return False
        self.log.info("Test Success. Radarr Version: %s", resp.get("version"))
        return True

    def get_downloaded_movies(self) -> list[Movie]:
        """Get list of movies."""
        data = self._get(endpoint="movie")
        if not isinstance(data, list):
            return []
        return [self._parse_movie_data(movie_data) for movie_data in data if movie_data.get("hasFile")]

    def get_movie_by_id(self, tmdb_id: int) -> Movie | None:
        """Get movie by tmdb id."""
        data = self._get(endpoint="movie", params={"tmdbId": tmdb_id})
        if not isinstance(data, list) or len(data) != 1:
            return None
        return self._parse_movie_data(data[0])

    def get_movie_by_path(self, movie_path: str) -> Movie | None:
        """Get movie by path."""
        for movie in self.get_downloaded_movies():
            if movie.file_path == movie_path:
                return movie
        return None
