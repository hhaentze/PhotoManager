"""Shared rich console and output helpers, so every tool looks the same."""

from typing import Iterable, Optional, Tuple

from rich.console import Console
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeRemainingColumn,
)
from rich.table import Table

console = Console()


def make_progress() -> Progress:
    """Standard determinate progress bar (spinner + description + bar + ETA)."""
    return Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        TimeRemainingColumn(),
    )


def summary_table(rows: Iterable[Tuple[str, str]], title: Optional[str] = None) -> Table:
    """Two-column metric/value summary table used by the CLIs."""
    table = Table(show_header=False, box=None, title=title)
    table.add_column("Metric", style="bold")
    table.add_column("Value", style="cyan")
    for metric, value in rows:
        table.add_row(metric, value)
    return table
