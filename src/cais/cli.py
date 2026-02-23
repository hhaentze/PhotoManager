import argparse
import logging
import sys
from pathlib import Path
from typing import Dict, List

from rich.console import Console
from rich.table import Table
from rich.tree import Tree

from cais.db import IndexDB
from cais.logger import setup_logging
from cais.reconciler import ScanAnalyzer, scan

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


def report_duplicates(exact_dupes: Dict[str, List[str]], perceptual_dupes: Dict[str, List[str]]) -> None:
    """Handles the differentiated duplicate presentation logic using rich Trees."""

    def print_dupe_tree(dupes: Dict[str, List[str]], dupe_type: str, color: str):
        if not dupes:
            console.print(f"\n[bold green]✓ No {dupe_type} found![/bold green]")
            return

        total_dupe_files = sum(len(paths) for paths in dupes.values())
        unique_assets = len(dupes)
        wasted_space_files = total_dupe_files - unique_assets

        console.print(
            f"\n[bold yellow]! Found {wasted_space_files} redundant files across {unique_assets} unique {dupe_type}.[/bold yellow]"
        )

        if wasted_space_files <= 10:
            for hash_val, paths in dupes.items():
                tree = Tree(f"📄 [bold {color}]{hash_val[:8]}...[/bold {color}]")
                for p in paths:
                    tree.add(f"[dim]{p}[/dim]")
                console.print(tree)
        else:
            log_path = Path(f"cais_{dupe_type.replace(' ', '_')}.log")
            with open(log_path, "w", encoding="utf-8") as f:
                for hash_val, paths in dupes.items():
                    f.write(f"Hash: {hash_val}\n")
                    for p in paths:
                        f.write(f"  {p}\n")
                    f.write("\n")
            console.print(f"[dim]* Too many {dupe_type} to display. Details written to {log_path.resolve()}[/dim]")

    # Print differentiated reports
    print_dupe_tree(exact_dupes, "exact binary duplicates", "cyan")
    print_dupe_tree(perceptual_dupes, "visual duplicates", "magenta")


def run_scan(db_path: Path, root_dir: Path, scan_dir: Path, dry_run: bool = True, do_perceptual: bool = False) -> None:
    db = get_db_or_exit(db_path)

    try:
        # 1. Gather Context
        with console.status("[bold blue]Loading known state from database..."):
            known_state = db.get_known_state()
            db_exact = db.get_duplicates()
            db_perceptual = db.get_perceptual_duplicates() if do_perceptual else {}

        # 2. Execute Scan
        results = scan(scan_dir, known_state, do_perceptual)

        # 3. Analyze Results
        analyzer = ScanAnalyzer(root_dir, scan_dir, known_state)
        report = analyzer.analyze(results, db_exact, db_perceptual)

        # 4. Print Summary UI
        summary_table = Table(show_header=False, box=None)
        summary_table.add_column("Metric", style="bold")
        summary_table.add_column("Value", style="cyan")
        summary_table.add_row("[-] Unchanged files:", str(report.unchanged_count))
        summary_table.add_row("[-] New/Modified files to hash:", str(report.new_modified_count))
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
        report_duplicates(report.exact_dupes, report.perceptual_dupes)

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
    db_file = root_path / ".cais.db"

    # Execute the bound function dynamically
    args.func(args, db_file, root_path)


if __name__ == "__main__":
    main()
