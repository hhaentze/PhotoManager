# import json
# import shutil
# from pathlib import Path

# from rich.console import Console


# def backup_cais_files(json_path: str = ".cais/cais_new_files.json", target_dir: str = ".temp_store"):
#     console = Console()
#     source_json = Path(json_path)
#     dest_path = Path(target_dir)

#     # 1. Load JSON file
#     if not source_json.exists():
#         console.print(f"[bold red]Error:[/] JSON file '{json_path}' not found.")
#         return

#     with open(source_json, "r", encoding="utf-8") as f:
#         paths = json.load(f)

#     # 2. Count all paths
#     total_paths = len(paths)

#     # 3. Count existing paths
#     existing_files = [Path(p) for p in paths if Path(p).is_file()]
#     existing_count = len(existing_files)

#     # 4. Create hidden folder (a leading dot makes it hidden on Unix/Linux)
#     dest_path.mkdir(parents=True, exist_ok=True)

#     # 5 & 6. Copy files without overwriting
#     copied_count = 0
#     skipped_count = 0

#     for src in existing_files:
#         # Places all files directly into the .temp_store root (flattened)
#         dest_file = dest_path / src.name

#         if not dest_file.exists():
#             shutil.copy2(src, dest_file)
#             copied_count += 1
#         else:
#             skipped_count += 1

#     # Print results using Rich
#     console.print("\n[bold magenta]Backup Summary Report[/bold magenta]")
#     console.print("-" * 35)
#     console.print(f"[cyan]Total paths in JSON:[/cyan]      {total_paths}")
#     console.print(f"[green]Existing files found:[/green]     {existing_count}")
#     console.print(f"[blue]Files successfully copied:[/blue] {copied_count}")
#     console.print(f"[yellow]Files skipped (already exist):[/yellow] {skipped_count}\n")


# def main():
#     backup_cais_files()


# if __name__ == "__main__":
#     backup_cais_files()

import argparse

from mover.extract import extract_cais_files
from mover.pull import pull_cais_files


def main():
    parser = argparse.ArgumentParser(description="CAIS File Mover CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # --- extract Command ---
    extract_parser = subparsers.add_parser("extract", help="Copy new files to a temp store")
    extract_parser.add_argument("source_path", help="Path to the external directory")
    extract_parser.add_argument("--json-path", default=".cais/cais_new_files.json", help="Path to JSON file")
    extract_parser.add_argument("--target-dir", default=".temp_store", help="Hidden target directory")

    # --- Pull Command ---
    pull_parser = subparsers.add_parser("pull", help="Pull new and modified files, replacing existing")
    pull_parser.add_argument("db2_path", help="Path to the external DB2 directory")
    pull_parser.add_argument("--root-dir", default=".", help="Target root directory (default: current dir)")
    pull_parser.add_argument("--update", action="store_true", help="Set flag to execute copy and overwrite")

    args = parser.parse_args()

    # Execute the chosen command
    if args.command == "extract":
        extract_cais_files(args.source_path, args.json_path, args.target_dir)
    elif args.command == "pull":
        pull_cais_files(args.db2_path, args.root_dir, args.update)


if __name__ == "__main__":
    main()
