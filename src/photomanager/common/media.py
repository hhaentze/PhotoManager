"""Media preview helpers shared by the GUI tools (delview, timeInject).

Depends on cv2 and PySide6, so it is only imported by the GUI packages and
never by the lightweight cais/mover tools.
"""

import cv2
from PySide6.QtGui import QImage, QPixmap


def get_video_preview(filepath, max_size: int = 400):
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
