"""YT-DLP Downloader CLI Interface."""

import json
import logging
import os
import re
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path


class YTDLPError(Exception):
    """Base YT-DLP Exception. A per-URL failure: the video is bad, geo-blocked,
    network glitch, etc. The URL itself is the locus of the problem."""


class YTDLPSessionBlockedError(YTDLPError):
    """Session-level rejection from the source (e.g. YouTube's
    "Sign in to confirm you're not a bot"). Nothing wrong with the URL —
    the source has revoked our anonymous access. Callers should skip the URL
    without recording it as broken, and mark the source as blocked so further
    URLs from the same host are skipped for a window.

    Subclass of YTDLPError so any pre-existing `except YTDLPError` keeps
    catching it as a safety net even if a new code path forgets the
    specific handler.
    """


# Stderr substrings that mark a source-wide rejection rather than a per-URL
# problem. We extend this list as we observe new patterns from Vimeo, AppleTV
# CDN, etc. Match is plain substring (case-sensitive — yt-dlp's wording is
# stable enough that this is fine).
SESSION_FAILURE_PATTERNS = (
    "Sign in to confirm",
    "LOGIN_REQUIRED",
)


def _is_session_failure(stderr: str) -> bool:
    """True iff stderr contains any source-wide-rejection fingerprint."""
    return any(pat in stderr for pat in SESSION_FAILURE_PATTERNS)


# Configuration key for the bgutil-ytdlp-pot-provider HTTP plugin. yt-dlp
# accepts these as `--extractor-args` and routes them to the matching plugin.
# Verified against https://github.com/Brainicism/bgutil-ytdlp-pot-provider .
POT_EXTRACTOR_KEY = "youtubepot-bgutilhttp"
POT_PROBE_TIMEOUT_SECS = 2


class YouTubeDLP:
    """YT-DLP Downloader CLI Interface."""

    def __init__(self, temp_directory: Path, pot_provider_url: str | None = None):
        self.log = logging.getLogger("TrailArr.YT-DLP")
        self.temp_directory = temp_directory
        # Per-instance HOME override for pip --user / yt-dlp invocations. When
        # the inherited HOME points at a directory the current user can't write
        # (common in LinuxServer.io images, where services run as UID 998 but
        # HOME=/root is inherited from s6 init), we relocate to a writable
        # fallback so self-update and runtime invocations stay in sync.
        self._home: str | None = self._resolve_writable_home()
        self.upgrade()
        # One-shot reachability probe for the optional PO token provider.
        # Result decides whether subsequent yt-dlp calls get the bgutil
        # extractor-args. Provider downtime mid-run degrades to today's
        # bot-detection failure mode — not catastrophic, self-heals next run.
        self._pot_provider_url: str | None = self._probe_pot_provider(pot_provider_url)

    def _resolve_writable_home(self) -> str | None:
        """Find a HOME the current user can write to.

        Returns None if no candidate is writable — caller should treat that as
        "self-update unavailable, continue with whatever yt-dlp is on PATH".
        """
        candidates = [
            os.environ.get("HOME"),
            os.path.expanduser("~"),  # honors passwd entry even if HOME is unset
            "/config",                # LSI convention for the service user's home
            tempfile.gettempdir(),
        ]
        seen: set[str] = set()
        for candidate in candidates:
            if not candidate or candidate in seen:
                continue
            seen.add(candidate)
            try:
                probe = Path(candidate) / ".local"
                probe.mkdir(parents=True, exist_ok=True)
                marker = probe / ".trailarr_write_probe"
                marker.touch()
                marker.unlink()
                return candidate
            except OSError:
                continue
        return None

    def _probe_pot_provider(self, url: str | None) -> str | None:
        """One-shot reachability check for the bgutil PO token provider.

        Returns the URL if a TCP/HTTP connection succeeds (any response code
        — even 404 — proves the server is listening), otherwise None. Treated
        as informational, not error: opting out is a valid configuration.
        """
        if not url:
            return None
        try:
            with urllib.request.urlopen(url, timeout=POT_PROBE_TIMEOUT_SECS):
                pass
        except urllib.error.HTTPError:
            # Server returned a non-2xx — that's fine, it's alive.
            self.log.info("PO token provider reachable at %s", url)
            return url
        except (urllib.error.URLError, OSError) as e:
            self.log.info(
                "PO token provider %s not reachable; continuing without (%s)",
                url, e,
            )
            return None
        self.log.info("PO token provider reachable at %s", url)
        return url

    def _pot_extractor_args(self) -> list[str]:
        """Return the yt-dlp arg pair for the PO token provider, or []."""
        if not self._pot_provider_url:
            return []
        return ["--extractor-args", f"{POT_EXTRACTOR_KEY}:base_url={self._pot_provider_url}"]

    def _subprocess_env(self) -> dict:
        """Env for pip/yt-dlp subprocess calls.

        When _home is set, points HOME at the writable fallback AND prepends
        $HOME/.local/bin to PATH so an updated yt-dlp entrypoint shadows the
        system-installed one. Without the PATH tweak, `yt-dlp` would still
        resolve to /usr/bin/yt-dlp (the system copy) and Python's user-site
        import would only apply via `python -m yt_dlp`.
        """
        env = os.environ.copy()
        if self._home:
            env["HOME"] = self._home
            user_bin = f"{self._home}/.local/bin"
            env["PATH"] = f"{user_bin}:{env.get('PATH', '')}"
        return env

    def upgrade(self) -> None:
        """Non-fatal self-update of yt-dlp to latest version via pip.

        Installs into the user site under self._home (NOT the system site),
        because services in LSI containers run as non-root but the system site
        is root-owned. yt-dlp updates frequently to keep up with YouTube's
        format changes, so this is run on every invocation.
        """
        if self._home is None:
            self.log.warning(
                "No writable HOME found for pip --user install; "
                "skipping yt-dlp self-update. Using system yt-dlp."
            )
            return

        self.log.info("Checking for yt-dlp updates (user-site under %s)...", self._home)
        # --user installs to $HOME/.local; --break-system-packages is required
        # on Alpine/Debian's externally-managed Python; --pre allows nightly
        # builds when they ship YouTube extractor fixes.
        cmd = [
            sys.executable, "-m", "pip", "install",
            "--user", "-U", "--pre", "--break-system-packages",
            "yt-dlp",
        ]
        try:
            result = subprocess.run(
                cmd, capture_output=True, timeout=60, env=self._subprocess_env(),
            )
            stdout = result.stdout.decode(errors="replace").strip()
            stderr = result.stderr.decode(errors="replace").strip()

            if result.returncode == 0:
                if "already satisfied" in stdout.lower() or "already up-to-date" in stdout.lower():
                    self.log.debug("yt-dlp is already up to date")
                else:
                    self.log.info("yt-dlp updated successfully")
                return

            # Pattern-match a couple of common, actionable failure modes so the
            # log line is useful instead of a wall of pip stderr.
            if "Permission denied" in stderr:
                self.log.warning(
                    "yt-dlp self-update blocked by filesystem permissions on %s; "
                    "continuing with current version. stderr: %s",
                    self._home, stderr[:300],
                )
            elif "Could not find a version" in stderr or "No matching distribution" in stderr:
                self.log.warning(
                    "yt-dlp self-update could not reach an index (network/DNS?); "
                    "continuing with current version. stderr: %s",
                    stderr[:300],
                )
            else:
                self.log.warning(
                    "yt-dlp update returned code %d: %s",
                    result.returncode, stderr or stdout,
                )
        except subprocess.TimeoutExpired:
            self.log.warning("yt-dlp update timed out after 60s, continuing with current version")
        except FileNotFoundError:
            self.log.warning("pip not found, skipping yt-dlp update")
        except OSError:
            self.log.exception("Unexpected error during yt-dlp update, continuing with current version")

    def test(self) -> bool:
        """Test YT-DLP connection."""
        cmd = ["yt-dlp", "--version"]
        try:
            result = subprocess.run(
                cmd, stdout=subprocess.PIPE, check=True, timeout=10,
                env=self._subprocess_env(),
            )
            data = result.stdout.decode()
        except subprocess.CalledProcessError as e:
            self.log.critical("YT-DLP Test Failed: %s", e)
            return False
        except FileNotFoundError as e:
            self.log.critical("YT-DLP Not Found: %s", e)
            return False

        self.log.info("YT-DLP Version: %s", data.strip())
        return True

    def _is_apple_tv_url(self, url: str) -> bool:
        """Check if URL is an Apple TV HLS stream."""
        return "play-edge.itunes.apple.com" in url.lower() or "tv.apple.com" in url.lower()

    def _get_clean_audio_format(self, url: str, max_resolution: int) -> str | None:
        """
        Get explicit format string for Apple TV HLS that excludes audio description tracks.

        Audio description tracks have format IDs ending with underscore (e.g., "English_").
        Clean audio tracks have format IDs without underscore (e.g., "English").

        Returns format string like "12345+67890" or None if unable to determine.
        """
        try:
            # Get format list as JSON
            cmd = ["yt-dlp", "-J", "--no-warnings", *self._pot_extractor_args(), url]
            result = subprocess.run(
                cmd, capture_output=True, timeout=30, check=True,
                env=self._subprocess_env(),
            )
            data = json.loads(result.stdout.decode())

            formats = data.get("formats", [])

            # Find best video format up to max_resolution
            video_formats = [
                f for f in formats
                if f.get("vcodec") != "none"
                and f.get("height", 0) <= max_resolution
            ]
            best_video = max(video_formats, key=lambda f: (f.get("height", 0), f.get("tbr") or 0)) if video_formats else None

            # Find best audio format WITHOUT underscore in format_id (excludes audio description)
            # Prefer English, then highest bitrate
            # For Apple TV HLS, format IDs contain bitrate hints: stereo-160 > stereo-64 > stereo-32
            audio_formats = [
                f for f in formats
                if f.get("acodec") != "none"
                and f.get("vcodec") == "none"
                and not f.get("format_id", "").endswith("_")  # Exclude audio description tracks
                and f.get("language") == "en"  # Prefer English
            ]

            def audio_quality_key(f):
                """Extract quality score from format - prefer higher bitrate, more channels."""
                format_id = f.get("format_id", "")
                # Extract bitrate from format ID (e.g., "audio-stereo-160" -> 160)
                bitrate_match = re.search(r'-(\d+)$', format_id)
                bitrate = int(bitrate_match.group(1)) if bitrate_match else 0
                channels = f.get("audio_channels") or 2
                return (channels, bitrate)

            best_audio = max(audio_formats, key=audio_quality_key) if audio_formats else None

            if best_video and best_audio:
                format_str = f"{best_video['format_id']}+{best_audio['format_id']}"
                self.log.info("Selected Apple TV formats: video=%s audio=%s",
                             best_video['format_id'], best_audio['format_id'])
                return format_str

        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, json.JSONDecodeError,
                KeyError, ValueError, TypeError) as e:
            self.log.warning("Failed to determine clean audio format for Apple TV: %s", e)

        return None

    def download(self, url: str, max_resolution: int = 1080) -> Path:
        """Download video from url, return downloaded file path.

        Args:
            url: Video URL to download
            max_resolution: Maximum resolution (360, 480, 720, 1080, 2160)
        """
        self.log.info("Downloading video from %s (max resolution: %dp)", url, max_resolution)

        # For Apple TV HLS, explicitly select format to avoid audio description tracks
        format_selector = None
        if self._is_apple_tv_url(url):
            format_selector = self._get_clean_audio_format(url, max_resolution)

        cmd = ["yt-dlp", "--quiet", "--no-simulate", "-N", "5"]

        if format_selector:
            cmd.extend(["-f", format_selector])
        else:
            # Prefer h264 + aac for universal Kodi/player compatibility.
            # Without this, yt-dlp serves AV1/Opus from YouTube which many devices can't decode.
            cmd.extend(["-S", f"res:{max_resolution},vcodec:h264,acodec:aac,lang:en"])

        # Fall back across YouTube player clients. The default client (android_vr)
        # reports "video unavailable" for some trailers that the older 'android'
        # client can fetch (no JS-runtime signature decryption needed).
        cmd.extend(["--extractor-args", "youtube:player_client=default,android,web,ios"])

        # PO token provider (bgutil-ytdlp-pot-provider) — bypasses YouTube's
        # bot-detection gating when configured and reachable. No-op otherwise.
        cmd.extend(self._pot_extractor_args())

        # Enable the EJS (extracted-JS) challenge solver. Together with the deno
        # JS runtime installed by the installer, this unlocks full-resolution
        # formats (e.g. 1080p) that YouTube gates behind n-challenge decryption.
        # yt-dlp caches the solver after the first fetch.
        cmd.extend(["--remote-components", "ejs:github"])

        cmd.extend([
            "--remux-video", "mp4",
            "-O", "after_move:filepath",
            "-P", str(self.temp_directory),
            "-o", "%(id)s-%(epoch)s.%(ext)s",
            url,
        ])

        # Use Popen so we can kill yt-dlp explicitly on signal/timeout. subprocess.run
        # leaves the child running when KeyboardInterrupt fires during wait().
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            env=self._subprocess_env(),
        )
        try:
            stdout, stderr = proc.communicate(timeout=600)
        except (KeyboardInterrupt, subprocess.TimeoutExpired) as e:
            proc.kill()
            try:
                proc.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                pass
            if isinstance(e, KeyboardInterrupt):
                raise
            raise YTDLPError(f"Download timed out for {url}") from e

        if proc.returncode != 0:
            # Surface yt-dlp's last line of stderr — its actual failure reason
            # (signature decryption, geo-block, video unavailable, etc.). The
            # full stderr can be tens of KB on a verbose failure; truncate.
            err_text = stderr.decode(errors="replace").strip() if stderr else ""
            last_line = err_text.splitlines()[-1] if err_text else "(no stderr)"
            if _is_session_failure(err_text):
                raise YTDLPSessionBlockedError(
                    f"Source rejected request for {url}: {last_line[:500]}"
                )
            raise YTDLPError(f"Failed to download {url}: {last_line[:500]}")

        return Path(stdout.decode().strip()).resolve()
