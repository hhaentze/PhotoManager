import hashlib
import os
import string
import subprocess
import tempfile

from PIL import Image


def is_acceptable_name(name: str) -> bool:
    name = name.strip()
    if '"' in name:
        return False
    if "\\" in name:
        return False
    if name[0] == "_" or name[-1] == "_":
        return False
    if name.count("_") < 1:
        return False
    if name.count("_") > 2:
        return False
    if name.count("-") >= 1:
        return False
    return True


def remove_metadata_and_calculate_hash(file_path, hash_algorithm="md5"):
    """Calculate hash for images and videos without metadata."""
    if file_path.lower().endswith((".jpg", ".jpeg", ".png", ".bmp", ".gif", ".tiff", ".webp")):
        # Process image
        img = Image.open(file_path)
        img_data = img.tobytes()  # Extract pixel data as raw bytes

        # Hash the raw pixel data
        hash_func = hashlib.new(hash_algorithm)
        hash_func.update(img_data)

        return hash_func.hexdigest()

    elif file_path.lower().endswith((".mp4", ".avi", ".mkv", ".mov", ".wmv", ".flv")):
        # Process video
        # Use FFmpeg to strip metadata
        suffix = "." + file_path.split(".")[-1].lower()
        temp_dir = os.getcwd()

        with tempfile.NamedTemporaryFile(suffix=suffix, dir=temp_dir, delete=False) as temp_file:
            temp_file_path = temp_file.name

        try:
            # FFmpeg command to remove metadata
            ffmpeg_path = r"C:\Users\Hartmut\miniforge3\envs\ImageTags\Library\bin\ffmpeg.exe"
            subprocess.run(
                [ffmpeg_path, "-y", "-i", file_path, "-map", "0", "-map_metadata", "-1", "-c", "copy", temp_file_path],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=10,
            )

            # Hash the stripped video file
            hash_func = hashlib.new(hash_algorithm)
            with open(temp_file_path, "rb") as f:
                for chunk in iter(lambda: f.read(4096), b""):
                    hash_func.update(chunk)

        finally:
            # Clean up the temporary file
            if os.path.exists(temp_file_path):
                os.remove(temp_file_path)

        return hash_func.hexdigest()

    else:
        raise ValueError("Unsupported file type. Please provide an image or video file.")


def calc_hashmaps(files):
    hash2files = {}
    files2hash = {}

    for f in files:
        hash = remove_metadata_and_calculate_hash(f)
        hash2files[hash] = [f] if hash not in hash2files else hash2files[hash] + [f]
        files2hash[f] = hash

    return hash2files, files2hash


def extract_file_creation_date(image_path):
    try:
        # Get the file's creation or modification time
        timestamp = os.path.getmtime(image_path)  # Modification time
        from datetime import datetime

        date_obj = datetime.fromtimestamp(timestamp)
        return date_obj.strftime("%Y-%m-%d")
    except Exception:
        return ""  # Return empty in case of an error


def base36_encode(hash):
    num = int(hash, 16)

    base_chars = string.digits + string.ascii_lowercase  # 0-9 and a-z
    if num == 0:
        return base_chars[0]

    base_str = ""
    while num:
        num, rem = divmod(num, len(base_chars))
        base_str = base_chars[rem] + base_str
    return base_str
