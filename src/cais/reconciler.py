import logging
import os
from pathlib import Path
from typing import Dict, Iterator, List, NamedTuple, Set, Tuple

import blake3  # type: ignore
import imagehash  # type: ignore
from PIL import Image, UnidentifiedImageError  # type: ignore
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeRemainingColumn,
)

logger = logging.getLogger(__name__)

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif", ".tiff"}


# Typed structure to pass back to the DAL/CLI
class ScanResult(NamedTuple):
    to_upsert: List[Tuple[str, str, int, float]]  # (path, hash, size, mtime)
    to_upsert_phash: List[Tuple[str, str]]  # (hash, phash)
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


def compute_phash(file_path: Path) -> str | None:
    """Safely calculates a perceptual hash for valid image files."""
    try:
        with Image.open(file_path) as img:
            return str(imagehash.phash(img))
    except (UnidentifiedImageError, OSError, ValueError) as e:
        logger.debug(f"Could not calculate pHash for {file_path}: {e}")
        return None


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


def scan_and_reconcile(
    root_dir: Path | str, known_state: Dict[str, Tuple[float, int]], do_perceptual: bool = False
) -> ScanResult:
    """Walks the disk, compares against known state, and hashes new/modified files."""
    root = Path(root_dir).resolve()
    to_upsert: List[Tuple[str, str, int, float]] = []
    to_upsert_phash: List[Tuple[str, str]] = []
    seen_paths: Set[str] = set()
    unchanged_count = 0

    # temporarily store files that need hashing here
    files_to_hash: List[Tuple[str, Path, int, float]] = []
    files_to_phash: List[Tuple[str, Path]] = []

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
            if known_file and known_file[:2] == (mtime, size):
                unchanged_count += 1
                if do_perceptual and known_file[2] is None and entry_path.suffix.lower() in IMAGE_EXTENSIONS:
                    blake3_hash = known_file[3]
                    files_to_phash.append((blake3_hash, entry_path))
            else:
                files_to_hash.append((rel_path, entry_path, size, mtime))

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
                    if do_perceptual and entry_path.suffix.lower() in IMAGE_EXTENSIONS:
                        files_to_phash.append((file_hash, entry_path))
                except OSError as e:
                    logger.warning(f"[!] Warning: Could not read/hash {entry_path} - {e}")
                progress.advance(hash_task)

    # PHASE 3: Perceptual Hashing
    if files_to_phash:
        # Deduplicate the queue in case multiple paths point to the same blake3 hash
        unique_phash_queue = {b3_hash: path for b3_hash, path in files_to_phash}

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            TimeRemainingColumn(),
        ) as progress:
            phash_task = progress.add_task("[magenta]Calculating perceptual hashes...", total=len(unique_phash_queue))

            for b3_hash, entry_path in unique_phash_queue.items():
                phash = compute_phash(entry_path)
                if phash:
                    to_upsert_phash.append((b3_hash, phash))
                progress.advance(phash_task)

    # Fast set difference to find files in DB that are no longer on disk
    missing_on_disk = list(set(known_state.keys()) - seen_paths)

    return ScanResult(to_upsert, to_upsert_phash, missing_on_disk, unchanged_count)


def check_external_path(
    external_dir: Path, known_hashes: set[str], known_phashes: set[str], do_perceptual: bool = False
) -> tuple[list[str], list[str]]:
    """
    Hashes files in an external directory and checks if they exist in the DB.
    Returns: (known_file_paths, unknown_file_paths)
    """
    known_files: list[str] = []
    perceptually_known_files: list[str] = []
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

    # PHASE 3: Perceptual Hashing Check
    if do_perceptual:
        truly_unknown: list[str] = []
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            TimeRemainingColumn(),
        ) as progress:
            hash_task = progress.add_task("[magenta]Calculating perceptual hashes...", total=len(unknown_files))

            for file_path in unknown_files:
                file_path = Path(file_path)
                if file_path.suffix.lower() in IMAGE_EXTENSIONS:
                    try:
                        file_hash = compute_phash(file_path)

                        if file_hash in known_phashes:
                            known_files.append(file_path.as_posix())
                        else:
                            truly_unknown.append(file_path.as_posix())
                    except OSError as e:
                        logger.warning(f"[!] Warning: Could not phash {file_path} - {e}")
                        truly_unknown.append(file_path.as_posix())
                else:
                    truly_unknown.append(file_path.as_posix())

                progress.advance(hash_task)
        unknown_files = truly_unknown

    return known_files, unknown_files
