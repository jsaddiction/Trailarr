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
            status = f"⏸ Rate limited until {expires_at.strftime('%Y-%m-%d %H:%M UTC')}"
        elif run_state.auth_failed:
            status = "✗ Authentication failed"
        else:
            status = "✓"

        lines.append(f"  {provider_name}: {status} ({run_state.request_count} requests)")

    # Collect warnings
    warnings = stats.all_warnings()
    if warnings:
        lines.append("")
        lines.append(f"Warnings: {len(warnings)}")
        # Limit to 10 warnings to avoid overwhelming output
        for warning in warnings[:10]:
            lines.append(f"  • {warning}")
        if len(warnings) > 10:
            lines.append(f"  ... and {len(warnings) - 10} more")

    # Collect errors
    errors = stats.all_errors()
    if errors:
        lines.append("")
        lines.append(f"Errors: {len(errors)}")
        # Limit to 10 errors to avoid overwhelming output
        for error in errors[:10]:
            lines.append(f"  • {error}")
        if len(errors) > 10:
            lines.append(f"  ... and {len(errors) - 10} more")

    lines.append("=" * 60)

    return "\n".join(lines)
