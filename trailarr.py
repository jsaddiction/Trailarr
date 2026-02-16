#!/usr/bin/env python
"""Main Entry Point for TrailArr."""

import logging
from trailarr.app import TrailArr

if __name__ == "__main__":
    app = TrailArr()  # Migrations run at end of __init__
    log = logging.getLogger("TrailArr")

    try:
        app.run()
    except KeyboardInterrupt:
        app.exit("User Terminated Script.")
    except Exception:
        log.exception("Unexpected error")
        app.exit("Unexpected error occurred")
    finally:
        # Print summary report (bypasses logging system)
        from trailarr.report import generate_summary_report
        summary = generate_summary_report(app.run_stats, app.state_manager)
        print(summary)
