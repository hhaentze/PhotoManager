import logging
import sys
from pathlib import Path
from typing import Dict, Optional

import typer
from rich.table import Table
from rich.tree import Tree

from cais.db import IndexDB
from cais.reconciler import AnalysisReport, DuplicateGroup, ScanAnalyzer, compare_dbs
from photomanager.common import contract
from photomanager.common.console import console, summary_table
from photomanager.common.logging import setup_logging

logger = logging.getLogger(__name__)


def format_size(size_bytes: float) -> str:
    """Converts bytes to a human-readable format."""
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size_bytes < 1024.0:
            return f"{size_bytes:.2f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.2f} PB"


def get_db_or_exit(db_file: Path) -> IndexDB:
    """Helper to ensure DB exists before running operations."""
    if not db_file.exists():
        console.print("[bold red]Error:[/bold red] No .cais.db found in the current directory. Run 'init' first.")
        sys.exit(1)
    return IndexDB(db_file)


def report_duplicates(duplicates: Dict[str, DuplicateGroup], output_dir: Path) -> None:
    """Report duplicate groups (exact + perceptual) in a unified format."""

    # --- Stats ---
    exact_count = sum(1 for group in duplicates.values() for _, t in group.duplicates if t == "hash")
    perceptual_count = sum(1 for group in duplicates.values() for _, t in group.duplicates if t == "phash")
    total_redundant = exact_count + perceptual_count

    if duplicates:
        console.print(
            f"\n[bold yellow]! Found {total_redundant} redundant files "
            f"({exact_count} exact, {perceptual_count} perceptual).[/bold yellow]"
        )
    else:
        console.print("\n[bold green]✓ No duplicates found![/bold green]")

    # --- Write unified log ---
    log_path = output_dir / "cais_duplicates.log"
    json_path = output_dir / contract.DUPLICATES

    with open(log_path, "w", encoding="utf-8") as f:
        for i, group in enumerate(duplicates.values(), start=1):
            f.write(f"GROUP {i}\n")
            if group.original is not None:
                f.write(f"  Representative: {group.original}\n")
            for path, match_type in group.duplicates:
                f.write(f"  Duplicate ({match_type}): {path}\n")
            f.write("\n")

    # JSON (structured, via the shared contract)
    contract.dump(json_path, contract.build_duplicates_payload(duplicates.values()))

    # --- Rich Tree (if small enough) ---
    if total_redundant < 30:
        tree = Tree("[bold]Duplicates[/bold]")

        for i, group in enumerate(duplicates.values()):
            # Use representative name as branch label
            label = (
                f"[bold green]{Path(group.original).name}[/bold green]"  #
                if group.original
                else f"[bold]Group {i}[/bold]"
            )

            branch = tree.add(label)
            for path, match_type in group.duplicates:
                color = "cyan" if match_type == "hash" else "magenta"
                branch.add(f"[{color}]{path} ({match_type})[/{color}]")

        console.print(tree)
    else:
        console.print("[dim]* Too many duplicates to display.[/dim]")


def print_and_save_report(report: AnalysisReport, output_dir: Path) -> None:
    contract.dump(output_dir / contract.MISSING_ON_DISK, report.missing_on_disk)
    contract.dump(output_dir / contract.NEW_FILES, report.new_files)
    new_and_modified_files = [f for f, _, _, _ in report.to_upsert]
    contract.dump(output_dir / contract.NEW_AND_MODIFIED, new_and_modified_files)

    report_duplicates(report.duplicates, output_dir)
    console.print(f"[dim]* Details written to:\n  - {output_dir.resolve()}[/dim]")


def run_scan(db_path: Path, root_dir: Path, scan_dir: Path, dry_run: bool = True, do_perceptual: bool = False) -> None:
    db = get_db_or_exit(db_path)

    try:
        # 1. Gather Context
        with console.status("[bold blue]Loading known state from database..."):
            known_state = db.get_known_state()

        # 2. Execute Scan
        analyzer = ScanAnalyzer(root_dir, scan_dir, known_state)
        results = analyzer.scan(do_perceptual)
        report = analyzer.analyze(results)

        # 4. Print Summary UI
        console.print(
            summary_table(
                [
                    ("[-] Unchanged files:", str(len(report.on_disk))),
                    ("[-] New/Modified files to hash:", str(len(report.to_upsert))),
                    ("[-] Missing files:", str(len(report.missing_on_disk))),
                ]
            )
        )

        # 5. Execute DB Updates
        if dry_run:
            console.print("\n[bold yellow]* DRY RUN: No changes committed to the database.[/bold yellow]")
        else:
            if report.to_upsert:
                db.upsert_files(report.to_upsert)
            if report.to_upsert_phash:
                unique_phashes = {row[0]: row for row in report.to_upsert_phash}.values()
                db.update_phashes(list(unique_phashes))
            if report.missing_on_disk:
                db.remove_paths(report.missing_on_disk)
            console.print("[bold green]✓ Update complete.[/bold green]")

        # 6. Print UI
        print_and_save_report(report, db_path.parent)

    finally:
        db.close()


app = typer.Typer(help="CAIS: Content-Addressed Indexing System for Media", no_args_is_help=True)


@app.callback()
def _configure() -> None:
    setup_logging(level=logging.INFO)


def _db_paths() -> tuple[Path, Path]:
    """Resolve the working directory and its .cais database file."""
    root_path = Path.cwd()
    db_dir = root_path / contract.CAIS_DIR
    db_dir.mkdir(exist_ok=True)
    return root_path, db_dir / ".cais.db"


@app.command()
def init(name: str = typer.Argument(..., help="Name for this database instance (e.g., 'main')")) -> None:
    """Initialize a new database here."""
    root_path, db_file = _db_paths()
    if db_file.exists():
        console.print(f"[bold red]Error:[/bold red] Database already exists at {db_file}")
        raise typer.Exit(1)

    console.print(f"[*] Initializing database [bold cyan]'{name}'[/bold cyan] at {root_path}...")
    db = IndexDB(db_file, name)
    db.close()
    console.print("[bold green]✓ Initialization complete.[/bold green]")


@app.command()
def scan(
    path: Optional[Path] = typer.Argument(None, help="External path to check"),
    perceptual: bool = typer.Option(False, "--perceptual", help="Calculate perceptual hashes for images"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Commit changes to the database (default: dry run)"),
) -> None:
    """Scan for changes. Writes to the database only when --yes is given."""
    root_path, db_file = _db_paths()

    if yes and path is not None:
        console.print("[bold red]Error:[/bold red] External Paths cannot be added to database.")
        raise typer.Exit(1)

    scan_dir = root_path if path is None else path.resolve()

    console.print("[bold]Scanning for differences...[/bold]")
    run_scan(
        db_path=db_file,
        root_dir=root_path,
        scan_dir=scan_dir,
        dry_run=not yes,
        do_perceptual=perceptual,
    )


@app.command()
def status() -> None:
    """Print database statistics."""
    _, db_file = _db_paths()
    db = get_db_or_exit(db_file)
    try:
        stats = db.get_status_stats()

        table = Table(title="Database Status", show_header=True, header_style="bold magenta")
        table.add_column("Metric", style="cyan")
        table.add_column("Value", justify="right", style="green")

        table.add_row("Database Name", stats["name"])
        table.add_row("Total File Locations", str(stats["locations"]))
        table.add_row("Unique Assets", str(stats["assets"]))
        table.add_row("Total Size", format_size(stats["size"]))

        console.print(table)

        duplicates = db.get_all_duplicates()
        report_duplicates(duplicates, db_file.parent)

    finally:
        db.close()


@app.command()
def compare(
    target: str = typer.Argument(..., help="Path to the external directory managed by cais"),
) -> None:
    """Compare this DB with another DB without scanning."""
    _, db_file = _db_paths()
    db1 = get_db_or_exit(db_file)
    db2_file = (Path(target) / contract.CAIS_DIR / ".cais.db").resolve()

    if not db2_file.exists():
        console.print(f"[bold red]Error:[/bold red] Target database not found at {db2_file}")
        raise typer.Exit(1)

    # Load DB2 in read-only mode implicitly by not calling init
    db2 = IndexDB(db2_file)
    try:
        state1 = db1.get_known_state()
        state2 = db2.get_known_state()
        report = compare_dbs(state1, state2)
    finally:
        db1.close()
        db2.close()

    total_dupes = sum(len(g.duplicates) for g in report.duplicates.values())
    console.print(
        summary_table(
            [
                ("[-] Files in Current DB:", str(len(state1))),
                ("[-] Files in Target DB:", str(len(state2))),
                ("[-] Unique files in Current DB:", str(len(report.missing_on_disk))),
                ("[-] Unique files in Target DB:", str(len(report.new_files))),
                ("[-] Redundant files in Target DB:", str(total_dupes)),
            ]
        )
    )

    print_and_save_report(report, db_file.parent)


def main():
    app()


if __name__ == "__main__":
    main()
