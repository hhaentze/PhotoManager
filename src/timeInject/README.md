# timeInject — Fix photo/video timestamps

A PySide6 GUI for reviewing and correcting embedded **EXIF / container
timestamps**, one file at a time. Useful for media where an accurate date could
not be detected automatically during `imagetags`.

Requires the `gui` extra (`uv sync --extra gui`) and the external `exiftool`
binary (found on `PATH`, in common conda locations, or via a file picker).

## Usage

```bash
timeInject      # opens a folder picker, then steps through the media
```

For each file it shows the image (or a video's first frame) and the best
available timestamp — from embedded metadata, or the filesystem mtime as a
fallback. Edit the value and **Save & Next** to write it, or **Skip**.

## Safety

- Writes only timestamp tags (`DateTimeOriginal`, `CreateDate`, …) via
  `exiftool -overwrite_original -P`, and syncs the file's mtime.
- Does not rename, move, or otherwise alter file contents.
