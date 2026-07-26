"""Unit tests for the .cais/ report contract (round-trip + versioned envelope)."""

import json
from dataclasses import dataclass
from pathlib import Path

from photomanager.common import contract


def test_dump_load_round_trip(tmp_path: Path) -> None:
    payload = ["a.jpg", "sub/b.jpg"]
    p = tmp_path / contract.NEW_FILES
    contract.dump(p, payload)
    assert contract.load(p) == payload


def test_dump_writes_versioned_envelope(tmp_path: Path) -> None:
    p = tmp_path / contract.NEW_FILES
    contract.dump(p, ["x.jpg"])
    raw = json.loads(p.read_text())
    assert raw == {"schema_version": contract.SCHEMA_VERSION, "items": ["x.jpg"]}


def test_load_tolerates_legacy_bare_payload(tmp_path: Path) -> None:
    """Files written before the envelope existed are still readable."""
    p = tmp_path / contract.NEW_FILES
    p.write_text(json.dumps(["legacy.jpg"]))
    assert contract.load(p) == ["legacy.jpg"]


def test_build_duplicates_payload_shape() -> None:
    @dataclass
    class Group:
        original: str
        duplicates: list

    groups = [Group("orig.jpg", [["dup.jpg", "hash"]])]
    assert contract.build_duplicates_payload(groups) == {
        "orig.jpg": {"representative": "orig.jpg", "duplicates": [["dup.jpg", "hash"]]}
    }


def test_build_duplicates_payload_uses_group_index_without_representative() -> None:
    @dataclass
    class Group:
        original: None
        duplicates: list

    groups = [Group(None, [["a.jpg", "phash"]])]
    assert contract.build_duplicates_payload(groups) == {
        "group_0": {"representative": None, "duplicates": [["a.jpg", "phash"]]}
    }
