import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Tuple

import blake3  # type: ignore
import imagehash  # type: ignore
from PIL import Image, UnidentifiedImageError  # type: ignore
from rich.progress import Progress, SpinnerColumn, TextColumn

from cais.db import DataPoint, DuplicateGroup
from photomanager.common.console import make_progress

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
                    directories.append(entry.path)
                elif entry.is_file(follow_symlinks=False):
                    yield entry
        except OSError:
            # Skip unreadable directories (permissions, etc.)
            continue


@dataclass
class ScanResult:
    rel_path: str
    in_db: Optional[bool] = None
    hash_in_db: Optional[bool] = None
    phash_in_db: Optional[bool] = None
    entry: Optional[DataPoint] = None


@dataclass
class AnalysisReport:
    on_disk: List[Tuple[str, Optional[str], Optional[str]]] = field(default_factory=list)
    to_upsert: List[Tuple[str, Optional[str], int, float]] = field(default_factory=list)  # path, hash, size, mtime
    to_upsert_phash: List[Tuple[Optional[str], str]] = field(default_factory=list)  # hash, phash
    missing_on_disk: List[str] = field(default_factory=list)  # paths
    duplicates: Dict[str, DuplicateGroup] = field(default_factory=dict)
    new_files: List[str] = field(default_factory=list)  # path


class ScanAnalyzer:
    def __init__(self, root_dir: Path, scan_dir: Path, known_state: Dict[str, DataPoint]):
        self.root_dir = root_dir
        self.scan_dir = scan_dir
        self.known_state = known_state
        self.updated_state: Dict[str, DataPoint] = {}
        self.is_external = root_dir != scan_dir

    def scan(self, do_perceptual: bool = False) -> List[ScanResult]:
        """Walks the disk, compares against known state, and hashes new/modified files."""

        results: List[ScanResult] = []

        # PHASE 1: Fast Discovery (based on file names)
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            transient=True,  # Disappears when done
        ) as progress:
            scan_task = progress.add_task("[cyan]Scanning directory structure...", total=None)

            for entry in fast_scandir(str(self.scan_dir)):
                rel_path = Path(os.path.relpath(entry.path, self.scan_dir)).as_posix()
                result = ScanResult(rel_path=rel_path)
                try:
                    stat = entry.stat(follow_symlinks=False)
                    mtime, size = stat.st_mtime, stat.st_size
                except OSError as e:
                    logger.warning(f"[!] Warning: Could not read {result.rel_path} - {e}")
                    continue

                # O(1) Check against the Database state
                known_file = self.known_state.get(rel_path)
                if known_file and known_file.mtime == mtime and known_file.size == size:
                    result.in_db = True
                    result.hash_in_db = True
                    result.phash_in_db = known_file.phash is not None
                    result.entry = known_file
                    self.updated_state[rel_path] = known_file

                else:
                    result.in_db = False
                    result.entry = DataPoint(None, None, size, mtime)

                results.append(result)
                progress.update(scan_task, description=f"[cyan]Scanning directory... found {len(results)} files")

        known_hashes = {info.hash for info in self.updated_state.values()}
        known_phashes = {info.phash for info in self.updated_state.values()}
        hash_phash_map = {info.hash: info.phash for info in self.updated_state.values()}

        # PHASE 2: Hashing
        needs_hashing_count = len(list(filter(lambda r: not r.hash_in_db, results)))
        if needs_hashing_count:
            with make_progress() as progress:
                hash_task = progress.add_task("[green]Hashing new/modified files...", total=needs_hashing_count)

                for r in results:
                    if r.hash_in_db is None or not r.hash_in_db:
                        assert r.entry is not None
                        try:
                            file_hash = compute_blake3(self.scan_dir / r.rel_path)
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
                with make_progress() as progress:
                    phash_task = progress.add_task(
                        "[magenta]Calculating perceptual hashes...", total=needs_phashing_count
                    )

                    for r in results:
                        if not r.phash_in_db:
                            assert r.entry is not None
                            try:
                                file_phash = compute_phash(self.scan_dir / r.rel_path)
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

        # calculate missing files (only if internal)
        if not self.is_external:
            expected = set(self.known_state.keys())
            found = set(self.updated_state.keys())
            report.missing_on_disk = list(expected - found)

        for r in results:
            entry = r.entry
            assert entry is not None
            if r.in_db:
                report.on_disk.append((r.rel_path, entry.hash, entry.phash))

            else:
                report.to_upsert.append((r.rel_path, entry.hash, entry.size, entry.mtime))

                if r.hash_in_db:
                    hash_on_disk.append((entry.hash, r.rel_path))

                elif r.phash_in_db:
                    phash_only_on_disk.append((entry.phash, r.rel_path))

            if not r.phash_in_db and entry.phash is not None:
                report.to_upsert_phash.append((entry.hash, entry.phash))

        # calculate dupes
        hash_to_path = {}
        phash_to_path = {}
        if self.is_external:
            for path, datapoint in self.updated_state.items():
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

        # get completly new files
        all_files = set(r.rel_path for r in results)
        duplicated_files = set()
        for group in all_dupes.values():
            paths = {d[0] for d in group.duplicates}
            duplicated_files.update(paths)

        report.new_files = list(all_files - duplicated_files)

        return report

    def _group_duplicates_with_representative(self, duplicates, look_up, match_type: str, duplicate_map={}) -> dict:

        # Exact hash matches
        for h, path in duplicates:
            original = look_up[h]  # exactly one match guaranteed
            entry = duplicate_map.setdefault(original, DuplicateGroup(original, []))
            entry.duplicates.append((path, match_type))

        return duplicate_map


def compare_dbs(state1: Dict[str, DataPoint], state2: Dict[str, DataPoint]) -> AnalysisReport:
    """Generates the comparison report efficiently using O(1) dictionary lookups."""
    report = AnalysisReport(
        missing_on_disk=list(set(state1) - set(state2)),
        new_files=list(set(state2) - set(state1)),
    )

    # 1. Build reverse lookups for the base state to find duplicates quickly
    hash_map = {dp.hash: path for path, dp in state1.items()}
    phash_map = {dp.phash: path for path, dp in state1.items() if dp.phash}
    upsert_phash = set()

    # 2. Reconcile Target State (db2) against Base State (db1)
    for path2, dp2 in state2.items():
        dp1 = state1.get(path2)

        # Categorize updates vs unchanged
        if dp1 is not None and dp1.hash == dp2.hash and dp1.size == dp2.size and dp1.phash == dp2.phash:
            report.on_disk.append((path2, dp2.hash, dp2.phash))
        else:
            report.to_upsert.append((path2, dp2.hash, dp2.size, dp2.mtime))
            if dp2.phash:
                upsert_phash.add((dp2.hash, dp2.phash))

        # Categorize duplicates
        orig_path, match_type = None, None
        if dp2.hash in hash_map:
            orig_path, match_type = hash_map[dp2.hash], "hash"
        elif dp2.phash in phash_map:
            orig_path, match_type = phash_map[dp2.phash], "phash"

        if orig_path:
            assert match_type is not None  # set together with orig_path above
            if orig_path not in report.duplicates:
                report.duplicates[orig_path] = DuplicateGroup(original=orig_path, duplicates=[])
            report.duplicates[orig_path].duplicates.append((path2, match_type))

    report.to_upsert_phash = list(upsert_phash)
    return report
