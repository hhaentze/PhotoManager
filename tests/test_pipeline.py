"""End-to-end pipeline test on a simulated photo library.

Drives the real cais + mover CLIs (no ML / LLM / Qt) through the multi-database
workflow:  init -> scan -> compare -> pull.

The critical safety invariants this guards:
  1. `mover pull` copies FROM the source database but never mutates it.
  2. Files that are overwritten or deleted in the target are first backed up
     to .trash, so a pull can never silently lose data.
"""

import contextlib
import hashlib
import os
from pathlib import Path

from typer.testing import CliRunner

import cais.cli
import mover.cli

runner = CliRunner()


@contextlib.contextmanager
def chdir(path: Path):
    prev = os.getcwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(prev)


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def snapshot(root: Path, names) -> dict:
    return {name: digest(root / name) for name in names}


def run(app, args, cwd: Path):
    with chdir(cwd):
        result = runner.invoke(app, args)
    assert result.exit_code == 0, f"{args} failed:\n{result.output}"
    return result


def test_pull_syncs_target_without_touching_source(tmp_path: Path) -> None:
    central = tmp_path / "central"
    backup = tmp_path / "backup"

    # --- Central library (the source of truth) ---
    write(central / "a.jpg", "AAA")
    write(central / "b.jpg", "BBB")
    write(central / "c.jpg", "CCC")  # not present in backup yet

    # --- Backup library (to be synced from central) ---
    write(backup / "a.jpg", "AAA")  # identical -> untouched
    write(backup / "b.jpg", "BBB_OLD")  # differs -> overwritten, old backed up
    write(backup / "d.jpg", "DDD")  # absent in central -> moved to trash

    # --- Index both databases ---
    run(cais.cli.app, ["init", "central"], central)
    run(cais.cli.app, ["scan", "--yes"], central)
    run(cais.cli.app, ["init", "backup"], backup)
    run(cais.cli.app, ["scan", "--yes"], backup)

    # --- Compare backup against central (writes the pull plan into backup/.cais) ---
    run(cais.cli.app, ["compare", str(central)], backup)

    new_and_modified = _load(backup, "cais_new_and_modified_files.json")
    missing = _load(backup, "cais_missing_on_disk.json")
    assert set(new_and_modified) == {"b.jpg", "c.jpg"}
    assert set(missing) == {"d.jpg"}

    # Snapshot the central data files right before the destructive operation
    central_before = snapshot(central, ["a.jpg", "b.jpg", "c.jpg"])

    # --- Pull from central into backup ---
    run(mover.cli.app, ["pull", str(central), "--yes"], backup)

    # 1. SOURCE UNTOUCHED: central's data files are byte-for-byte identical
    assert snapshot(central, ["a.jpg", "b.jpg", "c.jpg"]) == central_before
    assert not (central / "d.jpg").exists()  # nothing leaked back into the source
    assert not (central / ".trash").exists()

    # 2. TARGET SYNCED: backup now mirrors central's data
    assert (backup / "a.jpg").read_text() == "AAA"
    assert (backup / "b.jpg").read_text() == "BBB"
    assert (backup / "c.jpg").read_text() == "CCC"
    assert not (backup / "d.jpg").exists()  # removed from its location

    # 3. NOTHING LOST: overwritten + deleted originals are preserved in trash
    trashed_deleted = list(backup.glob(".trash/*/deleted/d.jpg"))
    trashed_modified = list(backup.glob(".trash/*/modified/b.jpg"))
    assert len(trashed_deleted) == 1 and trashed_deleted[0].read_text() == "DDD"
    assert len(trashed_modified) == 1 and trashed_modified[0].read_text() == "BBB_OLD"


def test_pull_dry_run_makes_no_changes(tmp_path: Path) -> None:
    central = tmp_path / "central"
    backup = tmp_path / "backup"
    write(central / "a.jpg", "AAA")
    write(central / "b.jpg", "BBB")
    write(backup / "a.jpg", "AAA")
    write(backup / "b.jpg", "BBB_OLD")

    run(cais.cli.app, ["init", "central"], central)
    run(cais.cli.app, ["scan", "--yes"], central)
    run(cais.cli.app, ["init", "backup"], backup)
    run(cais.cli.app, ["scan", "--yes"], backup)
    run(cais.cli.app, ["compare", str(central)], backup)

    before = snapshot(backup, ["a.jpg", "b.jpg"])

    # No --yes: dry run must not modify anything
    run(mover.cli.app, ["pull", str(central)], backup)

    assert snapshot(backup, ["a.jpg", "b.jpg"]) == before
    assert not (backup / ".trash").exists()


def _load(root: Path, filename: str):
    from photomanager.common import contract

    return contract.load(root / contract.CAIS_DIR / filename)
