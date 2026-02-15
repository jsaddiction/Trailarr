"""Kodi integration package."""

from trailarr.integrations.kodi.api import KodiApi
from trailarr.integrations.kodi.exceptions import KodiAPIError

__all__ = ["KodiApi", "KodiAPIError"]
