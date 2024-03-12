#!/usr/bin/env python
"""Kodi JSON-RPC Interface"""

import json
import logging
from pathlib import Path, PurePosixPath, PureWindowsPath

import requests
from src import RPCVersion, Platform, KodiResponse, Player, MOVIE_PROPERTIES, MovieDetails, KodiAPIError


class KodiApi:
    """Kodi JSON-RPC Client"""

    RETRIES = 3
    TIMEOUT = 5
    HEADERS = {"Content-Type": "application/json", "Accept": "plain/text"}

    def __init__(
        self,
        name: str,
        ip: str,
        port: int = 8080,
        user: str = None,
        password: str = None,
        path_maps: dict = None,
    ) -> None:
        self.log = logging.getLogger(f"TrailArr.Kodi-{name}")
        self.base_url = f"http://{ip}:{port}/jsonrpc"
        self.name = name
        self.path_maps: dict[str, str] = path_maps or {}
        self._platform: Platform = None

        # Establish session
        self.session = requests.Session()
        if user and password:
            self.session.auth = (user, password)
        self.session.headers.update(self.HEADERS)
        self.req_id = 0

    def __str__(self) -> str:
        return f"{self.name} JSON-RPC({self.rpc_version})"

    @property
    def platform(self) -> Platform:
        """Get platform of this client"""
        if self._platform:
            return self._platform

        params = {"booleans": [x.value for x in Platform]}
        try:
            resp = self._req("XBMC.GetInfoBooleans", params=params)
        except KodiAPIError as e:
            self.log.warning("Failed to get platform info. Error: %s", e)
            self._platform = Platform.UNKNOWN
            return self._platform

        # Check all platform booleans and return the first one that is True
        for k, v in resp.result.items():
            if v:
                return Platform(k)

        # Return unknown if no platform booleans are True
        self._platform = Platform.UNKNOWN
        return self._platform

    @property
    def rpc_version(self) -> RPCVersion | None:
        """Return JSON-RPC Version of host"""
        try:
            resp = self._req("JSONRPC.Version")
        except KodiAPIError as e:
            self.log.warning("Failed to get JSON-RPC Version. Error: %s", e)
            return None

        return RPCVersion(
            major=resp.result["version"].get("major"),
            minor=resp.result["version"].get("minor"),
            patch=resp.result["version"].get("patch"),
        )

    @property
    def is_alive(self) -> bool:
        """Return True if Kodi Host is responsive"""
        try:
            resp = self._req("JSONRPC.Ping")
        except KodiAPIError as e:
            self.log.warning("Failed to ping host. Error: %s", e)
            return False

        return resp.result == "pong"

    @property
    def is_playing(self) -> bool:
        """Return True if Kodi Host is currently playing content"""
        return bool(self.active_players)

    @property
    def active_players(self) -> list[Player]:
        """Get a list of active players"""
        try:
            resp = self._req("Player.GetActivePlayers")
        except KodiAPIError as e:
            self.log.warning("Failed to get active players. Error: %s", e)
            return []

        active_players: list[Player] = []
        for active_player in resp.result:
            active_players.append(
                Player(
                    player_id=active_player["playerid"],
                    player_type=active_player["playertype"],
                    type=active_player["type"],
                )
            )

        return active_players

    @property
    def is_scanning(self) -> bool:
        """True if a library scan is in progress"""
        params = {"booleans": ["Library.IsScanning"]}
        try:
            resp = self._req("XBMC.GetInfoBooleans", params=params)
        except KodiAPIError as e:
            self.log.warning("Failed to determine scanning state. Error: %s", e)
            return False

        return resp.result["Library.IsScanning"]

    @property
    def is_posix(self) -> bool:
        """If this host uses posix file naming conventions"""
        return self.platform not in [Platform.WINDOWS, Platform.UNKNOWN]

    def __del__(self) -> None:
        self.close_session()

    # --------------- Helper Methods -----------------
    def _map_path_to_kodi(self, path: str) -> Path:
        """Map path from Radarr to Kodi path using path_maps"""
        output = path
        for from_str, to_str in self.path_maps.items():
            if path.startswith(from_str):
                output = path.replace(from_str, to_str)

        if self.is_posix:
            return PurePosixPath(output)
        return PureWindowsPath(output)

    def _map_path_from_kodi(self, path: str) -> Path:
        """Map path from Kodi to Radarr path using path_maps"""
        output = path
        for from_str, to_str in self.path_maps.items():
            if path.startswith(to_str):
                output = path.replace(to_str, from_str)

        return Path(output)

    def _get_filename_from_path(self, path: str) -> str:
        """Extract filename from path based on os type"""
        if self.is_posix:
            return str(PurePosixPath(path).name)
        return str(PureWindowsPath(path).name)

    def _get_dirname_from_path(self, path: str) -> str:
        """Extract dir name from path based on os type"""
        if self.is_posix:
            return str(PurePosixPath(path).parent)
        return str(PureWindowsPath(path).parent)

    def _parse_movie_details(self, movie_data: dict) -> MovieDetails | None:
        try:
            movie_path = self._map_path_from_kodi(movie_data.get("file"))
            trailer_path = self._map_path_from_kodi(movie_data.get("trailer"))
            return MovieDetails(
                movie_id=movie_data["movieid"],
                movie_path=movie_path,
                title=movie_data["title"],
                year=movie_data["year"],
                tmdb=movie_data["uniqueid"].get("tmdb"),
                trailer_path=trailer_path,
            )
        except KeyError as e:
            self.log.warning("Failed to parse movie details. Error: %s", e)
            return None

    def _req(self, method: str, params: dict = None, timeout: int = None) -> KodiResponse | None:
        """Send request to this Kodi Host"""
        req_params = {"jsonrpc": "2.0", "id": self.req_id, "method": method}
        if params:
            req_params["params"] = params
        response = None
        try:
            resp = self.session.post(
                url=self.base_url,
                data=json.dumps(req_params).encode("utf-8"),
                timeout=timeout or self.TIMEOUT,
            )
            resp.raise_for_status()
            response = resp.json()
        except requests.Timeout as e:
            raise KodiAPIError(f"Request timed out after {timeout}s") from e
        except requests.HTTPError as e:
            if resp.status_code == 401:
                raise KodiAPIError("HTTP Error. Unauthorized. Check Credentials") from e
            raise KodiAPIError(f"HTTP Error. Error: {e}") from e
        except requests.ConnectionError as e:
            raise KodiAPIError(f"Connection Error. {e}") from e
        finally:
            self.req_id += 1

        if "error" in response:
            raise KodiAPIError(response.get("error"))

        return KodiResponse(
            req_id=response.get("id"),
            jsonrpc=response.get("jsonrpc"),
            result=response.get("result"),
        )

    def close_session(self) -> None:
        """Close the session"""
        self.log.debug("Closing session")
        self.session.close()

    # --------------- UI Methods ---------------------
    def update_gui(self) -> None:
        """Update GUI|Widgets by scanning a non existent path"""
        params = {"directory": "/does_not_exist/", "showdialogs": False}
        self.log.info("Updating GUI")
        try:
            self._req("VideoLibrary.Scan", params=params)
        except KodiAPIError as e:
            self.log.warning("Failed to update GUI. Error: %s", e)

    # Need an image if we keep this method
    def notify(self, title: str, msg: str, display_time: int = 5000) -> None:
        """Send GUI Notification to Kodi Host"""
        params = {
            "title": str(title),
            "message": str(msg),
            "displaytime": int(display_time),
            "image": "https://github.com/jsaddiction/Sonarr_Kodi/raw/main/img/sonarr.png",
        }
        self.log.info("Sending GUI Notification :: (title='%s', msg='%s'", title, msg)
        try:
            self._req("GUI.ShowNotification", params=params)
        except KodiAPIError as e:
            self.log.warning("Failed to send notification. Error: %s", e)

    # --------------- Movie Methods -----------------
    def get_movie_by_file(self, path: str) -> MovieDetails | None:
        """Get all movies given a file path"""
        mapped_path = self._map_path_to_kodi(path)
        file_name = self._get_filename_from_path(mapped_path)
        file_dir = self._get_dirname_from_path(mapped_path)
        params = {
            "properties": MOVIE_PROPERTIES,
            "filter": {
                "and": [
                    {"operator": "startswith", "field": "path", "value": file_dir},
                    {"operator": "is", "field": "filename", "value": file_name},
                ]
            },
        }

        # self.log.debug("Getting all movies from path %s", mapped_path)
        try:
            resp = self._req("VideoLibrary.GetMovies", params=params)
        except KodiAPIError as e:
            self.log.warning("Failed to get movies from file '%s'. Error: %s", mapped_path, e)
            return []

        if len(resp.result["movies"]) != 1:
            self.log.warning("Found %s movies for file '%s'. Expected 1.", len(resp.result["movies"]), mapped_path)
            return None

        return self._parse_movie_details(resp.result["movies"][0])

    def set_trailer_path(self, movie_id: int, trailer_path: str) -> bool:
        """Set the trailer path for a movie"""
        params = {"movieid": movie_id, "trailer": str(self._map_path_to_kodi(trailer_path))}
        self.log.debug("Setting trailer path for movie %s to %s", movie_id, params["trailer"])
        try:
            resp = self._req("VideoLibrary.SetMovieDetails", params=params)
        except KodiAPIError as e:
            self.log.warning("Failed to set trailer path for movie %s. Error: %s", movie_id, e)

        return resp.result == "OK"

    def get_all_movies(self) -> list[MovieDetails]:
        """Get all movies from Kodi Host"""
        params = {"properties": MOVIE_PROPERTIES}
        self.log.debug("Getting all movies")
        try:
            resp = self._req("VideoLibrary.GetMovies", params=params)
        except KodiAPIError as e:
            self.log.warning("Failed to get all movies. Error: %s", e)
            return []

        return [self._parse_movie_details(x) for x in resp.result["movies"]]
