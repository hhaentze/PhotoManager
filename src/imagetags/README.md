# imagetags — Content-based renaming

Renames photos to short, descriptive names (e.g. `sunset_beach.jpg`) using a
local **Ollama** vision model, and ensures each file has a correct timestamp. A
short content hash is appended to keep names unique and to skip files that were
already processed.

## Requirements

- A running [Ollama](https://ollama.com) with a vision model (default `llava:13b`).
- `ffmpeg` for hashing video files — on `PATH`, or set `PHOTOMANAGER_FFMPEG`.

## Usage

```bash
imagetags -i <input_folder> -o <output_folder>
```

If `-i` / `-o` are omitted they default to `input` / `output` under
`$PHOTOMANAGER_DATA` (the current directory's `data/` if unset).

For each file it:
1. computes a metadata-independent content hash (last 4 base36 chars → the name suffix),
2. asks the vision model for a 2–3 word description (skipped for videos),
3. checks for a valid date; if none is embedded, tries to recover one from the
   filename and injects it into the EXIF.

Files land in the output folder; those needing manual date entry go to
`<output>_notime/` (see [timeInject](../timeInject/README.md)), and failures to
`<output>_failed/`.

## Layout

- `main.py` — CLI entry point and the processing loop.
- `ai_content.py` — Ollama prompt and `generate_filename`.
- `name_methods.py` — hashing, base36 encoding, name validation.
- `time_methods.py` — timestamp extraction (filename + EXIF) and injection.
