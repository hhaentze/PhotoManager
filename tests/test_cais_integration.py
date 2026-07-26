"""Smoke test: verifies packages import cleanly and the IndexDB core round-trips.

A full end-to-end pipeline test (scan -> compare -> pull, with fs-safety
assertions) is added in a later phase. This test only guards against the
packaging/import regressions and the most basic DB lifecycle.
"""

from pathlib import Path

from cais.db import IndexDB


def test_indexdb_lifecycle(tmp_path: Path) -> None:
    db_path = tmp_path / ".cais.db"

    # Creation mode
    db = IndexDB(db_path, "test_main")
    assert db_path.exists()
    assert db.get_metadata("name") == "test_main"

    # Upsert two files: (path, hash, size, mtime)
    db.upsert_files(
        [
            ("photo1.jpg", "hash_a", 100, 1.0),
            ("folder/photo2.jpg", "hash_b", 200, 2.0),
        ]
    )

    stats = db.get_status_stats()
    assert stats["locations"] == 2
    assert stats["assets"] == 2
    assert stats["size"] == 300

    # Removing a path cleans up its orphaned asset
    db.remove_paths(["photo1.jpg"])
    stats = db.get_status_stats()
    assert stats["locations"] == 1
    assert stats["assets"] == 1

    db.close()
