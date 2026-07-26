# delview — Review and remove duplicates

A small PySide6 GUI for working through the duplicate groups that `cais` found.
It reads `.cais/cais_duplicates.json` from the current directory and shows each
group side by side (images and video thumbnails), highlighting the largest file.

Requires the `gui` extra: `uv sync --extra gui`.

## Usage

```bash
cd /path/to/library    # must contain .cais/cais_duplicates.json
delview
```

- `A` / `D` — previous / next group
- `1` / `2` / `3` — toggle a file for deletion
- **Finish** — review, confirm, and send the ticked files to the OS trash.

## Safety

- Only files you explicitly tick and then confirm are removed.
- Removal uses the **OS trash** (`Send2Trash`), so it is recoverable — nothing is
  permanently deleted.
- A duplicate group is only shown if at least two of its files still exist, and
  paths are validated to stay inside the library directory.
