"""CLI Interface for Trailarr."""

import logging
import signal
from dataclasses import dataclass
from argparse import ArgumentParser

from trailarr import __app_name__, __description__, __version__
from trailarr.app import TrailArr


def _raise_keyboard_interrupt(signum, _frame):
    raise KeyboardInterrupt(f"Received signal {signal.Signals(signum).name}")


@dataclass
class CLIConfig:
    """Trailarr CLI Configuration"""

    tmdb: int | None = None
    all: bool = False
    quiet: bool = False
    migrate: bool = False
    parser: ArgumentParser | None = None


def get_arguments() -> CLIConfig:
    """Collect arguments passed by user."""
    parser = ArgumentParser(prog=__app_name__, description=__description__)
    parser.add_argument(
        "-v", "--version", action="version", version=__version__, help="Show the name and version number"
    )
    parser.add_argument("-t", "--tmdb", metavar="ID", dest="tmdb", help="Process a specific movie by TMDB ID", type=int, default=None)
    parser.add_argument("-a", "--all", action="store_true", dest="all", help="Process all movies in Radarr", default=False)
    parser.add_argument("-q", "--quiet", action="store_true", dest="quiet", help="Suppress console output", default=False)
    parser.add_argument("--migrate", action="store_true", dest="migrate", help="Run pending data migrations", default=False)

    cfg = parser.parse_args()
    return CLIConfig(tmdb=cfg.tmdb, all=cfg.all, quiet=cfg.quiet, migrate=cfg.migrate, parser=parser)


def config_logging(app: TrailArr, quiet: bool = False):
    """Configure logging for console mode.

    File handler always uses the configured log level.
    Console handler uses the configured level, or is suppressed with --quiet.
    """
    configured_level = app.cfg.log_level.upper()
    console_level = 100 if quiet else configured_level
    for handler in logging.getLogger().handlers:
        if handler.name == "file":
            handler.setLevel(configured_level)
        elif handler.name == "console":
            handler.setLevel(console_level)


def main():
    """Run the application."""
    # SIGTERM (docker stop, kill -TERM) follows the same graceful path as SIGINT.
    signal.signal(signal.SIGTERM, _raise_keyboard_interrupt)

    args = get_arguments()

    app = TrailArr()  # Migrations run at end of __init__
    log = logging.getLogger("TrailArr.CLI")

    config_logging(app, args.quiet)

    try:
        # Handle --migrate flag (migrations already ran in __init__, just exit)
        if args.migrate:
            log.info("Migrations complete!")
            app.exit()
            return

        # Normal processing
        if args.all and args.tmdb is None:
            app.process_all()
        elif args.tmdb and not args.all:
            movie = app.radarr.get_movie_by_id(args.tmdb)
            if not movie:
                log.warning("TMDB id %s not found in Radarr.", args.tmdb)
                return
            app.process_movie(movie)
        else:
            log.warning("You must specify --tmdb ID or --all (not both).")
            args.parser.print_help()
            return
    except KeyboardInterrupt:
        log.info("Trailarr has been stopped")
    except Exception:
        log.exception("Unexpected error during processing")
    finally:
        # Only print summary if we actually processed movies
        if not args.migrate and (args.all or args.tmdb):
            from trailarr.report import generate_summary_report
            summary = generate_summary_report(app.run_stats, app.state_manager)
            print(summary)

    app.exit()
