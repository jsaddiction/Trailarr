"""Summary report generation for trailer processing runs."""

from datetime import timedelta

from trailarr.db import DB
from trailarr.providers.state import ProviderStateManager
from trailarr.stats import RunStats


def generate_summary_report(
    stats: RunStats,
    state_manager: ProviderStateManager,
    db: DB | None = None,
    source_block_minutes: int = 1440,
) -> str:
    """Generate human-readable summary report.

    Args:
        stats: Run statistics
        state_manager: Provider state manager for checking rate limits
        db: Database (optional; if provided, the report lists currently-blocked
            download sources and the count of broken URLs each affects)
        source_block_minutes: TTL used to interpret blocked_at_utc timestamps

    Returns:
        Formatted summary report string
    """
    lines = [
        "=" * 60,
        "Trailarr Run Summary",
        "=" * 60,
        f"Movies Processed: {stats.movies_processed}",
        f"Trailers Added: {stats.trailers_added}",
        f"Trailers Upgraded: {stats.trailers_upgraded}",
        "",
        "Provider Status:",
    ]

    # Report status for each provider
    for provider_name, run_state in stats.provider_states.items():
        # Check rate limit status from DB
        is_limited, expires_at = state_manager.is_rate_limited(provider_name)

        if is_limited and expires_at:
            status = f"[PAUSED] Rate limited until {expires_at.strftime('%Y-%m-%d %H:%M UTC')}"
        elif run_state.auth_failed:
            status = "[FAIL] Authentication failed"
        elif run_state.transient_error_count > 0:
            status = f"[WARN] {run_state.transient_error_count} transient errors"
        else:
            status = "[OK]"

        # Show breakdown: requests (failures if any)
        if run_state.transient_error_count > 0:
            detail = f"({run_state.request_count} requests, {run_state.transient_error_count} errors)"
        else:
            detail = f"({run_state.request_count} requests)"

        lines.append(f"  {provider_name}: {status} {detail}")

    # Show total transient errors if any occurred
    total_errors = stats.total_transient_errors()
    if total_errors > 0:
        lines.append("")
        lines.append(f"Note: {total_errors} transient error(s) - affected movies will retry on next run")

    # Currently-blocked download sources. Omitted when nothing is blocked.
    if db is not None:
        blocked = db.get_blocked_sources(source_block_minutes)
        if blocked:
            lines.append("")
            lines.append(f"Blocked Download Sources ({len(blocked)}):")
            for source, blocked_at in blocked:
                expires_at = blocked_at + timedelta(minutes=source_block_minutes)
                affected = db.count_broken_urls_for_source(source)
                lines.append(
                    f"  {source}: blocked at {blocked_at.strftime('%Y-%m-%d %H:%M UTC')}, "
                    f"expires {expires_at.strftime('%Y-%m-%d %H:%M UTC')}, "
                    f"{affected} affected URL(s)"
                )

    # Movies with no trailer anywhere (no local file, no usable online source).
    # One bare TMDB URL in the header is enough — most mail clients auto-linkify
    # it, and keeping the link count constant avoids spam-classifier escalation
    # as the trailerless list grows.
    if stats.movies_without_trailers:
        lines.append("")
        lines.append(f"Movies Without Trailers ({len(stats.movies_without_trailers)}):")
        lines.append("Add some content for these movies at https://www.themoviedb.org/")
        for _tmdb_id, title in sorted(stats.movies_without_trailers, key=lambda x: x[1]):
            lines.append(f"  - {title}")

    lines.append("=" * 60)

    return "\n".join(lines)
