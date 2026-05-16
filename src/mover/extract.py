import json
import shutil
from pathlib import Path

from rich.console import Console

console = Console()


def extract_cais_files(source: str, json_path: str = ".cais/cais_new_files.json", target_dir: str = ".temp_store"):
    source_dir = Path(source)
    source_json = Path(json_path)
    dest_path = Path(target_dir)

    if not source_json.exists():
        console.print(f"[bold red]Error:[/] JSON file '{json_path}' not found.")
        return

    if not source_dir.exists():
        console.print(f"[bold red]Error:[/] Source directory '{source_dir}' not found.")
        return

    with open(source_json, "r", encoding="utf-8") as f:
        paths = json.load(f)

    files = [source_dir / p for p in paths]
    existing_files = [p for p in files if p.is_file()]
    dest_path.mkdir(parents=True, exist_ok=True)

    copied_count = 0
    skipped_count = 0

    for src in existing_files:
        dest_file = dest_path / src.name
        if not dest_file.exists():
            shutil.copy2(src, dest_file)
            copied_count += 1
        else:
            skipped_count += 1

    console.print("\n[bold magenta]Extract Summary Report[/bold magenta]")
    console.print("-" * 35)
    console.print(f"[cyan]Total paths in JSON:[/]      {len(paths)}")
    console.print(f"[green]Existing files found:[/]     {len(existing_files)}")
    console.print(f"[blue]Files successfully copied:[/] {copied_count}")
    console.print(f"[yellow]Files skipped (already exist):[/] {skipped_count}\n")
