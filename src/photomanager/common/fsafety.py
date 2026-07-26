"""File-safety primitives shared across the tools.

These encode the project's safety rules in one audited, testable place.
"""

from pathlib import Path
from typing import List


def clean_empty_directories(root: Path, deleted_files: List[Path]) -> int:
    """Safely removes directories left empty after file deletions, bottom-up.

    Only removes directories that the OS confirms are empty; never recurses
    into or force-deletes non-empty directories. Returns the count removed.
    """
    # 1. Collect all unique parent directories, excluding the root itself ('.')
    dirs_to_check = {parent for p in deleted_files for parent in p.parents if str(parent) != "."}

    # 2. Sort by depth descending (deepest folders first)
    sorted_dirs = sorted(dirs_to_check, key=lambda x: len(x.parts), reverse=True)
    removed_count = 0

    # 3. Safely attempt deletion
    for rel_dir in sorted_dirs:
        abs_dir = root / rel_dir
        try:
            # Check if it's a directory and appears empty before asking the OS to delete
            if abs_dir.is_dir() and not any(abs_dir.iterdir()):
                abs_dir.rmdir()  # OS-level safeguard: strictly fails if not empty
                removed_count += 1
        except OSError:
            pass  # Fails cleanly if the dir isn't actually empty (e.g., hidden files)

    return removed_count
