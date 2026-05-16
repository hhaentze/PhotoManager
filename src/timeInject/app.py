#!/usr/bin/env python3
"""Photo/video file date editor — edits embedded EXIF/container timestamps via exiftool."""

import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import cv2
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

STYLESHEET = """
    QWidget { background-color: #1e1e1e; color: #ffffff; font-family: Segoe UI, sans-serif; }
    QLabel { font-size: 14px; }
    QPushButton { background-color: #333333; border: 1px solid #555; padding: 8px 16px; border-radius: 4px; }
    QPushButton:hover { background-color: #444444; }
    QPushButton:disabled { color: #555; border-color: #333; }
    QLineEdit { background-color: #2a2a2a; border: 1px solid #555; padding: 6px; border-radius: 4px; font-size: 14px; }
"""

MEDIA_EXTS = {
    ".jpg",
    ".jpeg",
    ".tiff",
    ".tif",
    ".heic",
    ".heif",
    ".webp",
    ".png",  # images
    ".mp4",
    ".mov",
    ".avi",
    ".mkv",
    ".m4v",
    ".3gp",  # videos
    ".gif",
}
DATE_FMT = "%Y-%m-%d %H:%M:%S"

# Tag priority: first match wins when reading; all are written on save
EXIF_TAGS = ["DateTimeOriginal", "CreateDate", "MediaCreateDate", "TrackCreateDate"]


def find_exiftool() -> str:
    """Locate exiftool binary: PATH → common conda dirs → ask user."""
    if found := shutil.which("exiftool"):
        return found
    conda_root = Path(os.environ.get("CONDA_PREFIX", os.environ.get("CONDA_EXE", "/opt/conda")))
    for candidate in [
        conda_root / "bin" / "exiftool",
        conda_root.parent.parent / "bin" / "exiftool",  # base env
        Path.home() / "anaconda3" / "bin" / "exiftool",
        Path.home() / "miniconda3" / "bin" / "exiftool",
        Path.home() / "miniforge3" / "bin" / "exiftool",
    ]:
        if candidate.is_file():
            return str(candidate)

    # Last resort: ask the user to locate it
    path, _ = QFileDialog.getOpenFileName(None, "Locate exiftool binary")
    if path:
        return path
    QMessageBox.critical(None, "exiftool not found", "Could not locate exiftool. Install it and re-run the script.")
    sys.exit(1)


EXIFTOOL = find_exiftool()


def exiftool_read(path: Path) -> str | None:
    """Return the best available embedded timestamp as a display string, or None."""
    args = [EXIFTOOL, "-s3"] + [f"-{t}" for t in EXIF_TAGS] + [str(path)]
    result = subprocess.run(args, capture_output=True, text=True)
    for line in result.stdout.splitlines():
        line = line.strip()
        if line:
            try:
                return datetime.strptime(line[:19], "%Y:%m:%d %H:%M:%S").strftime(DATE_FMT)
            except ValueError:
                continue
    return None


def exiftool_write(path: Path, dt: datetime):
    """Write timestamp to all relevant embedded tags and sync mtime."""
    exif_str = dt.strftime("%Y:%m:%d %H:%M:%S")
    tag_args = [f"-{t}={exif_str}" for t in EXIF_TAGS]
    subprocess.run([EXIFTOOL, "-overwrite_original", "-P"] + tag_args + [str(path)], capture_output=True)
    os.utime(path, (dt.timestamp(), dt.timestamp()))


def get_video_preview(filepath, max_size=400):
    """Extracts the first frame of a video, resizes it, and returns a QPixmap."""
    cap = cv2.VideoCapture(filepath)
    ret, frame = cap.read()
    cap.release()

    if not ret:
        return None  # Could not read the video

    # Resize the frame using OpenCV to save memory before converting to Qt
    h, w = frame.shape[:2]
    scale = max_size / max(h, w)
    if scale < 1:
        frame = cv2.resize(frame, (int(w * scale), int(h * scale)))

    # OpenCV loads images in BGR format; Qt expects RGB
    rgb_image = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    h, w, ch = rgb_image.shape
    bytes_per_line = ch * w

    # Create the QImage from the raw byte data
    qt_img = QImage(rgb_image.data, w, h, bytes_per_line, QImage.Format_RGB888)
    return QPixmap.fromImage(qt_img)


class PhotoDateEditor(QMainWindow):
    def __init__(self, folder: str):
        super().__init__()
        self.images = sorted(p for p in Path(folder).iterdir() if p.suffix.lower() in MEDIA_EXTS)
        self.index = 0
        self._build_ui()
        self._load()

    def _build_ui(self):
        self.setWindowTitle("Photo / Video Date Editor")
        self.resize(800, 640)

        self.image_label = QLabel(alignment=Qt.AlignCenter)
        self.image_label.setMinimumHeight(480)
        self.image_label.setStyleSheet("border: 1px solid #333;")

        self.file_label = QLabel()
        self.file_label.setStyleSheet("color: #aaa; font-size: 12px;")

        self.source_label = QLabel()
        self.source_label.setStyleSheet("color: #666; font-size: 11px;")

        self.date_edit = QLineEdit()
        self.date_edit.setPlaceholderText(DATE_FMT)

        self.save_btn = QPushButton("💾 Save & Next")
        self.save_btn.clicked.connect(self._save_and_next)

        self.skip_btn = QPushButton("⏭ Skip")
        self.skip_btn.clicked.connect(self._next)

        self.counter_label = QLabel(alignment=Qt.AlignRight)
        self.counter_label.setStyleSheet("color: #888; font-size: 12px;")

        btn_row = QHBoxLayout()
        btn_row.addWidget(self.skip_btn)
        btn_row.addStretch()
        btn_row.addWidget(self.save_btn)

        layout = QVBoxLayout()
        layout.setSpacing(8)
        layout.addWidget(self.image_label)
        layout.addWidget(self.file_label)
        layout.addWidget(self.source_label)
        layout.addWidget(QLabel("Timestamp:"))
        layout.addWidget(self.date_edit)
        layout.addLayout(btn_row)
        layout.addWidget(self.counter_label)

        container = QWidget()
        container.setLayout(layout)
        container.setContentsMargins(16, 16, 16, 16)
        self.setCentralWidget(container)

    def _load(self):
        if self.index >= len(self.images):
            self.file_label.setText("All files processed.")
            self.source_label.clear()
            self.image_label.clear()
            self.date_edit.clear()
            self.save_btn.setEnabled(False)
            self.skip_btn.setEnabled(False)
            return

        path = self.images[self.index]
        self.file_label.setText(str(path))
        self.counter_label.setText(f"{self.index + 1} / {len(self.images)}")
        self.date_edit.setStyleSheet("")

        pixmap = QPixmap(str(path))
        if not pixmap.isNull():
            self.image_label.setPixmap(pixmap.scaled(760, 480, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        else:
            # self.image_label.setText(f"🎬 {path.name}\n(video preview not supported)")
            pixmap = get_video_preview(str(path))
            self.image_label.setPixmap(pixmap.scaled(760, 480, Qt.KeepAspectRatio, Qt.SmoothTransformation))

        embedded = exiftool_read(path)
        if embedded:
            self.date_edit.setText(embedded)
            self.source_label.setText("📷 source: embedded EXIF / container metadata")
        else:
            self.date_edit.setText(datetime.fromtimestamp(os.path.getmtime(path)).strftime(DATE_FMT))
            self.source_label.setText("⚠️  source: filesystem mtime (no embedded date found)")

    def _next(self):
        self.index += 1
        self._load()

    def _save_and_next(self):
        try:
            dt = datetime.strptime(self.date_edit.text().strip(), DATE_FMT)
        except ValueError:
            self.date_edit.setStyleSheet("border: 1px solid #d32f2f;")
            return
        exiftool_write(self.images[self.index], dt)
        self._next()


def main():
    app = QApplication(sys.argv)
    app.setStyleSheet(STYLESHEET)

    folder = QFileDialog.getExistingDirectory(None, "Select media folder")
    if not folder:
        sys.exit(0)

    window = PhotoDateEditor(folder)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
