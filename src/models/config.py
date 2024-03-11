#!/usr/bin/env python
"""Trailarr Config Parser"""

from dataclasses import dataclass, field


@dataclass
class Config:
    """Trailarr Configuration"""

    log_level: str = field(default="INFO")
    kodi_name: str = field(default="")
    kodi_ip: str = field(default="127.0.0.1")
    kodi_port: int = field(default=8080)
    kodi_user: str = field(default="")
    kodi_pass: str = field(default="")
    kodi_notify: bool = field(default=False)

    @property
    def is_default(self):
        """Check if the configuration is the default"""
        return all(
            [
                self.log_level == "INFO",
                self.kodi_name == "",
                self.kodi_ip == "127.0.0.1",
                self.kodi_port == 8080,
                self.kodi_user == "",
                self.kodi_pass == "",
                self.kodi_notify is False,
            ]
        )
