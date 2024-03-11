#!/usr/bin/env python
"""Radarr API module."""

import logging
import xml.etree.ElementTree as ET
from pathlib import Path

import requests
from src import Movie


class RadarrApi:
    """Radarr API interface"""

    def __init__(self, api_key: str = None) -> None:
        self.log = logging.getLogger("TrailArr.Radarr")
        self.api_key = api_key
        self.base_url = None
        self._get_config()

    def _get_config(self) -> None:
        # Get data from config.xml
        tree = ET.parse(Path("/config/config.xml").resolve())
        root = tree.getroot()

        # Parse required data
        url_base = root.findtext("UrlBase", default="").lstrip("/")
        if url_base != "":
            url_base = f"/{url_base}"
        port = root.findtext("Port", default="7878")

        # Set instance variables
        self.base_url = f"http://127.0.0.1:{port}{url_base}/api/v3/"
        self.api_key = root.findtext("ApiKey")

    def _get(self, endpoint: str, params: dict = None) -> dict:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Connection": "close",
            "X-Api-Key": self.api_key,
        }

        try:
            resp = requests.get(url=f"{self.base_url}{endpoint}", headers=headers, timeout=10, params=params)
            resp.raise_for_status()
        except requests.HTTPError as e:
            print(e)
            return {}

        return resp.json()

    @staticmethod
    def _parse_movie_data(movie_data: dict) -> Movie:
        return Movie(
            tmdb_id=movie_data.get("tmdbId"),
            title=movie_data.get("title"),
            year=movie_data.get("year"),
            directory=Path(movie_data.get("folderName")),
            file_path=Path(movie_data["movieFile"].get("path")) if "movieFile" in movie_data else None,
        )

    def test(self) -> bool:
        """Test connection"""
        try:
            resp = self._get(endpoint="system/status")
            self.log.info("Test Success. Radarr Version: %s", resp.get("version"))
        except requests.HTTPError:
            return False
        return True

    def get_downloaded_movies(self) -> list[Movie]:
        """Get list of movies"""
        data = self._get(endpoint="movie")
        return [self._parse_movie_data(movie_data) for movie_data in data if movie_data.get("hasFile")]

    def get_movie_by_id(self, tmdb_id: int) -> Movie:
        """Get movie by tmdb id"""
        data = self._get(endpoint="movie", params={"tmdbId": tmdb_id})
        if len(data) != 1:
            return None
        return self._parse_movie_data(data[0])

    def get_movie_by_path(self, movie_path: str) -> Movie:
        """Get movie by path"""
        for movie in self.get_downloaded_movies():
            if movie.file_path == movie_path:
                return movie

        return None

    def get_iso_639_1(self) -> None:
        """Get language"""
        data = self._get(endpoint="localization/language")
        print("Radarr", data["identifier"])
