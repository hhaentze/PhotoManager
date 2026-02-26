import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Tuple

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

from cais.db import DataPoint, DuplicateGroup

logger = logging.getLogger(__name__)

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif", ".tiff"}


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


def fast_scandir(root: str) -> Iterator[os.DirEntry]:
    """Yields DirEntry objects, using an iterative stack to avoid recursion limits."""
    directories = [root]
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


@dataclass
class ScanResult:
    rel_path: str = None
    in_db: bool = None
    hash_in_db: bool = None
    phash_in_db: Optional[bool] = None
    entry: DataPoint = None


@dataclass
class AnalysisReport:
    on_disk: List[Tuple[str, str, str]] = field(default_factory=list)
    to_upsert: List[Tuple[str, str, int, float]] = field(default_factory=list)  # path, hash, size, mtime
    to_upsert_phash: List[Tuple[str, str]] = field(default_factory=list)  # hash, phash
    missing_on_disk: List[str] = field(default_factory=list)  # paths
    duplicates: Dict[str, DuplicateGroup] = field(default_factory=dict)


class ScanAnalyzer:
    def __init__(self, root_dir: Path, scan_dir: Path, known_state: Dict[str, DataPoint]):
        self.root_dir = root_dir
        self.scan_dir = scan_dir
        self.known_state = known_state
        self.is_external = root_dir != scan_dir

    def scan(self, do_perceptual: bool = False) -> List[ScanResult]:
        """Walks the disk, compares against known state, and hashes new/modified files."""

        root = os.path.relpath(self.scan_dir, self.root_dir)
        known_state = self.known_state

        known_hashes = {info.hash for info in known_state.values()}
        known_phashes = {info.phash for info in known_state.values()}
        hash_phash_map = {info.hash: info.phash for info in known_state.values()}

        results: List[ScanResult] = []

        # PHASE 1: Fast Discovery (based on file names)
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            transient=True,  # Disappears when done
        ) as progress:
            scan_task = progress.add_task("[cyan]Scanning directory structure...", total=None)

            for entry in fast_scandir(root):
                result = ScanResult()
                rel_path = Path(entry.path).as_posix()
                result.rel_path = rel_path
                try:
                    stat = entry.stat(follow_symlinks=False)
                    mtime, size = stat.st_mtime, stat.st_size
                except OSError as e:
                    logger.warning(f"[!] Warning: Could not read {result.rel_path} - {e}")
                    continue

                # O(1) Check against the Database state
                known_file = known_state.get(rel_path)
                if known_file and known_file.mtime == mtime and known_file.size == size:
                    result.in_db = True
                    result.hash_in_db = True
                    result.phash_in_db = known_file.phash is not None
                    result.entry = known_file

                else:
                    result.in_db = False
                    result.entry = DataPoint(None, None, size, mtime)

                results.append(result)
                progress.update(scan_task, description=f"[cyan]Scanning directory... found {len(results)} files")

        # PHASE 2: Hashing
        needs_hashing_count = len(list(filter(lambda r: not r.hash_in_db, results)))
        if needs_hashing_count:
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                TaskProgressColumn(),
                TimeRemainingColumn(),
            ) as progress:
                hash_task = progress.add_task("[green]Hashing new/modified files...", total=needs_hashing_count)

                for r in results:
                    if r.hash_in_db is None or not r.hash_in_db:
                        try:
                            file_hash = compute_blake3(r.rel_path)
                            r.entry.hash = file_hash
                            if r.entry.hash in known_hashes:
                                r.hash_in_db = True

                            _phash = hash_phash_map.get(file_hash)
                            if _phash is not None:
                                r.entry.phash = _phash
                                r.phash_in_db = True
                        except OSError as e:
                            logger.warning(f"[!] Warning: Could not read/hash {r.rel_path} - {e}")
                        progress.advance(hash_task)

        # PHASE 3: Perceptual Hashing
        if do_perceptual:
            needs_phashing_count = len(list(filter(lambda r: not r.phash_in_db, results)))
            if needs_phashing_count:
                with Progress(
                    SpinnerColumn(),
                    TextColumn("[progress.description]{task.description}"),
                    BarColumn(),
                    TaskProgressColumn(),
                    TimeRemainingColumn(),
                ) as progress:
                    phash_task = progress.add_task(
                        "[magenta]Calculating perceptual hashes...", total=needs_phashing_count
                    )

                    for r in results:
                        if not r.phash_in_db:
                            try:
                                file_phash = compute_phash(r.rel_path)
                                r.entry.phash = file_phash
                                if r.entry.phash in known_phashes:
                                    r.phash_in_db = True

                            except OSError as e:
                                logger.warning(f"[!] Warning: Could not read/hash {r.rel_path} - {e}")
                            progress.advance(phash_task)

        return results

    def analyze(
        self,
        results: List[ScanResult],
    ) -> AnalysisReport:
        report = AnalysisReport()

        hash_on_disk = []
        phash_only_on_disk = []

        for r in results:
            entry = r.entry
            if r.in_db:
                # print("DEBUG", r.rel_path)
                report.on_disk.append((r.rel_path, entry.hash, entry.phash))

            else:
                report.to_upsert.append((r.rel_path, entry.hash, entry.size, entry.mtime))

                if r.hash_in_db:
                    hash_on_disk.append((entry.hash, r.rel_path))

                elif r.phash_in_db:
                    phash_only_on_disk.append((entry.phash, r.rel_path))

            if not r.phash_in_db and entry.phash is not None:
                report.to_upsert_phash.append((entry.hash, entry.phash))

        # calculate missing files (only if internal)
        if not self.is_external:
            expected = set(self.known_state.keys())
            found = set(r.rel_path for r in results)
            report.missing_on_disk = list(expected - found)

        # calculate dupes
        hash_to_path = {}
        phash_to_path = {}
        if self.is_external:
            for path, datapoint in self.known_state.items():
                hash_to_path[datapoint.hash] = path
                if datapoint.phash is not None:
                    phash_to_path[datapoint.phash] = path

        else:
            for path, h, ph in report.on_disk:
                hash_to_path[h] = path
                if ph is not None:
                    phash_to_path[ph] = path

        exact_dupes = self._group_duplicates_with_representative(hash_on_disk, hash_to_path, "hash")
        all_dupes = self._group_duplicates_with_representative(phash_only_on_disk, phash_to_path, "phash", exact_dupes)
        report.duplicates = all_dupes

        return report

    def _group_duplicates_with_representative(self, duplicates, look_up, match_type: str, duplicate_map={}) -> dict:

        # Exact hash matches
        for h, path in duplicates:
            original = look_up[h]  # exactly one match guaranteed
            entry = duplicate_map.setdefault(original, DuplicateGroup(original, []))
            entry.duplicates.append((path, match_type))

        return duplicate_map
