import json
from pathlib import Path

from photomanager.common import contract
from photomanager.common.media import get_video_preview  # noqa: F401  (re-exported for app.py)


def load_and_validate_json(start_dir):
    base_path = Path(start_dir).resolve()
    json_files = [str(Path(contract.CAIS_DIR) / contract.DUPLICATES)]

    all_valid_groups = []

    for filename in json_files:
        file_path = base_path / filename
        if not file_path.exists():
            continue

        try:
            data = contract.load(file_path)

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
