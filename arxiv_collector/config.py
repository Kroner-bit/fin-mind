"""
Configuration module for ArXiv Research Collector.
Centralizes paths, API parameters, timeouts, and rate limiting limits.
"""
from pathlib import Path
import json
import os

# Base directory for the arxiv_collector package and workspace root
BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent

# Subdirectories
CONFIG_DIR = BASE_DIR / "config"
DATA_DIR = BASE_DIR / "data"
# Collector output folder is the processor's input folder: PROJECT_ROOT / pdf_processor / pdf
PDF_DIRECTORY = Path(os.getenv("ARXIV_PDF_DIR", str(PROJECT_ROOT / "pdf_processor" / "pdf")))
LOG_DIRECTORY = BASE_DIR / "logs"

# File paths
KEYWORDS_FILE = CONFIG_DIR / "keywords.json"
DATABASE_PATH = DATA_DIR / "papers.db"

# Ensure runtime directories exist
DATA_DIR.mkdir(parents=True, exist_ok=True)
PDF_DIRECTORY.mkdir(parents=True, exist_ok=True)
LOG_DIRECTORY.mkdir(parents=True, exist_ok=True)

# Search configuration
RESULTS_PER_KEYWORD = int(os.getenv("ARXIV_RESULTS_PER_KEYWORD", 100))
TEST_RESULTS = int(os.getenv("ARXIV_TEST_RESULTS", 5))

# ArXiv API Throttling & Throttling settings
REQUEST_DELAY = float(os.getenv("ARXIV_REQUEST_DELAY", 3.5))       # Seconds between ArXiv API searches
PDF_DOWNLOAD_DELAY = float(os.getenv("ARXIV_PDF_DELAY", 1.0))     # Seconds between PDF downloads

# Reliability & Retries
MAX_RETRIES = int(os.getenv("ARXIV_MAX_RETRIES", 5))
RETRY_BACKOFF = float(os.getenv("ARXIV_RETRY_BACKOFF", 2.0))
API_TIMEOUT = int(os.getenv("ARXIV_API_TIMEOUT", 30))
DOWNLOAD_TIMEOUT = int(os.getenv("ARXIV_DOWNLOAD_TIMEOUT", 45))

# ArXiv API Parameters
ARXIV_API_URL = "http://export.arxiv.org/api/query"
DEFAULT_SORT_BY = "relevance"             # relevance, lastUpdatedDate, submittedDate
DEFAULT_SORT_ORDER = "descending"         # ascending, descending

# User Agent header (respectful identification for arXiv and publisher CDNs)
USER_AGENT = "ArXivResearchCollector/1.0 (Quantitative Finance Academic Research; mailto:researcher@local)"


def load_keywords(filepath: Path = KEYWORDS_FILE) -> list[str]:
    """Load search keywords from the keywords JSON file."""
    if not filepath.exists():
        raise FileNotFoundError(f"Keywords file not found at: {filepath}")
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)
    keywords = data.get("keywords", [])
    if not keywords:
        raise ValueError(f"No keywords found in {filepath}")
    return keywords
