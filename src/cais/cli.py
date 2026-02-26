import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Dict

from rich.console import Console
from rich.table import Table
from rich.tree import Tree

from cais.db import IndexDB
from cais.logger import setup_logging
from cais.reconciler import DuplicateGroup, ScanAnalyzer

logger = logging.getLogger(__name__)
console = Console()


def format_size(size_bytes: int) -> str:
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

    if not duplicates:
        console.print("\n[bold green]✓ No duplicates found![/bold green]")
        return

    # --- Stats ---
    exact_count = sum(1 for group in duplicates.values() for _, t in group.duplicates if t == "hash")
    perceptual_count = sum(1 for group in duplicates.values() for _, t in group.duplicates if t == "phash")
    total_redundant = exact_count + perceptual_count

    console.print(
        f"\n[bold yellow]! Found {total_redundant} redundant files "
        f"({exact_count} exact, {perceptual_count} perceptual).[/bold yellow]"
    )

    # --- Write unified log ---
    log_path = output_dir / "cais_duplicates.log"
    json_path = output_dir / "cais_duplicates.json"

    with open(log_path, "w", encoding="utf-8") as f:
        for i, group in enumerate(duplicates.values(), start=1):
            f.write(f"GROUP {i}\n")
            if group.original is not None:
                f.write(f"  Representative: {group.original}\n")
            for path, match_type in group.duplicates:
                f.write(f"  Duplicate ({match_type}): {path}\n")
            f.write("\n")

    # JSON (structured)
    json_data = {
        group.original or f"group_{i}": {
            "representative": group.original,
            "duplicates": group.duplicates,
        }
        for i, group in enumerate(duplicates.values())
    }

    with open(json_path, "w", encoding="utf-8") as jf:
        json.dump(json_data, jf, indent=4)

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

    console.print(f"[dim]* Details written to:\n  - {log_path.resolve()}\n  - {json_path.resolve()}[/dim]")


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
        summary_table = Table(show_header=False, box=None)
        summary_table.add_column("Metric", style="bold")
        summary_table.add_column("Value", style="cyan")
        summary_table.add_row("[-] Unchanged files:", str(len(report.on_disk)))
        summary_table.add_row("[-] New/Modified files to hash:", str(len(report.to_upsert)))
        summary_table.add_row("[-] Missing files:", str(len(report.missing_on_disk)))
        console.print(summary_table)

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

        # 6. Print Duplicates UI
        report_duplicates(report.duplicates, db_path.parent)

    finally:
        db.close()


# --- Command Handlers ---


def handle_init(args, db_file: Path, root_path: Path):
    if db_file.exists():
        console.print(f"[bold red]Error:[/bold red] Database already exists at {db_file}")
        sys.exit(1)

    console.print(f"[*] Initializing database [bold cyan]'{args.name}'[/bold cyan] at {root_path}...")
    db = IndexDB(db_file, args.name)
    db.close()
    console.print("[bold green]✓ Initialization complete.[/bold green]")


def handle_scan(args, db_file: Path, root_path: Path):

    if args.update and args.path is not None:
        console.print("[bold red]Error:[/bold red] External Paths cannot be added to database.")
        sys.exit(1)

    scan_dir = root_path if args.path is None else Path(args.path).resolve()

    console.print("[bold]Scanning for differences...[/bold]")
    run_scan(
        db_path=db_file,
        root_dir=root_path,
        scan_dir=scan_dir,
        dry_run=not args.update,
        do_perceptual=args.perceptual,
    )


def handle_status(args, db_file: Path, root_path: Path):
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


def main():
    setup_logging(level=logging.INFO)

    parser = argparse.ArgumentParser(description="CAIS: Content-Addressed Indexing System for Media")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Mode 1: Self-Management
    parser_init = subparsers.add_parser("init", help="Initialize a new database here")
    parser_init.add_argument("name", help="Name for this database instance (e.g., 'main')")
    parser_init.set_defaults(func=handle_init)

    parser_scan = subparsers.add_parser("scan", help="Check for changes without updating DB")
    parser_scan.add_argument("path", nargs="?", default=None, help="External path to check")
    parser_scan.add_argument("--perceptual", action="store_true", help="Calculate perceptual hashes for images")
    parser_scan.add_argument("--update", action="store_true", help="Update the database")
    parser_scan.set_defaults(func=handle_scan)

    parser_status = subparsers.add_parser("status", help="Print database statistics")
    parser_status.set_defaults(func=handle_status)

    args = parser.parse_args()

    # Paths
    root_path = Path.cwd()
    db_dir = Path(".cais")
    db_dir.mkdir(exist_ok=True)
    db_file = root_path / db_dir / ".cais.db"

    # Execute the bound function dynamically
    args.func(args, db_file, root_path)


if __name__ == "__main__":
    main()
