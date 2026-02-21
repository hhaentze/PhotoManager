.PHONY: install install-dev lint format format-nbs test clean help

ci: lint type

# Installation
install:
	pip install -e .

install-dev:
	pip install -e ".[dev]"

# Linting 
lint:
	ruff check src tests
	ruff format --check src tests

# Formatting
format:
	ruff check --select I,F401 --fix src tests
	ruff format src tests

type:
	mypy src

# Cleaning (Cross-platform via Python)
clean:
	python -c "import pathlib; [p.unlink() for p in pathlib.Path('.').rglob('*.py[co]')]"
	python -c "import pathlib; [p.rmdir() for p in pathlib.Path('.').rglob('__pycache__')]"
	python -c "import shutil, pathlib; [shutil.rmtree(p) for p in pathlib.Path('.').rglob('*.egg-info')]"
	python -c "import shutil, pathlib; [shutil.rmtree(p) for p in pathlib.Path('.').rglob('.pytest_cache')]"
	python -c "import shutil, pathlib; [shutil.rmtree(p) for p in pathlib.Path('.').rglob('.mypy_cache')]"
	python -c "import shutil, pathlib; [shutil.rmtree(p) for p in pathlib.Path('.').rglob('.ruff_cache')]"
	python -c "import shutil, pathlib; [shutil.rmtree(p) for p in pathlib.Path('.').rglob('build')]"
	python -c "import shutil, pathlib; [shutil.rmtree(p) for p in pathlib.Path('.').rglob('dist')]"
	python -c "import shutil, pathlib; [shutil.rmtree(p) for p in pathlib.Path('.').rglob('htmlcov')]"
	@echo "Clean complete."

# Help
help:
	@echo "Available commands:"
	@echo "  install-dev    - Install package with development dependencies"
	@echo "  lint           - Run all linting checks (read-only)"
	@echo "  format         - Format code with black and ruff"
	@echo "  format-nbs     - Format jupyter notebooks with black and ruff"
	@echo "  test           - Run tests"
	@echo "  clean          - Clean build artifacts and caches"

# Default target
default: install-dev