import time
from pathlib import Path

import pytest

from cais.db import IndexDB
from cais.reconciler import check_external_path, scan_and_reconcile

# (Assume the classes and functions we wrote are imported here, e.g., from cais_core import IndexDB, scan_and_reconcile, etc.)
# from cais import IndexDB, scan_and_reconcile, fast_scandir, check_external_path


def create_file(path: Path, content: str) -> None:
    """Helper to create a file with specific content."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    """Provides an isolated temporary directory for the test."""
    return tmp_path


def test_mode_1_full_lifecycle(workspace: Path):
    # --- 1. Initialization ---
    db_path = workspace / ".cais.db"
    db = IndexDB(db_path, "test_main")

    assert db_path.exists()
    assert db.get_metadata("name") == "test_main"

    # --- 2. Initial Data Creation & Update ---
    create_file(workspace / "photo1.jpg", "image_data_A")
    create_file(workspace / "folder" / "photo2.jpg", "image_data_B")

    assert Path(workspace / "folder" / "photo2.jpg").exists

    # Run scan
    known_state = db.get_known_state()
    result1 = scan_and_reconcile(workspace, known_state)
    print("DEBUG", result1, flush=True)
    time.sleep(2)

    assert len(result1.to_upsert) == 2
    assert len(result1.missing_on_disk) == 0
    assert result1.unchanged_count == 0

    # Commit to DB
    db.upsert_files(result1.to_upsert)

    # Verify Status
    stats = db.get_status_stats()
    assert stats["locations"] == 2
    assert stats["assets"] == 2

    # --- 3. Mutation: Add duplicate, modify file, delete file ---
    # Sleep briefly to ensure filesystem mtime registers a distinct difference
    time.sleep(0.01)

    # Duplicate photo1
    create_file(workspace / "photo1_copy.jpg", "image_data_A")
    # Modify photo2
    create_file(workspace / "folder" / "photo2.jpg", "image_data_B_MODIFIED")
    # Delete photo1
    (workspace / "photo1.jpg").unlink()

    # --- 4. Reconciliation of Mutations ---
    known_state = db.get_known_state()
    result2 = scan_and_reconcile(workspace, known_state)

    # Assertions on the engine's logic
    # Expected upserts: photo1_copy.jpg (new), photo2.jpg (modified)
    assert len(result2.to_upsert) == 2
    # Expected missing: photo1.jpg (deleted)
    assert len(result2.missing_on_disk) == 1
    assert result2.missing_on_disk[0] == "photo1.jpg"
    assert result2.unchanged_count == 0

    # Commit the changes
    db.upsert_files(result2.to_upsert)
    db.remove_paths(result2.missing_on_disk)

    # Verify duplicate logic directly from DB
    dupes = db.get_duplicates()
    # Actually, since photo1.jpg was deleted, photo1_copy is now the ONLY instance.
    # So there should be NO duplicates! This proves the cleanup logic works.
    assert len(dupes) == 0

    # --- 5. External Path Check ---
    ext_dir = workspace / "external_drive"
    ext_dir.mkdir()
    # Contains a file we know (same content as photo2 MODIFIED)
    create_file(ext_dir / "backup2.jpg", "image_data_B_MODIFIED")
    # Contains a brand new file
    create_file(ext_dir / "vacation.jpg", "image_data_C")

    known_hashes = db.get_all_hashes()
    known_files, unknown_files = check_external_path(ext_dir, known_hashes)

    assert len(known_files) == 1
    assert len(unknown_files) == 1
    assert "backup2.jpg" in known_files[0]
    assert "vacation.jpg" in unknown_files[0]

    db.close()
