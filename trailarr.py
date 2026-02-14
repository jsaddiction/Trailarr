#!/usr/bin/env python
"""Main Entry Point for TrailArr."""

from trailarr.app import TrailArr

if __name__ == "__main__":
    app = TrailArr()
    try:
        app.run()
    except KeyboardInterrupt:
        app.exit("User Terminated Script.")
