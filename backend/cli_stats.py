"""
Usage: python -m backend stats --days 7
       python -m backend stats --days 30
       python -m backend stats --help

Generate a metrics report from the local SQLite database.
"""

import asyncio
import sys
import argparse
from pathlib import Path
from rich.console import Console
from rich.table import Table
from rich import box
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn

# stderr console for status messages, stdout for the report itself
_err_con = Console(stderr=True)
_out_con = Console()  # stdout for final output


def _format_usd(cost: float) -> str:
    """Format a USD cost consistently."""
    if cost >= 100:
        return f"${cost:,.2f}"
    elif cost >= 1:
        return f"${cost:.4f}"
    elif cost >= 0.0001:
        return f"${cost:.6f}"
    else:
        return "$0.00"


def _format_number(n: int) -> str:
    """Format a number with comma separators."""
    return f"{n:,}"


def _format_latency(ms: float) -> str:
    """Format latency in a human-readable way."""
    if ms >= 1000:
        return f"{ms / 1000:.2f}s"
    elif ms >= 1:
        return f"{ms:.0f} ms"
    else:
        return f"{ms:.1f} ms"


async def main(days: int = 7):
    from backend.core.metrics import MetricsCollector

    db_path = Path("data/metrics.db")

    # Check if db exists
    if not db_path.exists():
        _err_con.print(f"[red]Error:[/red] Metrics database not found at [bold]{db_path}[/bold]")
        _err_con.print()
        _err_con.print("  [yellow]Why:[/yellow] No metrics have been recorded yet, or the database was deleted.")
        _err_con.print("  [yellow]Fix:[/yellow]  Run the application first to generate metrics, then re-run this command.")
        _err_con.print()
        sys.exit(2)

    m = MetricsCollector(str(db_path))

    # Progress indicator while generating the report
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(bar_width=None),
        console=_err_con,
    ) as progress:
        progress.add_task(description="[cyan]Generating metrics report...[/cyan]", total=None)
        report = await m.weekly_report()

    total_turns = report.get("total_turns", 0)

    if total_turns == 0:
        _err_con.print(f"[yellow]Warning:[/yellow] No metric data found in the last {days} days.")
        _err_con.print("  The database exists but is empty for the requested period.")
        _err_con.print("  [dim]Try increasing --days or run the application first.[/dim]")
        sys.exit(1)

    # -- Build the report on stdout --
    divider = "=" * 48
    _out_con.print(f"\n[bold]{divider}[/bold]")
    _out_con.print(f"  [bold yellow]Amalgam[/bold yellow] — Metrics Report [dim](last {days} days)[/dim]")
    _out_con.print(f"[bold]{divider}[/bold]\n")

    # Summary table
    summary = Table(box=box.SIMPLE, show_header=False, padding=(0, 2))
    summary.add_column("Metric", style="cyan")
    summary.add_column("Value", style="bold")

    summary.add_row("Total turns", _format_number(total_turns))
    summary.add_row("Total cost", _format_usd(report.get("total_cost_usd", 0)))
    summary.add_row("Total tokens", _format_number(report.get("total_tokens", 0)))
    summary.add_row("Avg latency", _format_latency(report.get("avg_latency_ms", 0)))
    summary.add_row("Tool calls", _format_number(report.get("total_tool_calls", 0)))
    summary.add_row("Avg memory hits", f'{report.get("avg_memory_hits_per_turn", 0):.1f} per turn')

    _out_con.print(summary)

    # Top models
    top_models = report.get("top_models", [])
    if top_models:
        _out_con.print()
        model_table = Table(
            title="Models Used",
            box=box.ROUNDED,
            header_style="bold cyan",
            title_style="bold",
        )
        model_table.add_column("Model", style="cyan")
        model_table.add_column("Turns", justify="right")
        model_table.add_column("Cost", justify="right")

        for entry in top_models:
            model_name = entry.get("model", "?")
            uses = entry.get("uses", 0)
            cost = entry.get("cost", 0.0)
            model_table.add_row(model_name, _format_number(uses), _format_usd(cost))

        _out_con.print(model_table)

    # Top skills
    top_skills = report.get("top_skills", [])
    if top_skills:
        _out_con.print()
        skill_table = Table(
            title="Skills Used",
            box=box.ROUNDED,
            header_style="bold cyan",
            title_style="bold",
        )
        skill_table.add_column("Skill", style="cyan")
        skill_table.add_column("Uses", justify="right")

        for entry in top_skills:
            skill_name = entry.get("skill_used", "?")
            uses = entry.get("uses", 0)
            skill_table.add_row(skill_name, _format_number(uses))

        _out_con.print(skill_table)

    _out_con.print()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Generate an Amalgam metrics report from the local database.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m backend stats              Last 7 days
  python -m backend stats --days 30    Last 30 days
  python -m backend stats --days 0     All time
        """,
    )
    parser.add_argument(
        "--days",
        type=int,
        default=7,
        help="Number of days to include in the report (default: 7, use 0 for all time)",
    )
    parser.add_argument(
        "--db",
        type=str,
        default="data/metrics.db",
        help="Path to the metrics database (default: data/metrics.db)",
    )

    args = parser.parse_args()

    if args.days < 0:
        _err_con.print("[red]Error:[/red] --days must be 0 or greater.")
        _err_con.print("  [yellow]Usage:[/yellow] python -m backend stats --days 7")
        sys.exit(2)

    try:
        asyncio.run(main(args.days))
    except KeyboardInterrupt:
        _err_con.print("\n[yellow]Interrupted[/yellow]")
        sys.exit(0)
    except Exception as e:
        _err_con.print(f"[red]Error generating report:[/red] {e}")
        sys.exit(1)
