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

from cais.db import DataPoint

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


@dataclass
class ScanResult:
    entry_path: str
    hash_in_db: bool
    phash_in_db: Optional[bool]
    entry: DataPoint


def scan(root_dir: Path | str, known_state: Dict[str, DataPoint], do_perceptual: bool = False) -> List[ScanResult]:
    """Walks the disk, compares against known state, and hashes new/modified files."""
    root = Path(root_dir).resolve()

    known_hashes = {info.hash for info in known_state.values()}
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
            entry_path = Path(entry.path)
            rel_path = entry_path.relative_to(root).as_posix()
            try:
                stat = entry.stat(follow_symlinks=False)
                mtime, size = stat.st_mtime, stat.st_size
            except OSError as e:
                logger.warning(f"[!] Warning: Could not read {entry_path} - {e}")
                continue

            # O(1) Check against the Database state
            known_file = known_state.get(rel_path)
            if known_file and known_file.mtime == mtime and known_file.size == size:
                has_phash = known_file.phash is not None
                result = ScanResult(entry_path, True, has_phash, known_file)
            else:
                new_point = DataPoint(None, None, size, mtime)
                result = ScanResult(entry_path, False, None, new_point)

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

            for i, r in enumerate(results):
                if not r.hash_in_db:
                    try:
                        file_hash = compute_blake3(r.entry_path)
                        r.entry.hash = file_hash
                        if r.entry.hash in known_hashes:
                            r.hash_in_db = True

                        _phash = hash_phash_map.get(file_hash)
                        if _phash is not None:
                            r.entry.phash = _phash
                            r.phash_in_db = True
                    except OSError as e:
                        logger.warning(f"[!] Warning: Could not read/hash {r.entry_path} - {e}")
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
                phash_task = progress.add_task("[magenta]Calculating perceptual hashes...", total=needs_phashing_count)

                for i, r in enumerate(results):
                    if not r.phash_in_db:
                        try:
                            file_phash = compute_phash(r.entry_path)
                            r.entry.phash = file_phash
                        except OSError as e:
                            logger.warning(f"[!] Warning: Could not read/hash {r.entry_path} - {e}")
                        progress.advance(phash_task)

    return results


@dataclass
class AnalysisReport:
    missing_on_disk: List[str] = field(default_factory=list)
    to_upsert: List[Tuple[str, str, int, float]] = field(default_factory=list)
    to_upsert_phash: List[Tuple[str, str]] = field(default_factory=list)

    exact_dupes: Dict[str, List[str]] = field(default_factory=dict)
    perceptual_dupes: Dict[str, List[str]] = field(default_factory=dict)

    unchanged_count: int = 0
    new_modified_count: int = 0


class ScanAnalyzer:
    def __init__(self, root_dir: Path, scan_dir: Path, known_state: Dict[str, "DataPoint"]):
        self.root_dir = root_dir
        self.scan_dir = scan_dir
        self.known_state = known_state

        # Determine if we are scanning internally or an external drive
        try:
            self.scan_rel = self.scan_dir.relative_to(self.root_dir).as_posix()
            self.is_external = False
            if self.scan_rel == ".":
                self.scan_rel = ""
        except ValueError:
            self.scan_rel = ""
            self.is_external = True

    def analyze(self, results: List[ScanResult], db_dupes: dict, db_pdupes: dict) -> AnalysisReport:
        report = AnalysisReport()
        run_hashes, run_phashes = {}, {}
        scanned_paths = set()

        for r in results:
            # 1. Path Resolution
            p = r.entry_path.relative_to(self.root_dir).as_posix() if not self.is_external else str(r.entry_path)
            scanned_paths.add(p)

            # 2. Grouping
            if r.entry.hash:
                run_hashes.setdefault(r.entry.hash, []).append(p)
            if r.entry.phash:
                run_phashes.setdefault(r.entry.phash, []).append(p)

            # 3. Payload Prep (Skip external paths for DB upserts)
            kf = self.known_state.get(p)
            is_unchanged = kf and kf.mtime == r.entry.mtime and kf.size == r.entry.size

            if is_unchanged:
                report.unchanged_count += 1
            else:
                report.new_modified_count += 1
                if not self.is_external and r.entry.hash:
                    report.to_upsert.append((p, r.entry.hash, r.entry.size, r.entry.mtime))

            if not self.is_external and r.entry.phash and (not is_unchanged or (kf and kf.phash != r.entry.phash)):
                report.to_upsert_phash.append((r.entry.hash, r.entry.phash))

        # 4. Calculate Missing Files (Only if internal)
        if not self.is_external:
            expected = {p for p in self.known_state if p == self.scan_rel or p.startswith(self.scan_rel + "/")}
            report.missing_on_disk = list(expected - scanned_paths)

        # 5. Merge Duplicates
        report.exact_dupes = self._merge_dupes(run_hashes, db_dupes)
        report.perceptual_dupes = self._merge_dupes(run_phashes, db_pdupes)

        return report

    def _merge_dupes(self, run_dict: dict, db_dict: dict) -> dict:
        """Helper to combine run duplicates with historical DB duplicates."""
        merged = {}
        for k, paths in run_dict.items():
            combined = list(dict.fromkeys(db_dict.get(k, []) + paths))
            if len(combined) > 1:
                merged[k] = combined

        for k, db_paths in db_dict.items():
            if k not in merged and len(db_paths) > 1:
                merged[k] = db_paths
        return merged
