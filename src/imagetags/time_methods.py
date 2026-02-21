import re
from datetime import datetime
from pathlib import Path

import piexif
from PIL import Image
from pymediainfo import MediaInfo


def extract_timestamp(filename, max_year: int = 2025):
    # Patterns for matching human-readable and numeric timestamps

    filename = Path(filename).stem

    n1 = r"(?<!\d)"  # negative lookbehind
    n2 = r"(?!\d)"  # negative lookahead

    reg_date = n1 + r"(\d{4})(\d{2})(\d{2})" + n2
    reg_time = n1 + r"(\d{2})(\d{2})(\d{2})" + n2

    reg_date_only = reg_date + r"(?![_\-]\d{6})"
    reg_date_time = reg_date + r"[_\-]" + reg_time

    human_readable_patterns = [
        reg_date_only,  # e.g., MG_20210609_225212
        reg_date_time,  # e.g., IMG-20230201-WA0000
    ]
    numeric_patterns = [
        n1 + r"1\d{9}" + n2,  # Unix timestamp (10 digits)
        n1 + r"1\d{12}" + n2,  # Milliseconds Unix timestamp (13 digits)
    ]

    # To store matched timestamps
    matched_timestamps = []

    # Check human-readable patterns
    for pattern in human_readable_patterns:
        for match in re.findall(pattern, filename):
            try:
                if len(match) == 6:  # Full date and time
                    year, month, day, hour, minute, second = map(int, match)
                    dt = datetime(year, month, day, hour, minute, second)
                elif len(match) == 3:  # Only date
                    year, month, day = map(int, match)
                    dt = datetime(year, month, day)
                matched_timestamps.append(dt.timestamp())
            except ValueError:
                continue  # Skip invalid dates

    # Check numeric patterns
    for pattern in numeric_patterns:
        for match in re.findall(pattern, filename):
            try:
                timestamp = int(match)
                if len(match) == 13:  # Convert milliseconds to seconds
                    timestamp //= 1000
                dt = datetime.fromtimestamp(timestamp)
                # Validate the year range for Unix timestamps
                if 2010 <= dt.year <= max_year:
                    matched_timestamps.append(timestamp)
            except (ValueError, OverflowError):
                continue  # Skip invalid timestamps

    if matched_timestamps:
        # Find the earliest timestamp
        earliest_timestamp = min(matched_timestamps)
        # Convert back to ISO 8601 format
        return datetime.fromtimestamp(earliest_timestamp).strftime("%Y:%m:%d %H:%M:%S")

    return ""  # Return empty string if no valid timestamp is found


def extract_date_from_exif(file_path):
    try:
        img = Image.open(file_path)
        exif_data = piexif.load(img.info.get("exif", b""))
        date_time_original = exif_data["Exif"].get(piexif.ExifIFD.DateTimeOriginal)

        if date_time_original:
            # Decode bytes to string and return the date
            date_str = date_time_original.decode("utf-8")
            return date_str

        # else:
        #     return ""
    except Exception:
        pass  # Not an image or failed to extract EXIF

    # If it's not an image or EXIF extraction fails, treat it as a video
    media_info = MediaInfo.parse(file_path)
    for track in media_info.tracks:
        if track.track_type == "General":
            creation_date = track.tagged_date or track.recorded_date
            if creation_date:
                # Extract the date part from the timestamp
                date_str = creation_date.split("T")[0]  # Format: YYYY-MM-DDTHH:MM:SS
                return date_str

    return ""  # Return empty if no valid date is found


def inject_time(img_path, timestamp):
    img_path = str(img_path)
    exif_data = piexif.load(img_path)
    exif_data["Exif"][piexif.ExifIFD.DateTimeOriginal] = timestamp

    exif_bytes = piexif.dump(exif_data)
    piexif.insert(exif_bytes, img_path)
