import shutil
import time
from datetime import datetime
from pathlib import Path

from photomanager.common import contract
from photomanager.common.console import console, make_progress
from photomanager.common.fsafety import clean_empty_directories


def pull_cais_files(db2_path: str, root_dir: str = ".", update: bool = False):
    db2, root = Path(db2_path), Path(root_dir)
    update_json_path = Path(contract.CAIS_DIR) / contract.NEW_AND_MODIFIED
    missing_json_path = Path(contract.CAIS_DIR) / contract.MISSING_ON_DISK

    if not update_json_path.exists() and not missing_json_path.exists():
        console.print("[bold red]Error:[/] No comparison JSON files found in .cais/")
        return

    rel_paths = []
    if update_json_path.exists():
        rel_paths = [Path(p) for p in contract.load(update_json_path)]
    delete_paths = []
    if missing_json_path.exists():
        delete_paths = [Path(p) for p in contract.load(missing_json_path)]

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
        with make_progress() as progress:
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
