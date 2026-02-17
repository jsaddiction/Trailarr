"""Radarr environment variable parser."""

import types
from dataclasses import dataclass, field, fields
from enum import Enum
from typing import get_args, get_origin, Any, Union
from os import environ


def _base_type(annotation) -> type | None:
    """Extract the base type from a type annotation, handling unions like 'int | None'.

    Returns the first non-NoneType argument from union types, or the annotation itself
    if it's a plain type.
    """
    origin = get_origin(annotation)
    if origin is Union or origin is types.UnionType:
        for arg in get_args(annotation):
            if arg is not type(None):
                return arg
        return None
    if isinstance(annotation, type):
        return annotation
    return None


class Events(Enum):
    """Radarr Events"""

    ON_GRAB = "Grab"
    ON_DOWNLOAD = "Download"
    ON_RENAME = "Rename"
    ON_MOVIE_ADD = "MovieAdded"
    ON_MOVIE_DELETE = "MovieDelete"
    ON_MOVIE_FILE_DELETE = "MovieFileDelete"
    ON_HEALTH_ISSUE = "HealthIssue"
    ON_HEALTH_RESTORED = "HealthRestored"
    ON_APPLICATION_UPDATE = "ApplicationUpdate"
    ON_MANUAL_INTERACTION_REQUIRED = "ManualInteractionRequired"
    ON_TEST = "Test"
    UNKNOWN = "Unknown"

    @classmethod
    def _missing_(cls, value: object) -> Any:
        value = value.upper()
        for member in cls:
            if member.value.upper() == value:
                return member
        return cls.UNKNOWN


@dataclass
class RadarrEnvironment:
    """Radarr Environment Variables"""

    event_type: Events = field(default=None, metadata={"var": "Radarr_EventType"})
    movie_title: str = field(default=None, metadata={"var": "Radarr_Movie_Title"})
    movie_year: int = field(default=None, metadata={"var": "Radarr_Movie_Year"})
    tmdb_id: int = field(default=None, metadata={"var": "radarr_movie_tmdbid"})
    imdb_id: str = field(default=None, metadata={"var": "Radarr_Movie_ImdbId"})
    movie_file_dir: str = field(default=None, metadata={"var": "Radarr_Movie_Path"})
    movie_file_path: str = field(default=None, metadata={"var": "Radarr_MovieFile_Path"})
    movie_file_delete_reason: str = field(default=None, metadata={"var": "Radarr_MovieFile_DeleteReason"})
    raw_vars: dict = field(default=None, repr=False)

    @classmethod
    def _parse_bool(cls, value: str) -> bool:
        if isinstance(value, str):
            if value.lower().strip() == "true":
                return True
            if value.lower().strip() == "false":
                return False
        raise ValueError(f"Failed to parse {value} to boolean")

    @classmethod
    def _parse_int(cls, value: str) -> int:
        if isinstance(value, str):
            try:
                return int(value.strip())
            except ValueError:
                pass
        raise ValueError(f"Failed to parse {value} to int")

    def __post_init__(self) -> None:
        self.raw_vars = {k.lower().strip(): v for k, v in environ.items() if k.lower().startswith("radarr")}

        for attr in fields(self):
            var_name = attr.metadata.get("var")
            if not var_name:
                continue

            value = self.raw_vars.get(var_name.lower())
            if not value:
                continue

            base = _base_type(attr.type)
            if base is None:
                continue

            if issubclass(base, Events):
                self.__setattr__(attr.name, Events(value))
            elif issubclass(base, str):
                self.__setattr__(attr.name, value.strip())
            elif issubclass(base, bool):
                self.__setattr__(attr.name, self._parse_bool(value))
            elif issubclass(base, int):
                self.__setattr__(attr.name, self._parse_int(value))
            elif get_origin(attr.type) == list:
                list_type = get_args(attr.type)[0]
                if issubclass(list_type, str):
                    value_lst = [x.strip() for x in value.split("|")]
                    self.__setattr__(attr.name, value_lst)
                elif issubclass(list_type, int):
                    value_lst = [self._parse_int(x) for x in value.split(",")]
                    self.__setattr__(attr.name, value_lst)
