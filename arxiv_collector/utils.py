"""
Utility functions for text processing, logging, file sanitization, and verification.
"""
from datetime import datetime
from pathlib import Path
import logging
import re
import sys

from .config import LOG_DIRECTORY


def setup_logger(mode_name: str = "run") -> logging.Logger:
    """
    Set up a persistent file logger and clean console logger.
    Logs are written to: arxiv_collector/logs/YYYY-MM-DD_run.log
    """
    date_str = datetime.now().strftime("%Y-%m-%d")
    log_file = LOG_DIRECTORY / f"{date_str}_run.log"

    logger = logging.getLogger("arxiv_collector")
    logger.setLevel(logging.INFO)

    # Avoid duplicate handlers if setup_logger is called multiple times
    if logger.handlers:
        return logger

    # File handler: detailed format with timestamp, level, module
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] [%(filename)s:%(lineno)d] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    file_handler.setFormatter(file_formatter)
    logger.addHandler(file_handler)

    return logger


def clean_text(text: str | None) -> str:
    """Normalize whitespace and strip unnecessary line breaks."""
    if not text:
        return ""
    # Replace multiple whitespaces and newlines with a single space
    cleaned = re.sub(r"\s+", " ", text)
    return cleaned.strip()


def extract_arxiv_id(raw_id_or_url: str) -> str:
    """
    Extract canonical base arXiv ID (without URL prefix or version suffix).
    Examples:
      - 'http://arxiv.org/abs/2006.08307v1' -> '2006.08307'
      - '2006.08307v2' -> '2006.08307'
      - 'math/0309136v1' -> 'math/0309136'
      - 'arXiv:2104.08891' -> '2104.08891'
    """
    if not raw_id_or_url:
        return ""

    s = raw_id_or_url.strip()
    # Strip arXiv URL prefixes
    s = re.sub(r"^https?://arxiv\.org/(abs|pdf)/", "", s)
    # Strip trailing .pdf
    s = re.sub(r"\.pdf$", "", s, flags=re.IGNORECASE)
    # Strip 'arXiv:' prefix
    s = re.sub(r"^arxiv:\s*", "", s, flags=re.IGNORECASE)
    # Strip version suffix (e.g., v1, v2, v10) at the end of the ID
    s = re.sub(r"v\d+$", "", s)

    return s.strip()


def sanitize_filename(arxiv_id: str) -> str:
    """
    Sanitize arXiv ID for use as a file name.
    Replaces slashes (found in older legacy arXiv IDs like 'math/0309136') with underscores.
    """
    # Replace illegal filename characters
    safe = re.sub(r'[\\/*?:"<>|]', "_", arxiv_id)
    return f"{safe}.pdf"


def is_valid_pdf(file_path: Path) -> bool:
    """
    Check if a file exists, is non-empty, and starts with the standard PDF magic bytes '%PDF-'.
    Protects against partial downloads and HTML error pages saved as .pdf.
    """
    if not file_path.exists():
        return False
    if file_path.stat().st_size < 100:  # Valid PDFs are almost always > 100 bytes
        return False
    try:
        with open(file_path, "rb") as f:
            header = f.read(5)
            return header == b"%PDF-"
    except Exception:
        return False
