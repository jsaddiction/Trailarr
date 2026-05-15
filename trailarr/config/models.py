"""Trailarr Configuration Model."""

from dataclasses import dataclass, field


@dataclass
class Config:
    """Trailarr Configuration"""

    log_level: str = field(default="INFO")
    max_resolution: int = field(default=1080)
    pot_provider_url: str = field(default="")
    source_block_minutes: int = field(default=1440)
    kodi_name: str = field(default="")
    kodi_ip: str = field(default="127.0.0.1")
    kodi_port: int = field(default=8080)
    kodi_user: str = field(default="")
    kodi_pass: str = field(default="")
    kodi_notify: bool = field(default=False)

    @property
    def is_default(self):
        """Check if the Kodi configuration is at defaults.

        Only the Kodi block is consulted — pot_provider_url, log_level, etc.
        don't affect whether trailarr should attempt Kodi library updates.
        """
        return all(
            [
                self.kodi_name == "",
                self.kodi_ip == "127.0.0.1",
                self.kodi_port == 8080,
                self.kodi_user == "",
                self.kodi_pass == "",
                self.kodi_notify is False,
            ]
        )
