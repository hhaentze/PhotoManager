"""Safety tests for files that cannot be hashed.

A file that fails to read/hash (permissions, a cloud "online-only" placeholder,
a mid-scan I/O error) must never poison the index with a null hash or leave a
partially-written database.
"""

import sqlite3
from pathlib import Path

import pytest

from cais import reconciler
from cais.db import IndexDB
from cais.reconciler import ScanAnalyzer


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def test_unhashable_file_is_skipped(tmp_path: Path, monkeypatch) -> None:
    write(tmp_path / "a.jpg", "AAA")
    write(tmp_path / "b.jpg", "BBB")
    db = IndexDB(tmp_path / ".cais.db", "t")

    # Simulate b.jpg being unreadable during hashing.
    real = reconciler.compute_blake3

    def fake(path, *args, **kwargs):
        if Path(path).name == "b.jpg":
            raise OSError("simulated unreadable file")
        return real(path, *args, **kwargs)

    monkeypatch.setattr(reconciler, "compute_blake3", fake)

    analyzer = ScanAnalyzer(tmp_path, tmp_path, db.get_known_state())
    report = analyzer.analyze(analyzer.scan())

    upsert_paths = {p for p, *_ in report.to_upsert}
    assert "a.jpg" in upsert_paths
    assert "b.jpg" not in upsert_paths  # skipped, not indexed
    assert report.failed == ["b.jpg"]
    assert "b.jpg" not in report.new_files
    assert all(h is not None for _, h, _, _ in report.to_upsert)

    # Committing the (clean) report must not crash or leave a null-hash asset.
    db.upsert_files(report.to_upsert)
    null_assets = db.conn.execute("SELECT COUNT(*) FROM assets WHERE hash IS NULL").fetchone()[0]
    assert null_assets == 0
    locations = {row[0] for row in db.conn.execute("SELECT path FROM locations")}
    assert locations == {"a.jpg"}
    db.close()


def test_upsert_is_atomic_on_bad_row(tmp_path: Path) -> None:
    """A null hash reaching the DB must roll back the whole batch, not persist partially."""
    db = IndexDB(tmp_path / ".cais.db", "t")

    with pytest.raises(sqlite3.IntegrityError):
        db.upsert_files([("good.jpg", "h1", 10, 1.0), ("bad.jpg", None, 20, 2.0)])

    # Nothing from the failed batch should have been committed.
    assert db.conn.execute("SELECT COUNT(*) FROM assets").fetchone()[0] == 0
    assert db.conn.execute("SELECT COUNT(*) FROM locations").fetchone()[0] == 0
    db.close()
