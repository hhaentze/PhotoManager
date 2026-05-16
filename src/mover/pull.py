import json
import shutil
import time
from datetime import datetime
from pathlib import Path

from rich.console import Console

console = Console()


def pull_cais_files(db2_path: str, root_dir: str = ".", update: bool = False):
    db2, root = Path(db2_path), Path(root_dir)
    json_path = Path(".cais/cais_new_and_modified_files.json")

    if not json_path.exists():
        console.print(f"[bold red]Error:[/] {json_path} not found.")
        return

    with open(json_path, "r", encoding="utf-8") as f:
        rel_paths = [Path(p) for p in json.load(f)]

    # 3. Check if all paths exist in db2_path
    missing_in_db2 = [p for p in rel_paths if not (db2 / p).is_file()]
    if missing_in_db2:
        console.print(f"[bold red]Error:[/] Missing {len(missing_in_db2)} files in '{db2}'.")
        console.print(f"First missing file: {missing_in_db2[0]}")
        return

    # 4. Skim target root directory
    existing_targets = [p for p in rel_paths if (root / p).is_file()]
    missing_targets_count = len(rel_paths) - len(existing_targets)

    console.print("\n[bold magenta]Pull Skim Report[/bold magenta]")
    console.print("-" * 35)
    console.print(f"[cyan]Files to create (new):[/]     {missing_targets_count}")
    console.print(f"[yellow]Files to overwrite:[/]        {len(existing_targets)}")

    if not update:
        return

    # 5. Execute Update Sequence
    console.print(f"\n[bold red]WARNING:[/] Pulling from [cyan]{db2}[/] to [cyan]{root}[/]")
    console.print("Operation starting in 3 seconds... Press Ctrl+C to cancel.")
    try:
        time.sleep(3)
    except KeyboardInterrupt:
        console.print("\n[yellow]Operation cancelled by user.[/]")
        return

    # 6. Backup existing to .trash
    trash_dir = Path(".trash") / datetime.now().strftime("%Y-%m-%d")
    for p in existing_targets:
        trash_target = trash_dir / p
        trash_target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(root / p, trash_target)

    # 7. Copy from db2 to root
    copied = 0
    for p in rel_paths:
        dest = root / p
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(db2 / p, dest)
        copied += 1

    # 8. Summary statistics
    console.print("\n[bold green]Update Successful![/bold green]")
    console.print("-" * 35)
    console.print(f"[blue]Files backed up to trash:[/]  {len(existing_targets)} ({trash_dir})")
    console.print(f"[green]Total files copied:[/]        {copied}\n")
