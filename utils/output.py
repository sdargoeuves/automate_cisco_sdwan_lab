"""
Unified output helper for consistent logging and console output.

This module provides a single interface for both logging and user-facing output,
ensuring consistent formatting across all automation scripts.
"""

import sys
import threading
import time
from contextlib import contextmanager

from utils.logging import get_logger

# Standard width for headers and separators
HEADER_WIDTH = 60

# Status symbols
SYMBOLS = {
    "success": "✓",
    "error": "✗",
    "warning": "⚠",
    "info": "ℹ",
    "wait": "⏳",
    "rocket": "🚀",
}

# Serialize console writes so concurrent threads (parallel edge automation)
# don't interleave each other's output. Logging itself is already thread-safe.
_PRINT_LOCK = threading.Lock()

# Per-thread label inherited by Output() instances that don't set an explicit
# prefix — lets shared helpers (utils/netmiko, etc.) pick up the caller's label
# without changing every signature.
_thread_local = threading.local()


def _thread_prefix() -> str:
    return getattr(_thread_local, "prefix", "")


@contextmanager
def thread_label(label: str):
    """Set a label for the current thread; any Output() created inside this
    block (and any pre-existing Output without an explicit prefix) will pick
    it up. Restores the previous label on exit.

    Also renames the OS thread, so third-party loggers we don't control — chiefly
    netmiko, which logs raw channel I/O through one global logger — are
    attributable to a device via ``%(threadName)s``. Without it, parallel edge
    runs interleave into one undifferentiated stream. Worker threads only: the
    main thread keeps its name.
    """
    previous = _thread_prefix()
    _thread_local.prefix = label or ""
    current = threading.current_thread()
    previous_name = current.name
    rename = label and current is not threading.main_thread()
    if rename:
        current.name = label.strip("[]") or previous_name
    try:
        yield
    finally:
        _thread_local.prefix = previous
        if rename:
            current.name = previous_name


class Output:
    """
    Unified output handler that logs and prints messages consistently.

    Usage:
        from utils.output import Output
        out = Output(__name__)

        # For parallel work, pass a prefix that identifies the worker:
        out = Output(__name__, prefix="[edge1x01]")

        out.header("Section Title")
        out.info("Doing something...")
        out.success("Task completed")
        out.warning("Something might be wrong")
        out.error("Task failed")
    """

    def __init__(self, name: str, prefix: str = ""):
        """Initialize with a logger name (typically __name__) and optional prefix.

        If ``prefix`` is empty, the effective prefix is read from the current
        thread's label (set via :func:`thread_label`) at call time. This lets
        a worker thread label all of its output — including output produced by
        shared helpers — without each helper needing to pass an explicit prefix.
        """
        self.logger = get_logger(name)
        self.prefix = prefix

    @property
    def _effective_prefix(self) -> str:
        return self.prefix or _thread_prefix()

    @property
    def _console_prefix(self) -> str:
        p = self._effective_prefix
        return f"{p} " if p else ""

    @property
    def _log_prefix(self) -> str:
        p = self._effective_prefix
        return f"{p} " if p else ""

    def _print(self, line: str) -> None:
        """Write one console line under the shared lock."""
        with _PRINT_LOCK:
            print(f"{self._console_prefix}{line}")

    def header(self, title: str, subtitle: str | None = None) -> None:
        """Print a section header.

        In labelled mode (prefix set) the separator lines are dropped so
        parallel workers don't flood the console with banners.
        """
        if self._effective_prefix:
            with _PRINT_LOCK:
                print(f"{self._console_prefix}=== {title} ===")
                if subtitle:
                    print(f"{self._console_prefix}{subtitle}")
        else:
            with _PRINT_LOCK:
                print("\n" + "=" * HEADER_WIDTH)
                print(title)
                if subtitle:
                    print(subtitle)
                print("=" * HEADER_WIDTH)
        self.logger.info(f"{self._log_prefix}=== {title} ===")

    def subheader(self, title: str) -> None:
        """Print a subsection header with dashes."""
        if self._effective_prefix:
            with _PRINT_LOCK:
                print(f"{self._console_prefix}--- {title} ---")
        else:
            with _PRINT_LOCK:
                print("\n" + "-" * HEADER_WIDTH)
                print(title)
                print("-" * HEADER_WIDTH)
        self.logger.info(f"{self._log_prefix}--- {title} ---")

    def success(self, message: str) -> None:
        """Print a success message with checkmark and log as INFO."""
        self._print(f"{SYMBOLS['success']} {message}")
        self.logger.info(f"{self._log_prefix}{message}")

    def error(self, message: str) -> None:
        """Print an error message with X mark and log as ERROR."""
        self._print(f"{SYMBOLS['error']} {message}")
        self.logger.error(f"{self._log_prefix}{message}")

    def warning(self, message: str) -> None:
        """Print a warning message and log as WARNING."""
        self._print(f"{SYMBOLS['warning']} {message}")
        self.logger.warning(f"{self._log_prefix}{message}")

    def info(self, message: str) -> None:
        """Print an info message and log as INFO."""
        self._print(f"{SYMBOLS['info']} {message}")
        self.logger.info(f"{self._log_prefix}{message}")

    def step(self, message: str) -> None:
        """Print a step message (no symbol) and log as INFO."""
        self._print(message)
        self.logger.info(f"{self._log_prefix}{message}")

    def wait(self, message: str) -> None:
        """Print a waiting/progress message and log as INFO."""
        self._print(f"{SYMBOLS['wait']} {message}")
        self.logger.info(f"{self._log_prefix}{message}")

    def spinner_wait(
        self,
        message: str,
        seconds: int,
        interval: float = 0.5,
        log: bool = False,
    ) -> None:
        """Display a simple spinner/countdown without spamming logs.

        Behavior:
        - Labelled mode (prefix set): silent on console, sleep + log only.
          Avoids interleaving carriage-return spinners across parallel workers.
        - Non-TTY: print one line at start, sleep, print one done line.
        - TTY single-thread: pretty carriage-return countdown.
        """
        seconds = max(0, seconds)

        # Parallel workers: stay silent on console so logs don't collide.
        if self._effective_prefix:
            self.logger.info(f"{self._log_prefix}{message} ({seconds}s)")
            time.sleep(seconds)
            return

        if log:
            self.logger.info(message)

        if not sys.stdout.isatty():
            with _PRINT_LOCK:
                print(f"{SYMBOLS['wait']} {message} ({seconds}s)")
            time.sleep(seconds)
            with _PRINT_LOCK:
                print(f"{SYMBOLS['wait']} {message} (done)")
            return

        spinner = "|/-\\"
        end = time.time() + seconds
        i = 0
        with _PRINT_LOCK:
            while True:
                remaining = int(max(0, end - time.time()))
                line = (
                    f"\r{SYMBOLS['wait']} {message} "
                    f"({remaining:>2}s) {spinner[i % len(spinner)]}"
                )
                sys.stdout.write(line)
                sys.stdout.flush()
                if remaining <= 0:
                    break
                time.sleep(interval)
                i += 1
            sys.stdout.write("\r" + f"{SYMBOLS['wait']} {message} (done)\n")
            sys.stdout.flush()

    def detail(self, message: str) -> None:
        """Print an indented detail message and log as DEBUG."""
        self._print(f"  {message}")
        self.logger.debug(f"{self._log_prefix}{message}")

    def banner(self, title: str) -> None:
        """Print a prominent banner (used for script start/end)."""
        if self._effective_prefix:
            with _PRINT_LOCK:
                print(
                    f"{self._console_prefix}{SYMBOLS['rocket']} {title} {SYMBOLS['rocket']}"
                )
        else:
            with _PRINT_LOCK:
                print("=" * HEADER_WIDTH)
                print(f"{SYMBOLS['rocket']} {title} {SYMBOLS['rocket']}")
                print("=" * HEADER_WIDTH)
        self.logger.info(f"{self._log_prefix}=== {title} ===")

    def blank(self) -> None:
        """Print a blank line (for spacing, not logged)."""
        with _PRINT_LOCK:
            print()

    def log_only(self, message: str, level: str = "info") -> None:
        """Log a message without printing to console."""
        prefixed = f"{self._log_prefix}{message}"
        if level == "debug":
            self.logger.debug(prefixed)
        elif level == "warning":
            self.logger.warning(prefixed)
        elif level == "error":
            self.logger.error(prefixed)
        else:
            self.logger.info(prefixed)
