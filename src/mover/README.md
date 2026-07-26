# mover — Move files between libraries

`mover` performs the actual file operations that `cais` only plans. It reads the
JSON [report files](../../README.md#the-cais-contract) from `.cais/` and acts on
them. Both commands are **dry-run by default**.

## Commands

Run from inside the target library directory.

### `mover extract <source> [--json-path …] [--target-dir …]`
Copies the files listed in `cais_new_files.json` from `<source>` into a
`.temp_store/` folder (default). Purely **additive**: it skips files that already
exist and never overwrites. Useful for pulling only genuinely new files out of a
messy source folder.

### `mover pull <source> [--root-dir …] [--yes]`
Brings the current library up to date with `<source>`, using
`cais_new_and_modified_files.json` (files to copy) and `cais_missing_on_disk.json`
(files to remove). Without `--yes` it prints a skim report and exits.

With `--yes` it, in order:
1. moves files marked for deletion to `.trash/<date>/deleted/`,
2. copies files about to be overwritten to `.trash/<date>/modified/`,
3. copies the new/changed files from `<source>`.

## Safety

- **The source (`<source>` / db2) is never modified** — pull only reads from it.
- Every overwritten or deleted file is preserved under `.trash/` before any
  destructive step, so a pull can always be undone.
- `extract` never overwrites existing files in the target.

## Layout

- `extract.py` — `mover extract` implementation.
- `pull.py` — `mover pull` implementation.
- `cli.py` — the Typer command-line interface.
