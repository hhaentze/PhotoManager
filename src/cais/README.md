# cais — Content-Addressed Indexing System

The database layer. `cais` indexes a photo library by **content hash** (blake3)
and optional **perceptual hash**, detects duplicates, and compares one library
against another. It is **read-only on your media** — it only ever writes to its
own `.cais/` folder.

Each library keeps a hidden `.cais/` directory containing the SQLite index
(`.cais.db`) and the JSON [report files](../../README.md#the-cais-contract).

## Commands

Run from inside the library directory.

| Command | Description |
|---------|-------------|
| `cais init <name>` | Create a new database in the current directory. |
| `cais scan [path]` | Report changes since the last index. **Dry run** unless `--yes`. With no `path`, scans the current library; with a `path`, scans an external folder (read-only, cannot be committed). |
| `cais status` | Print database statistics and known duplicates. |
| `cais compare <target>` | Diff this library against another cais-managed library, writing a pull plan into `.cais/`. |

Flags for `scan`:
- `--perceptual` — also compute perceptual hashes (catches near-duplicate images).
- `--yes` / `-y` — commit the changes to the database (otherwise dry run).

## Safety

- Never deletes, moves, or overwrites media files.
- `compare` opens the target database **read-only**.
- Writes only inside `.cais/` (the index and JSON reports).

## Layout

- `db.py` — SQLite schema and access (`IndexDB`, `DataPoint`, `DuplicateGroup`).
- `reconciler.py` — disk scanning, hashing, duplicate grouping, `compare_dbs`.
- `cli.py` — the Typer command-line interface.
