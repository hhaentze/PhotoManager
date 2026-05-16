import json
import shutil
import time
from datetime import datetime
from pathlib import Path
from typing import List

from rich.console import Console
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeRemainingColumn,
)

console = Console()


def clean_empty_directories(root: Path, deleted_files: List[Path]) -> int:
    """
    Safely removes empty directories bottom-up after file deletions.
    Returns the count of successfully removed directories.
    """
    # 1. Collect all unique parent directories, excluding the root itself ('.')
    dirs_to_check = {parent for p in deleted_files for parent in p.parents if str(parent) != "."}

    # 2. Sort by depth descending (deepest folders first)
    sorted_dirs = sorted(dirs_to_check, key=lambda x: len(x.parts), reverse=True)
    removed_count = 0

    # 3. Safely attempt deletion
    for rel_dir in sorted_dirs:
        abs_dir = root / rel_dir
        try:
            # Check if it's a directory and appears empty before asking the OS to delete
            if abs_dir.is_dir() and not any(abs_dir.iterdir()):
                abs_dir.rmdir()  # OS-level safeguard: strictly fails if not empty
                removed_count += 1
        except OSError:
            pass  # Fails cleanly if the dir isn't actually empty (e.g., hidden files)

    return removed_count


def pull_cais_files(db2_path: str, root_dir: str = ".", update: bool = False):
    db2, root = Path(db2_path), Path(root_dir)
    update_json_path = Path(".cais/cais_new_and_modified_files.json")
    missing_json_path = Path(".cais/cais_missing_on_disk.json")

    if not update_json_path.exists() and not missing_json_path.exists():
        console.print("[bold red]Error:[/] No comparison JSON files found in .cais/")
        return

    rel_paths = []
    if update_json_path.exists():
        with open(update_json_path, "r", encoding="utf-8") as f:
            rel_paths = [Path(p) for p in json.load(f)]
    delete_paths = []
    if missing_json_path.exists():
        with open(missing_json_path, "r", encoding="utf-8") as f:
            delete_paths = [Path(p) for p in json.load(f)]

    # 3. Validate paths in db2 (for files we are pulling)
    missing_in_db2 = [p for p in rel_paths if not (db2 / p).is_file()]
    if missing_in_db2:
        console.print(f"[bold red]Error:[/] Missing {len(missing_in_db2)} files in '{db2}'.")
        console.print(f"First missing file: {missing_in_db2[0]}")
        return

    # 4. Skim target root directory
    existing_targets = [p for p in rel_paths if (root / p).is_file()]
    missing_targets_count = len(rel_paths) - len(existing_targets)
    existing_to_delete = [p for p in delete_paths if (root / p).is_file()]

    console.print("\n[bold magenta]Pull Skim Report[/bold magenta]")
    console.print("-" * 35)
    console.print(f"[cyan]Files to create (new):[/]     {missing_targets_count}")
    console.print(f"[yellow]Files to overwrite:[/]        {len(existing_targets)}")
    console.print(f"[red]Files to delete (to trash):[/] {len(existing_to_delete)}")

    if not update:
        return

    # 5. Execute Update Sequence
    console.print(f"\n[bold red]WARNING:[/] Pulling from [cyan]{db2}[/] to [cyan]{root}[/]")
    console.print("Operation starting in 6 seconds... Press Ctrl+C to cancel.")
    removed_dirs_count = 0

    try:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            TimeRemainingColumn(),
        ) as progress:
            # Countdown task
            countdown_task = progress.add_task("[yellow]Waiting to start...", total=60)
            for _ in range(60):
                time.sleep(0.1)
                progress.advance(countdown_task)

            # Define Trash Directories
            trash_base = Path(".trash") / datetime.now().strftime("%Y-%m-%d")
            trash_modified = trash_base / "modified"
            trash_deleted = trash_base / "deleted"

            # 6. Move files marked for deletion to trash
            if existing_to_delete:
                delete_task = progress.add_task("[red]Moving deleted files to trash...", total=len(existing_to_delete))
                for p in existing_to_delete:
                    trash_target = trash_deleted / p
                    trash_target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(root / p, trash_target)
                    progress.advance(delete_task)
                removed_dirs_count = clean_empty_directories(root, existing_to_delete)

            # 7. Backup existing files (to be overwritten) to trash
            if existing_targets:
                backup_task = progress.add_task("[blue]Backing up existing files...", total=len(existing_targets))
                for p in existing_targets:
                    trash_target = trash_modified / p
                    trash_target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(root / p, trash_target)
                    progress.advance(backup_task)

            # 8. Copy from db2 to root
            if rel_paths:
                copy_task = progress.add_task("[green]Copying files to root...", total=len(rel_paths))
                copied = 0
                for p in rel_paths:
                    dest = root / p
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(db2 / p, dest)
                    copied += 1
                    progress.advance(copy_task)

    except KeyboardInterrupt:
        console.print("\n[yellow]Operation cancelled by user.[/]")
        return

    # 9. Summary statistics
    console.print("\n[bold green]Update Successful![/bold green]")
    console.print("-" * 35)
    console.print(f"[blue]Files overwritten (backed up):[/] {len(existing_targets)} ({trash_modified})")
    console.print(f"[red]Files deleted (moved):[/]         {len(existing_to_delete)} ({trash_deleted})")
    if removed_dirs_count > 0:
        console.print(f"[magenta]Empty directories cleaned:[/]      {removed_dirs_count}")
    console.print(f"[green]Total files copied:[/]            {len(rel_paths)}\n")
