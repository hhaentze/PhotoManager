"""
Photo renamer using Ollama vision models.
Renames photos based on their content description from a visual language model.
"""

import glob
import logging
import os
import shutil as sh
import sys
from pathlib import Path
from typing import Optional

import typer
from PIL import Image
from tqdm import tqdm

from imagetags import ai_content, name_methods, time_methods
from photomanager.common.logging import setup_logging


def validate_input(input_dir: Path) -> None:
    if not input_dir.exists():
        print(f"Error: Input directory '{input_dir}' does not exist")
        sys.exit(1)

    if not input_dir.is_dir():
        print(f"Error: Input path '{input_dir}' is not a directory")
        sys.exit(1)


def run(
    input_dir: Optional[Path] = typer.Option(None, "--input", "-i", help="Input folder containing images"),
    output_dir: Optional[Path] = typer.Option(None, "--output", "-o", help="Output folder for renamed images"),
) -> None:
    """Rename photos based on content using Ollama vision models."""

    setup_logging()
    logger = logging.getLogger(__name__)

    basepath = Path(os.environ.get("PHOTOMANAGER_DATA", "data"))
    if input_dir is None:
        input_dir = basepath / "input"
    if output_dir is None:
        output_dir = basepath / "output"

    validate_input(input_dir)
    logger.info(f"Load from {input_dir}")
    logger.info(f"Save to {output_dir}")

    # ---- start logic ----

    existing_files = glob.glob(str(output_dir / "*"))
    existing_hashes = [Path(f).stem for f in existing_files if "_" in Path(f).stem]
    existing_hashes = {name.split("_")[-1]: name for name in existing_hashes if len(name.split("_")[-1]) == 4}
    if existing_hashes:
        logger.info(f"Found {len(existing_hashes)} renamed files in target directory")

    files = glob.glob(str(input_dir / "*"))
    for f in tqdm(files, position=0, leave=True):
        # check hash
        hash = name_methods.remove_metadata_and_calculate_hash(f)
        base36_hash = name_methods.base36_encode(hash)
        idx = base36_hash[-4:]
        filetype = Path(f).suffix
        if idx in existing_hashes:
            tqdm.write(f"Skip already renamed file {Path(f).name} ({existing_hashes[idx]})")
            continue

        try:
            # names logic
            if filetype in [".mp4"]:
                response = Path(f).stem
            else:
                acceptable = False
                count = 0
                while not acceptable:
                    response = ai_content.generate_filename(f, ai_content.describe_content)

                    if name_methods.is_acceptable_name(response):
                        acceptable = True
                    elif count > 10:
                        raise Exception(f"Couldnt guess name for file {f}")
                    else:
                        count += 1
                        logger.info(f"Incorrect name for {Path(f).name}: {response}  -  Will try again x{count}")

            name = response + "_" + idx + filetype
            message = f"Renamed {Path(f).name} -> {name}"

            # time logic
            if filetype not in [".mp4"] and len(time_methods.extract_date_from_exif(f)) != 19:
                timestamp = time_methods.extract_timestamp(f)
                if len(timestamp) == 19:
                    if filetype != ".png":
                        sh.copy(f, output_dir / name)
                    else:
                        # png do not support timestamp injection with piexif, hence I save it as a jpg
                        name = name.replace(filetype, ".jpg")
                        Image.open(f).convert("RGB").save(output_dir / name, quality=95)

                    time_methods.inject_time(output_dir / name, timestamp)
                    message += f" (updated date to {timestamp})"
                elif len(timestamp) > 0:
                    raise Exception(f, name, timestamp)
                else:
                    sh.copy(f, str(output_dir) + "_notime/" + name)
                    message += " (missing timestamp)"
            else:
                sh.copy(f, output_dir / name)

            tqdm.write(message)
        except Exception as e:
            sh.copy(f, str(output_dir) + "_failed/" + Path(f).name)
            print(f"Failed for file {f}:", e)

    # ---- finish up ----

    logger.info("Done! Renamed images all saved.")


def main():
    typer.run(run)


if __name__ == "__main__":
    main()
