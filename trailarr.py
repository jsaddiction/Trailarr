#!/usr/bin/env python
"""Main Entry Point for TrailArr."""

import logging
import signal
from trailarr.app import TrailArr


def _raise_keyboard_interrupt(signum, _frame):
    raise KeyboardInterrupt(f"Received signal {signal.Signals(signum).name}")


if __name__ == "__main__":
    # SIGTERM (docker stop, kill -TERM) follows the same graceful path as SIGINT.
    signal.signal(signal.SIGTERM, _raise_keyboard_interrupt)

    # NOTE: Don't call `logging.getLogger("TrailArr")` here. TrailArr.__init__
    # runs `dictConfig(... disable_existing_loggers=True)`, which would disable
    # any "TrailArr" logger created before that call — and since getLogger is
    # name-keyed, app.py's `self.log = logging.getLogger("TrailArr")` would
    # then receive the disabled instance and silently drop every message.
    app: TrailArr | None = None

    try:
        app = TrailArr()  # configure_logging runs inside __init__
        app.run()
    except KeyboardInterrupt:
        if app is not None:
            app.exit("User Terminated Script.")
        raise
    except SystemExit:
        # Re-raise without wrapping — app.exit() uses this for normal termination.
        raise
    except Exception:
        # If init failed, we can't use app.log; fall back to root logger.
        logger = app.log if app is not None else logging.getLogger()
        logger.exception("Unexpected error")
        if app is not None:
            app.exit("Unexpected error occurred")
        raise
    finally:
        # Generate report BEFORE resource teardown — it queries provider state
        # from the DB. Skipped if init failed (app still None).
        if app is not None:
            try:
                from trailarr.report import generate_summary_report
                summary = generate_summary_report(
                    app.run_stats,
                    app.state_manager,
                    db=app.db,
                    source_block_minutes=app.cfg.source_block_minutes,
                )
                print(summary)
            except Exception:
                app.log.exception("Failed to generate summary report")
            finally:
                app.shutdown()
