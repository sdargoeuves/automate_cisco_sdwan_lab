import gzip
import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path


def setup_logging(verbose: bool) -> None:
    log_level = logging.DEBUG
    console_level = logging.DEBUG if verbose else logging.ERROR

    root_logger = logging.getLogger()
    if root_logger.handlers:
        return

    logs_dir = Path(__file__).resolve().parents[1] / "logs"
    logs_dir.mkdir(exist_ok=True)
    info_log_file = logs_dir / "sdwan_automation.log"
    debug_log_file = logs_dir / "sdwan_automation.debug.log"

    info_handler = RotatingFileHandler(
        info_log_file, maxBytes=2 * 1024 * 1024, backupCount=5
    )
    info_handler.rotator = _rotator
    info_handler.namer = _namer
    info_handler.setLevel(logging.INFO)
    info_handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    )

    debug_handler = RotatingFileHandler(
        debug_log_file, maxBytes=2 * 1024 * 1024, backupCount=5
    )
    debug_handler.rotator = _rotator
    debug_handler.namer = _namer
    debug_handler.setLevel(log_level)
    debug_handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    )

    console_handler = logging.StreamHandler()
    console_handler.setLevel(console_level)
    console_handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    )

    root_logger.setLevel(log_level)
    root_logger.addHandler(info_handler)
    root_logger.addHandler(debug_handler)
    root_logger.addHandler(console_handler)

    logging.getLogger("paramiko").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


def _rotator(source: str, dest: str) -> None:
    with open(source, "rb") as src, gzip.open(dest, "wb") as dst:
        dst.writelines(src)
    os.remove(source)


def _namer(name: str) -> str:
    return name + ".gz"
