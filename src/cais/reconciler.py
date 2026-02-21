import logging
import os
from pathlib import Path
from typing import Dict, Iterator, List, NamedTuple, Set, Tuple

import blake3  # type: ignore
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeRemainingColumn,
)

logger = logging.getLogger(__name__)


# Typed structure to pass back to the DAL/CLI
class ScanResult(NamedTuple):
    to_upsert: List[Tuple[str, str, int, float]]  # (path, hash, size, mtime)
    missing_on_disk: List[str]  # paths
    unchanged_count: int


def compute_blake3(file_path: Path, chunk_size: int = 1024 * 1024) -> str:
    """Safely hashes a file in 1MB chunks to prevent RAM exhaustion."""
    hasher = blake3.blake3()
    with open(file_path, "rb") as f:
        # iter(callable, sentinel) efficiently reads until EOF (empty bytes)
        for chunk in iter(lambda: f.read(chunk_size), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def fast_scandir(root: Path) -> Iterator[os.DirEntry]:
    """Yields DirEntry objects, using an iterative stack to avoid recursion limits."""
    directories = [root.resolve()]
    while directories:
        current_dir = directories.pop()
        try:
            for entry in os.scandir(current_dir):
                if entry.name.startswith("."):
                    continue
                if entry.is_dir(follow_symlinks=False):
                    directories.append(Path(entry.path))
                elif entry.is_file(follow_symlinks=False):
                    yield entry
        except OSError:
            # Skip unreadable directories (permissions, etc.)
            continue


def scan_and_reconcile(root_dir: Path | str, known_state: Dict[str, Tuple[float, int]]) -> ScanResult:
    """Walks the disk, compares against known state, and hashes new/modified files."""
    root = Path(root_dir).resolve()
    to_upsert: List[Tuple[str, str, int, float]] = []
    seen_paths: Set[str] = set()
    unchanged_count = 0

    # temporarily store files that need hashing here
    files_to_hash: List[Tuple[str, Path, int, float]] = []

    # PHASE 1: Fast Discovery
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        transient=True,  # Disappears when done
    ) as progress:
        scan_task = progress.add_task("[cyan]Scanning directory structure...", total=None)

        for entry in fast_scandir(root):
            entry_path = Path(entry.path)
            rel_path = entry_path.relative_to(root).as_posix()
            seen_paths.add(rel_path)

            try:
                stat = entry.stat(follow_symlinks=False)
                mtime, size = stat.st_mtime, stat.st_size
            except OSError as e:
                logger.warning(f"[!] Warning: Could not read {entry_path} - {e}")
                continue

            # O(1) Check against the Database state
            known_file = known_state.get(rel_path)
            if known_file and known_file == (mtime, size):
                unchanged_count += 1
            else:
                # Needs hashing! Add to our queue.
                files_to_hash.append((rel_path, entry_path, size, mtime))

            # Update the spinner text
            progress.update(scan_task, description=f"[cyan]Scanning directory... found {len(seen_paths)} files")

    # PHASE 2: Hashing with ETA
    if files_to_hash:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            TimeRemainingColumn(),
        ) as progress:
            hash_task = progress.add_task("[green]Hashing new/modified files...", total=len(files_to_hash))

            for rel_path, entry_path, size, mtime in files_to_hash:
                try:
                    file_hash = compute_blake3(entry_path)
                    to_upsert.append((rel_path, file_hash, size, mtime))
                except OSError as e:
                    logger.warning(f"[!] Warning: Could not read/hash {entry_path} - {e}")

                # Advance the progress bar by 1
                progress.advance(hash_task)

    # Fast set difference to find files in DB that are no longer on disk
    missing_on_disk = list(set(known_state.keys()) - seen_paths)

    return ScanResult(to_upsert, missing_on_disk, unchanged_count)


def check_external_path(external_dir: Path, known_hashes: set[str]) -> tuple[list[str], list[str]]:
    """
    Hashes files in an external directory and checks if they exist in the DB.
    Returns: (known_file_paths, unknown_file_paths)
    """
    known_files: list[str] = []
    unknown_files: list[str] = []

    all_files: list[Path] = []

    # PHASE 1: Discovery
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        transient=True,
    ) as progress:
        scan_task = progress.add_task("[cyan]Discovering external files...", total=None)
        for entry in fast_scandir(external_dir):
            all_files.append(Path(entry.path))
            progress.update(scan_task, description=f"[cyan]Discovering external files... found {len(all_files)}")

    # PHASE 2: Hashing Check
    if all_files:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            TimeRemainingColumn(),
        ) as progress:
            hash_task = progress.add_task("[green]Analyzing external files...", total=len(all_files))

            for file_path in all_files:
                try:
                    file_hash = compute_blake3(file_path)

                    if file_hash in known_hashes:
                        known_files.append(file_path.as_posix())
                    else:
                        unknown_files.append(file_path.as_posix())
                except OSError as e:
                    logger.warning(f"[!] Warning: Could not read/hash {file_path} - {e}")

                progress.advance(hash_task)

    return known_files, unknown_files
