"""
Unified output helper for consistent logging and console output.

This module provides a single interface for both logging and user-facing output,
ensuring consistent formatting across all automation scripts.
"""

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


class Output:
    """
    Unified output handler that logs and prints messages consistently.

    Usage:
        from utils.output import Output
        out = Output(__name__)

        out.header("Section Title")
        out.info("Doing something...")
        out.success("Task completed")
        out.warning("Something might be wrong")
        out.error("Task failed")
    """

    def __init__(self, name: str):
        """Initialize with a logger name (typically __name__)."""
        self.logger = get_logger(name)

    def header(self, title: str, subtitle: str | None = None) -> None:
        """
        Print a section header.

        Args:
            title: Main header title
            subtitle: Optional subtitle shown below the title
        """
        print("\n" + "=" * HEADER_WIDTH)
        print(title)
        if subtitle:
            print(subtitle)
        print("=" * HEADER_WIDTH)
        self.logger.info(f"=== {title} ===")

    def subheader(self, title: str) -> None:
        """Print a subsection header with dashes."""
        print("\n" + "-" * HEADER_WIDTH)
        print(title)
        print("-" * HEADER_WIDTH)
        self.logger.info(f"--- {title} ---")

    def success(self, message: str) -> None:
        """Print a success message with checkmark and log as INFO."""
        print(f"{SYMBOLS['success']} {message}")
        self.logger.info(message)

    def error(self, message: str) -> None:
        """Print an error message with X mark and log as ERROR."""
        print(f"{SYMBOLS['error']} {message}")
        self.logger.error(message)

    def warning(self, message: str) -> None:
        """Print a warning message and log as WARNING."""
        print(f"{SYMBOLS['warning']} {message}")
        self.logger.warning(message)

    def info(self, message: str) -> None:
        """Print an info message and log as INFO."""
        print(f"{SYMBOLS['info']} {message}")
        self.logger.info(message)

    def step(self, message: str) -> None:
        """Print a step message (no symbol) and log as INFO."""
        print(message)
        self.logger.info(message)

    def wait(self, message: str) -> None:
        """Print a waiting/progress message and log as INFO."""
        print(f"{SYMBOLS['wait']} {message}")
        self.logger.info(message)

    def detail(self, message: str) -> None:
        """Print an indented detail message and log as DEBUG."""
        print(f"  {message}")
        self.logger.debug(message)

    def banner(self, title: str) -> None:
        """Print a prominent banner (used for script start/end)."""
        print("=" * HEADER_WIDTH)
        print(f"{SYMBOLS['rocket']} {title} {SYMBOLS['rocket']}")
        print("=" * HEADER_WIDTH)
        self.logger.info(f"=== {title} ===")

    def blank(self) -> None:
        """Print a blank line (for spacing, not logged)."""
        print()

    def log_only(self, message: str, level: str = "info") -> None:
        """Log a message without printing to console."""
        if level == "debug":
            self.logger.debug(message)
        elif level == "warning":
            self.logger.warning(message)
        elif level == "error":
            self.logger.error(message)
        else:
            self.logger.info(message)
