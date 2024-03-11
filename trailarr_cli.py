"""CLI Interface for Trailarr"""

import logging
from argparse import ArgumentParser
from src import __app_name__, __description__, __version__
from trailarr import TrailArr, CFG

app = TrailArr()


def get_arguments():
    """Collect arguments passed by user"""
    parser = ArgumentParser(prog=__app_name__, description=__description__)
    parser.add_argument(
        "-v", "--version", action="version", version=__version__, help="Show the name and version number"
    )
    parser.add_argument("-tmdb", metavar="TMDB id", dest="tmdb", help="TMDB id of the movie", type=int, default=None)
    parser.add_argument("-all", action="store_true", dest="all", help="Process all movies in Radarr", default=False)

    return parser.parse_args()


def main():
    """Run the application"""
    # Set console logger to the log level in the config
    for handler in logging.getLogger().handlers:
        if handler.name == "console":
            handler.setLevel(CFG.log_level.upper())
            break

    args = get_arguments()
    if args.all:
        app.process_all()

    elif args.tmdb:
        movie = app.radarr.get_movie_by_id(args.tmdb)
        if not movie:
            print(f"TMDB id {args.tmdb} not found in Radarr.")
            return
        app.process_movie(movie)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        app.log.info("Trailarr has been stopped")
        app.exit()
