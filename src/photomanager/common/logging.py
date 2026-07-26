import logging


class LevelBasedFormatter(logging.Formatter):
    """Custom formatter that uses different formats based on log level"""

    def __init__(self):
        super().__init__()

        # Define different formats for each level
        self.formats = {
            logging.DEBUG: "[DEBUG] %(filename)s:%(lineno)d - %(message)s",
            logging.INFO: "%(asctime)s - %(message)s",
            logging.WARNING: "[WARNING] %(asctime)s %(filename)s:%(lineno)d - %(message)s",
            logging.ERROR: "[ERROR] %(asctime)s %(filename)s:%(lineno)d - %(message)s",
            logging.CRITICAL: "[CRITICAL] %(asctime)s %(filename)s:%(lineno)d - %(message)s",
        }

        self.date_format = "%H:%M:%S"

    def format(self, record):
        format_string = self.formats.get(record.levelno, self.formats[logging.INFO])
        formatter = logging.Formatter(format_string, self.date_format)
        return formatter.format(record)


def setup_logging(level: int = logging.INFO) -> None:
    """Configure the root logger with the level-based formatter.

    Callers should obtain their own logger via ``logging.getLogger(__name__)``.
    """
    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    # Clear any existing handlers (important to avoid duplicates)
    root_logger.handlers.clear()

    console_handler = logging.StreamHandler()
    console_handler.setLevel(level)
    console_handler.setFormatter(LevelBasedFormatter())
    root_logger.addHandler(console_handler)
