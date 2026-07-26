from pathlib import Path

import typer

from mover.extract import extract_cais_files
from mover.pull import pull_cais_files
from photomanager.common import contract

app = typer.Typer(help="CAIS File Mover CLI", no_args_is_help=True)


@app.command()
def extract(
    source_path: str = typer.Argument(..., help="Path to the external directory"),
    json_path: str = typer.Option(
        str(Path(contract.CAIS_DIR) / contract.NEW_FILES), "--json-path", help="Path to JSON file"
    ),
    target_dir: str = typer.Option(".temp_store", "--target-dir", help="Hidden target directory"),
) -> None:
    """Copy new files to a temp store."""
    extract_cais_files(source_path, json_path, target_dir)


@app.command()
def pull(
    db2_path: str = typer.Argument(..., help="Path to the external DB2 directory"),
    root_dir: str = typer.Option(".", "--root-dir", help="Target root directory (default: current dir)"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Execute the copy/overwrite/trash (default: dry run)"),
) -> None:
    """Pull new and modified files, backing up replaced files to trash."""
    pull_cais_files(db2_path, root_dir, yes)


def main():
    app()


if __name__ == "__main__":
    main()
