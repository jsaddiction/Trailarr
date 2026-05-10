"""Summary report generation for trailer processing runs."""

from trailarr.providers.state import ProviderStateManager
from trailarr.stats import RunStats


def generate_summary_report(stats: RunStats, state_manager: ProviderStateManager) -> str:
    """Generate human-readable summary report.

    Args:
        stats: Run statistics
        state_manager: Provider state manager for checking rate limits

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

    lines.append("=" * 60)

    return "\n".join(lines)
