import logging
import os
from pathlib import Path
from typing import Dict, Iterator, List, NamedTuple, Set, Tuple

import blake3  # type: ignore

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

    for entry in fast_scandir(root):
        entry_path = Path(entry.path)
        rel_path = Path(entry.path).relative_to(root).as_posix()
        seen_paths.add(rel_path)

        try:
            # THIS is the magic of scandir: stat() is often cached here, saving an I/O call
            stat = entry.stat(follow_symlinks=False)
            mtime, size = stat.st_mtime, stat.st_size

        except OSError as e:
            logger.warning(f"[!] Warning: Could not read {entry_path} - {e}")
            continue

        # O(1) Check against the Database state
        known_file = known_state.get(rel_path)
        if known_file and known_file == (mtime, size):
            unchanged_count += 1
            continue

        # File is New or Modified: time to hash
        try:
            file_hash = compute_blake3(entry_path)
            to_upsert.append((rel_path, file_hash, size, mtime))
        except OSError as e:
            logger.warning(f"[!] Warning: Could not read/hash {entry_path} - {e}")

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

    for entry in fast_scandir(external_dir):
        file_path = Path(entry.path)
        try:
            file_hash = compute_blake3(file_path)

            # Instant O(1) memory lookup, zero database I/O!
            if file_hash in known_hashes:
                known_files.append(file_path.as_posix())
            else:
                unknown_files.append(file_path.as_posix())
        except OSError as e:
            logger.warning(f"[!] Warning: Could not read/hash {file_path} - {e}")

    return known_files, unknown_files
