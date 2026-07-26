"""Unit tests for pure cais logic that has no filesystem/DB side effects."""

from cais.cli import format_size
from cais.db import DataPoint
from cais.reconciler import compare_dbs


def dp(hash_: str, size: int, phash=None, mtime: float = 1.0) -> DataPoint:
    return DataPoint(hash=hash_, phash=phash, size=size, mtime=mtime)


def test_compare_dbs_classifies_new_missing_and_modified() -> None:
    # state1 = "current" db, state2 = the db we compare against
    state1 = {"a.jpg": dp("hA", 3), "b.jpg": dp("hB", 3), "d.jpg": dp("hD", 3)}
    state2 = {"a.jpg": dp("hA", 3), "b.jpg": dp("hB2", 7), "c.jpg": dp("hC", 3)}

    report = compare_dbs(state1, state2)

    # In current but not in the compared db
    assert set(report.missing_on_disk) == {"d.jpg"}
    # In the compared db but not in current
    assert set(report.new_files) == {"c.jpg"}
    # Files from the compared db that differ or are new (what a pull would fetch)
    upsert_paths = {path for path, *_ in report.to_upsert}
    assert upsert_paths == {"b.jpg", "c.jpg"}
    # The unchanged file is not scheduled for upsert
    assert "a.jpg" not in upsert_paths


def test_compare_dbs_identical_states_have_no_changes() -> None:
    state = {"a.jpg": dp("hA", 3), "b.jpg": dp("hB", 3)}
    report = compare_dbs(dict(state), dict(state))
    assert report.missing_on_disk == []
    assert report.new_files == []
    assert report.to_upsert == []


def test_format_size() -> None:
    assert format_size(0) == "0.00 B"
    assert format_size(512) == "512.00 B"
    assert format_size(1024) == "1.00 KB"
    assert format_size(1536) == "1.50 KB"
    assert format_size(1024**2) == "1.00 MB"
    assert format_size(1024**3) == "1.00 GB"
