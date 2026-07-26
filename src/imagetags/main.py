"""
Photo renamer using Ollama vision models.
Renames photos based on their content description from a visual language model.
"""

import argparse
import glob
import os
import shutil as sh
import sys
from pathlib import Path

from PIL import Image
from tqdm import tqdm

from imagetags import ai_content, name_methods, time_methods
from imagetags.logger import setup_logging


def setup_argparse() -> argparse.ArgumentParser:
    """Setup command line argument parser."""
    parser = argparse.ArgumentParser(description="Rename photos based on content using Ollama vision models")
    parser.add_argument("--input", "-i", required=False, type=Path, help="Input folder containing images")
    parser.add_argument("--output", "-o", required=False, type=Path, help="Output folder for renamed images")
    return parser


def validate_args(args: any) -> None:
    # Validate input directory
    if not args.input.exists():
        print(f"Error: Input directory '{args.input}' does not exist")
        sys.exit(1)

    if not args.input.is_dir():
        print(f"Error: Input path '{args.input}' is not a directory")
        sys.exit(1)


def main():
    """Main entry point."""

    logger = setup_logging(__name__)
    parser = setup_argparse()
    args = parser.parse_args()

    basepath = Path(os.environ.get("PHOTOMANAGER_DATA", "data"))
    if not args.input:
        args.input = basepath / "input"
    if not args.output:
        args.output = basepath / "output"

    validate_args(args)
    logger.info(f"Load from {args.input}")
    logger.info(f"Save to {args.output}")

    # ---- start logic ----

    existing_files = glob.glob(str(args.output / "*"))
    existing_hashes = [Path(f).stem for f in existing_files if "_" in Path(f).stem]
    existing_hashes = {name.split("_")[-1]: name for name in existing_hashes if len(name.split("_")[-1]) == 4}
    if existing_hashes:
        logger.info(f"Found {len(existing_hashes)} renamed files in target directory")

    files = glob.glob(str(args.input / "*"))
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
                        sh.copy(f, args.output / name)
                    else:
                        # png do not support timestamp injection with piexif, hence I save it as a jpg
                        name = name.replace(filetype, ".jpg")
                        Image.open(f).convert("RGB").save(args.output / name, quality=95)

                    time_methods.inject_time(args.output / name, timestamp)
                    message += f" (updated date to {timestamp})"
                elif len(timestamp) > 0:
                    raise Exception(f, name, timestamp)
                else:
                    sh.copy(f, str(args.output) + "_notime/" + name)
                    message += " (missing timestamp)"
            else:
                sh.copy(f, args.output / name)

            tqdm.write(message)
        except Exception as e:
            sh.copy(f, str(args.output) + "_failed/" + Path(f).name)
            print(f"Failed for file {f}:", e)

    # ---- finish up ----

    logger.info("Done! Renamed images all saved.")


if __name__ == "__main__":
    main()
