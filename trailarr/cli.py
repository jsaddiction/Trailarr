"""CLI Interface for Trailarr."""

import logging
from dataclasses import dataclass
from argparse import ArgumentParser

from trailarr import __app_name__, __description__, __version__
from trailarr.app import TrailArr


@dataclass
class CLIConfig:
    """Trailarr CLI Configuration"""

    tmdb: int = None
    all: bool = False
    quiet: bool = False
    parser: ArgumentParser = None


def get_arguments() -> CLIConfig:
    """Collect arguments passed by user."""
    parser = ArgumentParser(prog=__app_name__, description=__description__)
    parser.add_argument(
        "-v", "--version", action="version", version=__version__, help="Show the name and version number"
    )
    parser.add_argument("-tmdb", metavar="TMDB id", dest="tmdb", help="TMDB id of the movie", type=int, default=None)
    parser.add_argument("-all", action="store_true", dest="all", help="Process all movies in Radarr", default=False)
    parser.add_argument("-quiet", action="store_true", dest="quiet", help="Suppress console output", default=False)

    cfg = parser.parse_args()
    return CLIConfig(tmdb=cfg.tmdb, all=cfg.all, quiet=cfg.quiet, parser=parser)


def config_logging(app: TrailArr, quiet: bool = False):
    """Configure logging for console mode."""
    console_level = 100 if quiet else app.cfg.log_level.upper()
    for handler in logging.getLogger().handlers:
        if handler.name == "file":
            handler.setLevel(100)
        elif handler.name == "console":
            handler.setLevel(console_level)


def main():
    """Run the application."""
    app = TrailArr()
    log = logging.getLogger("Trailarr.CLI")

    args = get_arguments()
    config_logging(app, args.quiet)

    try:
        if args.all and args.tmdb is None:
            app.process_all()
        elif args.tmdb and not args.all:
            movie = app.radarr.get_movie_by_id(args.tmdb)
            if not movie:
                log.warning("TMDB id %s not found in Radarr.", args.tmdb)
                return
            app.process_movie(movie)
        else:
            log.warning("You must specify a TMDB id or use the -all flag.")
            args.parser.print_help()
    except KeyboardInterrupt:
        log.info("Trailarr has been stopped")
    except Exception:
        log.exception("Unexpected error during processing")
    finally:
        # ALWAYS print summary (even in quiet mode) - bypasses logging system
        from trailarr.report import generate_summary_report
        summary = generate_summary_report(app.run_stats, app.state_manager)
        print(summary)

    app.exit()
