# PhotoManager
> A suite for intelligent, safe photo backup and organization.

[![CI](https://github.com/hhaentze/PhotoManager/actions/workflows/ci.yml/badge.svg)](https://github.com/hhaentze/PhotoManager/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
![Python](https://img.shields.io/badge/python-3.11%2B-blue)
[![Code style: ruff](https://img.shields.io/badge/code%20style-ruff-000000.svg)](https://github.com/astral-sh/ruff)

PhotoManager centralizes photos from many sources (phone camera, WhatsApp,
other devices) into one **year-based library** of **uniquely-named, de-duplicated**
files, and makes incremental backups to other drives pull **only genuinely new files**.

It is intentionally split into small, single-purpose tools so that each has a
narrow, auditable effect on your files (see [Safety model](#safety-model)).

## Tools

| Tool | Purpose | Docs |
|------|---------|------|
| **cais** | Content-addressed index/database of a photo library; scans, finds duplicates, compares libraries. Read-only on your media. | [src/cais](src/cais/README.md) |
| **mover** | Copies/moves files between libraries based on cais reports (extract new files, pull a backup up to date). | [src/mover](src/mover/README.md) |
| **imagetags** | Renames photos to short, content-descriptive names using a local vision model (Ollama), and fixes timestamps. | [src/imagetags](src/imagetags/README.md) |
| **timeInject** | GUI to review and correct embedded EXIF/container timestamps. | [src/timeInject](src/timeInject/README.md) |
| **delview** | GUI to review duplicate groups and send unwanted copies to the OS trash. | [src/delview](src/delview/README.md) |

## Install

Uses [uv](https://docs.astral.sh/uv/). Python 3.11+.

```bash
uv sync                 # core tools (cais, mover, imagetags)
uv sync --extra gui     # + GUI tools (delview, timeInject): PySide6, OpenCV
uv sync --extra dev     # + dev tooling (ruff, mypy, pytest)
```

`imagetags` additionally needs a running [Ollama](https://ollama.com) with a
vision model, and `ffmpeg` for video hashing. `timeInject` needs the external
`exiftool` binary.

## Core concepts

- **Content-addressed database (`cais`).** Each library has a hidden `.cais/`
  folder holding a SQLite index (`.cais.db`) keyed by file **content hash**
  (blake3), plus optional **perceptual hashes** for near-duplicate images.
  Moving or renaming a file doesn't confuse it — identity follows content.
- **The `.cais/` report files.** cais writes its findings as JSON into `.cais/`;
  mover and delview read them. This is a versioned [contract](#the-cais-contract).
- **Year-based library.** The central library is organised as `database/<year>/…`.

## Safety model

The whole point of the multi-tool split is that **each tool's authority over
your files is narrow and predictable**:

| Tool | May write / move / delete | Never touches |
|------|---------------------------|---------------|
| **cais** | Only its own `.cais/` folder (DB + JSON reports) | Your media files — read-only, always |
| **mover extract** | Copies into a fresh `.temp_store/` (skips existing, never overwrites) | The source directory |
| **mover pull** | The **current/target** library only; backs up every overwritten or deleted file to `.trash/<date>/` first | The **source** library (read-only) |
| **delview** | Sends files you explicitly tick to the **OS trash** (recoverable) | Anything not confirmed in the dialog |
| **timeInject** | Edits EXIF/container timestamps in place | File contents / names |

Two rules hold across the mutating commands:

- **Dry-run by default.** `cais scan` and `mover pull` make no changes unless you
  pass `--yes`. Without it they print exactly what *would* happen.
- **Back up before destroying.** `mover pull` moves deleted files and copies
  overwritten files into `.trash/` before writing, so a pull can never silently
  lose data.

## Workflows

### A. Add new photos to the central library

```bash
# 1. Generate content-based names + fix timestamps (needs Ollama + ffmpeg)
#    Reads $PHOTOMANAGER_DATA/input, writes to $PHOTOMANAGER_DATA/output
imagetags
# 2. (optional) Manually fix any timestamps that couldn't be detected
timeInject
# 3. Move the renamed files into the year folder, e.g. database/2026/
# 4. Update the library index (perceptual hashing catches near-duplicates)
cd /path/to/database
cais scan --perceptual --yes
```

### B. Sync a backup drive from the central library

Run this **from the backup library**; it pulls only what's new/changed and
mirrors deletions, backing up anything it replaces.

```bash
cd /path/to/backup
cais scan --yes                 # index the backup's current state
cais compare /path/to/central   # write the pull plan into .cais/
mover pull /path/to/central     # DRY RUN: shows what would change
mover pull /path/to/central --yes   # execute (replaced files go to .trash/)
```

### Unsure which files are already backed up?

```bash
cd /path/to/central
cais scan /path/to/new_files    # scan an external folder (dry run)
mover extract /path/to/new_files   # copy only the new ones to .temp_store/
```

## The `.cais/` contract

cais writes these files into `.cais/`; mover and delview read them. Each is
wrapped in a versioned envelope `{"schema_version": 1, "items": …}` so the
format can evolve safely. Defined once in `photomanager.common.contract`.

| File | Contents | Written by | Read by |
|------|----------|-----------|---------|
| `cais_new_files.json` | Paths with no duplicate anywhere in the library | `cais scan` | `mover extract` |
| `cais_new_and_modified_files.json` | Paths to fetch (new or changed vs. the compared library) | `cais scan` / `compare` | `mover pull` |
| `cais_missing_on_disk.json` | Indexed paths absent from disk / the compared library | `cais scan` / `compare` | `mover pull` |
| `cais_duplicates.json` | Duplicate groups (exact + perceptual) | `cais scan` / `status` | `delview` |

## Development

```bash
make install-dev   # uv sync --extra dev
make lint          # ruff check + format check
make type          # mypy
make test          # pytest (fast; no ML/LLM/GUI needed)
make ci            # lint + type + test
```

CI (GitHub Actions) runs lint, type-check, and tests on every push and pull
request. See [.github/workflows/ci.yml](.github/workflows/ci.yml).
