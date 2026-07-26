"""The on-disk contract between the tools.

cais writes report files into ``.cais/``; mover and delview read them. This
module is the single source of truth for those filenames and their JSON
format, so the producer and consumers can never drift apart.

Every report is wrapped in a versioned envelope::

    {"schema_version": 1, "items": <payload>}

so the format can evolve without silently misreading old files.
"""

import json
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1

CAIS_DIR = ".cais"

# Report filenames (relative to CAIS_DIR)
NEW_FILES = "cais_new_files.json"
NEW_AND_MODIFIED = "cais_new_and_modified_files.json"
MISSING_ON_DISK = "cais_missing_on_disk.json"
DUPLICATES = "cais_duplicates.json"


def dump(path: Path, payload: Any) -> None:
    """Write ``payload`` to ``path`` inside the versioned envelope."""
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"schema_version": SCHEMA_VERSION, "items": payload}, f, indent=4)


def load(path: Path) -> Any:
    """Read a report file, returning its payload.

    Tolerates legacy files that were written as a bare payload (no envelope).
    """
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict) and "schema_version" in data:
        return data["items"]
    return data


def build_duplicates_payload(groups) -> dict:
    """Serialize duplicate groups to the shared JSON shape.

    ``groups`` is any iterable of objects exposing ``.original`` (Optional[str])
    and ``.duplicates`` (list of ``[path, match_type]``). The returned mapping is
    keyed by the representative path (or ``group_<i>`` when there is none)::

        {"<representative>": {"representative": ..., "duplicates": [[path, type], ...]}}
    """
    return {
        (group.original or f"group_{i}"): {
            "representative": group.original,
            "duplicates": group.duplicates,
        }
        for i, group in enumerate(groups)
    }
