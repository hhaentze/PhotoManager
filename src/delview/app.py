import os
import sys
from pathlib import Path

import send2trash
from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QImageReader, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import QApplication, QFrame, QHBoxLayout, QLabel, QMessageBox, QPushButton, QVBoxLayout, QWidget

from delview.datahandler import get_video_preview, load_and_validate_json

# A simple dark theme for a sleek, modern look
STYLESHEET = """
    QWidget { background-color: #1e1e1e; color: #ffffff; font-family: Segoe UI, sans-serif; }
    QLabel { font-size: 14px; }
    QPushButton { background-color: #333333; border: 1px solid #555; padding: 8px; border-radius: 4px; }
    QPushButton:hover { background-color: #444444; }
    QPushButton:checked { background-color: #d32f2f; font-weight: bold; }
"""


class DuplicateResolver(QWidget):
    def __init__(self, groups):
        super().__init__()
        self.groups = groups  # List of lists: [ ["file1.jpg", "file2.jpg"], ... ]
        self.current_index = 0
        self.marked_for_deletion = set()

        self.setWindowTitle("Duplicate Resolver")
        self.resize(1000, 700)

        # Layouts
        self.main_layout = QVBoxLayout(self)

        self.header = QLabel()
        self.header.setAlignment(Qt.AlignCenter)
        self.header.setStyleSheet("font-size: 18px; font-weight: bold; margin: 10px;")
        self.main_layout.addWidget(self.header)

        self.cards_layout = QHBoxLayout()
        self.main_layout.addLayout(self.cards_layout)

        # Initialize a list to hold the current buttons
        self.current_buttons = []

        # Bottom Navigation
        nav_layout = QHBoxLayout()

        self.btn_prev = QPushButton("Previous (A)")
        self.btn_prev.clicked.connect(self.prev_group)

        self.btn_next = QPushButton("Next Group (D)")
        self.btn_next.clicked.connect(self.next_group)

        self.btn_finish = QPushButton("Finish & Empty Trash")
        self.btn_finish.clicked.connect(self.finish_session)
        self.btn_finish.setStyleSheet("background-color: #005a9e;")

        nav_layout.addWidget(self.btn_prev)
        nav_layout.addWidget(self.btn_next)
        nav_layout.addWidget(self.btn_finish)
        self.main_layout.addLayout(nav_layout)

        # Navigation Shortcuts
        QShortcut(QKeySequence("A"), self).activated.connect(self.prev_group)
        QShortcut(QKeySequence("D"), self).activated.connect(self.next_group)

        # Number Shortcuts for toggling deletion
        QShortcut(QKeySequence("1"), self).activated.connect(lambda: self.toggle_by_index(0))
        QShortcut(QKeySequence("2"), self).activated.connect(lambda: self.toggle_by_index(1))
        QShortcut(QKeySequence("3"), self).activated.connect(lambda: self.toggle_by_index(2))
        self.load_group()

    def clear_layout(self, layout):
        """Removes old images from memory and the UI when moving to the next group."""
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                self.clear_layout(item.layout())

    def load_group(self):

        if self.current_index >= len(self.groups):
            self.header.setText("All groups reviewed! Click Finish.")
            self.clear_layout(self.cards_layout)
            return

        self.header.setText(f"Reviewing Group {self.current_index + 1} of {len(self.groups)}")
        self.clear_layout(self.cards_layout)

        current_files = self.groups[self.current_index]

        # Pre-calculate sizes to find the largest (in bytes for exact precision)
        sizes = [os.path.getsize(f) if os.path.exists(f) else 0 for f in current_files]
        max_size = max(sizes) if sizes else -1
        all_equal = len(set(sizes)) <= 1  # True if all files are the exact same size

        self.current_buttons.clear()  # Reset the button list for the new group

        for index, filepath in enumerate(current_files):
            # Create a visual "Card" for each file
            card = QFrame()
            card.setStyleSheet("QFrame { border: 1px solid #444; border-radius: 6px; padding: 10px; }")
            card_layout = QVBoxLayout(card)

            # Fast Loading: Determine if Image or Video
            img_label = QLabel("Image/Video Missing or Invalid")
            img_label.setAlignment(Qt.AlignCenter)

            if os.path.exists(filepath):
                ext = os.path.splitext(filepath)[1].lower()
                video_exts = {".mp4", ".mkv", ".avi", ".mov"}

                pixmap = None
                if ext in video_exts:
                    pixmap = get_video_preview(filepath)
                else:
                    reader = QImageReader(filepath)
                    reader.setScaledSize(QSize(400, 400))
                    img = reader.read()
                    if not img.isNull():
                        pixmap = QPixmap.fromImage(img)

                if pixmap:
                    img_label.setPixmap(pixmap)

            # Metadata
            file_size = sizes[index]
            size_mb = file_size / (1024 * 1024)
            file_path_obj = Path(filepath)
            rel_dir = file_path_obj.parent
            name = file_path_obj.name
            meta_label = QLabel(f"{rel_dir}\n{name}\nSize: {size_mb:.2f} MB")
            meta_label.setAlignment(Qt.AlignCenter)
            # Highlight the largest file in green, but only if sizes are actually different
            if not all_equal and file_size == max_size and file_size > 0:
                meta_label.setStyleSheet("border: none; color: #4CAF50; font-weight: bold;")  # Green
            else:
                meta_label.setStyleSheet("border: none; color: #aaa;")  # Default gray

            # Delete Toggle Button
            btn_delete = QPushButton(f"Mark for Deletion ({index + 1})")
            btn_delete.setCheckable(True)
            btn_delete.setChecked(filepath in self.marked_for_deletion)
            btn_delete.toggled.connect(lambda checked, f=filepath: self.toggle_delete(f, checked))

            self.current_buttons.append(btn_delete)  # Store it so our 1-2-3 keys can find it

            card_layout.addWidget(img_label)
            card_layout.addWidget(meta_label)
            card_layout.addWidget(btn_delete)
            self.cards_layout.addWidget(card)

    def toggle_delete(self, filepath, is_checked):
        if is_checked:
            self.marked_for_deletion.add(filepath)
        else:
            self.marked_for_deletion.discard(filepath)

    def toggle_by_index(self, index):
        """Simulates a click on the corresponding delete button if it exists."""
        if index < len(self.current_buttons):
            self.current_buttons[index].toggle()

    def next_group(self):
        self.current_index += 1
        self.load_group()

    def prev_group(self):
        if self.current_index > 0:
            self.current_index -= 1
            self.load_group()

    def keyPressEvent(self, event):
        """Map the Spacebar to the Next button."""
        if event.key() == Qt.Key_Space:
            self.next_group()

    def finish_session(self):
        if not self.marked_for_deletion:
            QMessageBox.information(self, "Finished", "No files were marked for deletion.")
            self.close()
            return

        # Double-check with the user before moving files
        reply = QMessageBox.question(
            self,
            "Confirm Deletion",
            f"Are you sure you want to move {len(self.marked_for_deletion)} files to the Recycle Bin?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )

        if reply == QMessageBox.StandardButton.Yes:
            success_count = 0
            error_count = 0

            for filepath in self.marked_for_deletion:
                try:
                    # Crucial: This moves to the OS Trash, it does NOT permanently delete
                    send2trash.send2trash(filepath)
                    success_count += 1
                except Exception as e:
                    print(f"Error moving {filepath} to trash: {e}")
                    error_count += 1

            msg = f"Successfully moved {success_count} files to the Recycle Bin."
            if error_count > 0:
                msg += f"\nFailed to move {error_count} files (check console for locked file errors)."

            QMessageBox.information(self, "Cleanup Complete", msg)
            self.close()


def main():
    # Import QApplication here if not already imported at the top

    app = QApplication(sys.argv)
    app.setStyleSheet(STYLESHEET)

    # Get the directory where the script was started
    current_directory = Path.cwd()

    # Load and validate the data
    valid_groups = load_and_validate_json(current_directory)

    if not valid_groups:
        # Prevent the app from opening an empty, useless window
        QMessageBox.warning(
            None,
            "No Data",
            "Could not find valid duplicate groups in exact_binary_duplicates.json "
            "or visual_duplicates.json in the current directory.",
        )
        sys.exit()

    window = DuplicateResolver(valid_groups)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
