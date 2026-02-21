import argparse
import logging
import sys
from pathlib import Path

from rich.console import Console
from rich.table import Table
from rich.tree import Tree

from cais.db import IndexDB
from cais.logger import setup_logging
from cais.reconciler import check_external_path, scan_and_reconcile

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


def report_duplicates(db: IndexDB) -> None:
    """Handles the duplicate presentation logic using rich Trees."""
    dupes = db.get_duplicates()
    if not dupes:
        console.print("\n[bold green]✓ No duplicate files found![/bold green]")
        return

    total_dupe_files = sum(len(paths) for paths in dupes.values())
    unique_assets = len(dupes)
    wasted_space_files = total_dupe_files - unique_assets

    console.print(
        f"\n[bold yellow]! Found {wasted_space_files} redundant files across {unique_assets} unique assets.[/bold yellow]"
    )

    if wasted_space_files <= 10:
        for file_hash, paths in dupes.items():
            tree = Tree(f"📄 [bold cyan]{file_hash[:8]}...[/bold cyan]")
            for p in paths:
                tree.add(f"[dim]{p}[/dim]")
            console.print(tree)
    else:
        log_path = Path("cais_duplicates.log")
        with open(log_path, "w", encoding="utf-8") as f:
            for file_hash, paths in dupes.items():
                f.write(f"Hash: {file_hash}\n")
                for p in paths:
                    f.write(f"  {p}\n")
                f.write("\n")
        console.print(f"[dim]* Too many duplicates to display. Details written to {log_path.resolve()}[/dim]")


def run_scan_or_update(root_dir: Path, db_path: Path, dry_run: bool) -> None:
    """Orchestrates the disk walk, reconciliation, and database updates."""
    db = get_db_or_exit(db_path)

    try:
        with console.status("[bold blue]Loading known state from database..."):
            known_state = db.get_known_state()

        console.print(f"[*] Found [cyan]{len(known_state)}[/cyan] known files in database.")

        with console.status("[bold blue]Scanning disk and hashing modified files..."):
            result = scan_and_reconcile(root_dir, known_state)

        # Print Summary Panel
        summary_table = Table(show_header=False, box=None)
        summary_table.add_column("Metric", style="bold")
        summary_table.add_column("Value", style="cyan")
        summary_table.add_row("[-] Unchanged files:", str(result.unchanged_count))
        summary_table.add_row("[-] New/Modified files to hash:", str(len(result.to_upsert)))
        summary_table.add_row("[-] Missing files (removed from disk):", str(len(result.missing_on_disk)))
        console.print(summary_table)

        if dry_run:
            console.print("\n[bold yellow]* DRY RUN: No changes committed to the database.[/bold yellow]")
        else:
            if result.to_upsert:
                console.print(f"[*] Committing [green]{len(result.to_upsert)}[/green] hashed files to database...")
                db.upsert_files(result.to_upsert)
            if result.missing_on_disk:
                console.print(f"[*] Removing [red]{len(result.missing_on_disk)}[/red] orphaned paths from database...")
                db.remove_paths(result.missing_on_disk)
            console.print("[bold green]✓ Update complete.[/bold green]")

        report_duplicates(db)

    finally:
        db.close()


# --- Command Handlers ---


def handle_init(args, db_file: Path, root_path: Path):
    if db_file.exists():
        console.print(f"[bold red]Error:[/bold red] Database already exists at {db_file}")
        sys.exit(1)

    console.print(f"[*] Initializing database [bold cyan]'{args.name}'[/bold cyan] at {root_path}...")
    db = IndexDB(db_file, args.name)  # Note: passed db_name directly based on your init schema
    db.close()
    console.print("[bold green]✓ Initialization complete.[/bold green]")


def handle_scan(args, db_file: Path, root_path: Path):
    console.print("[bold]Scanning for differences (dry run)...[/bold]")
    run_scan_or_update(root_path, db_file, dry_run=True)


def handle_update(args, db_file: Path, root_path: Path):
    console.print("[bold]Scanning and updating database...[/bold]")
    run_scan_or_update(root_path, db_file, dry_run=False)


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


def handle_check_path(args, db_file: Path, root_path: Path):
    ext_path = Path(args.path)
    if not ext_path.exists() or not ext_path.is_dir():
        console.print(f"[bold red]Error:[/bold red] Path {ext_path} does not exist or is not a directory.")
        sys.exit(1)

    db = get_db_or_exit(db_file)
    try:
        with console.status("[bold blue]Loading known database hashes into memory..."):
            known_hashes = db.get_all_hashes()

        with console.status(f"[bold blue]Scanning external path: {ext_path.resolve()}..."):
            known_files, unknown_files = check_external_path(ext_path, known_hashes)

        console.print("\n[bold]External Path Check Results[/bold]")
        console.print(f"[-] Files already safely in your database: [green]{len(known_files)}[/green]")
        console.print(f"[-] New, unbacked-up files found: [yellow]{len(unknown_files)}[/yellow]")

        if unknown_files:
            log_path = Path("cais_unknown_external.log")
            with open(log_path, "w", encoding="utf-8") as f:
                for p in unknown_files:
                    f.write(f"{p}\n")
            console.print(f"[dim]* List of unbacked-up files written to {log_path.resolve()}[/dim]")
    finally:
        db.close()


def main():
    setup_logging(level=logging.DEBUG)  # Keep logging for file-based debug traces if needed

    parser = argparse.ArgumentParser(description="CAIS: Content-Addressed Indexing System for Media")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Mode 1: Self-Management
    parser_init = subparsers.add_parser("init", help="Initialize a new database here")
    parser_init.add_argument("name", help="Name for this database instance (e.g., 'main')")
    parser_init.set_defaults(func=handle_init)

    parser_scan = subparsers.add_parser("scan", help="Check for changes without updating DB")
    parser_scan.set_defaults(func=handle_scan)

    parser_update = subparsers.add_parser("update", help="Scan and update the database")
    parser_update.set_defaults(func=handle_update)

    parser_status = subparsers.add_parser("status", help="Print database statistics")
    parser_status.set_defaults(func=handle_status)

    parser_check = subparsers.add_parser("check-path", help="Compare external folder against own entries")
    parser_check.add_argument("path", help="External path to check")
    parser_check.set_defaults(func=handle_check_path)

    args = parser.parse_args()

    # Paths
    root_path = Path.cwd()
    db_file = root_path / ".cais.db"

    # Execute the bound function dynamically
    args.func(args, db_file, root_path)


if __name__ == "__main__":
    main()
