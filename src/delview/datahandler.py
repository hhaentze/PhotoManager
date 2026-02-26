import json
from pathlib import Path

import cv2
from PySide6.QtGui import QImage, QPixmap


def load_and_validate_json(start_dir):
    base_path = Path(start_dir).resolve()
    json_files = [".cais/cais_duplicates.json"]

    all_valid_groups = []

    for filename in json_files:
        file_path = base_path / filename
        if not file_path.exists():
            continue

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            valid_groups = []
            for entry in data.values():
                valid_files = []
                for duplicate in entry["duplicates"]:
                    # Resolve creates an absolute path and resolves any ".."
                    rel_path = duplicate[0]
                    target_path = (base_path / rel_path).resolve()

                    # Security Check: Ensure the target is inside our base directory
                    # and that the file actually exists on the hard drive.
                    if target_path.is_relative_to(base_path) and target_path.is_file():
                        valid_files.append(str(target_path))

                # Only add the group if we still have at least 2 valid files to compare
                if len(valid_files) > 1:
                    all_valid_groups.append(valid_files)
                valid_groups.append(valid_files)

        except json.JSONDecodeError:
            print(f"Warning: {filename} is not a valid JSON file.")

    return all_valid_groups


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
