"""
Robust PDF Downloader for arXiv papers.
Implements:
- Deduplication against filesystem and SQLite
- Streaming download with atomic file renaming (protects against partial files)
- HTTP status & timeout checks
- Exponential backoff retries
- PDF magic byte verification (%PDF-)
- Download rate limiting
"""
from pathlib import Path
from typing import Optional
import logging
import os
import time
import requests

from .config import (
    PDF_DIRECTORY,
    PDF_DOWNLOAD_DELAY,
    MAX_RETRIES,
    RETRY_BACKOFF,
    DOWNLOAD_TIMEOUT,
    USER_AGENT,
)
from .utils import is_valid_pdf, sanitize_filename


logger = logging.getLogger("arxiv_collector")


class DownloadResult:
    """Represents the outcome of a PDF download attempt."""

    def __init__(
        self,
        success: bool,
        status: str,
        message: str,
        file_path: Optional[Path] = None,
    ):
        self.success = success
        self.status = status      # 'downloaded', 'skipped', 'failed', 'redownloaded'
        self.message = message
        self.file_path = file_path


class PDFDownloader:
    """Manages secure and robust PDF retrieval from arXiv."""

    def __init__(
        self,
        pdf_dir: Path = PDF_DIRECTORY,
        download_delay: float = PDF_DOWNLOAD_DELAY,
        max_retries: int = MAX_RETRIES,
        timeout: int = DOWNLOAD_TIMEOUT,
    ):
        self.pdf_dir = pdf_dir
        self.download_delay = download_delay
        self.max_retries = max_retries
        self.timeout = timeout
        self.last_download_time: float = 0.0

        self.pdf_dir.mkdir(parents=True, exist_ok=True)

        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": USER_AGENT,
            "Accept": "application/pdf,application/octet-stream,*/*",
        })

    def _wait_for_rate_limit(self) -> None:
        """Throttles PDF downloads to be courteous to the host servers."""
        elapsed = time.time() - self.last_download_time
        if elapsed < self.download_delay:
            wait_time = self.download_delay - elapsed
            time.sleep(wait_time)
        self.last_download_time = time.time()

    def get_target_path(self, arxiv_id: str) -> Path:
        """Return the target file path for an arXiv ID."""
        filename = sanitize_filename(arxiv_id)
        return self.pdf_dir / filename

    def download_paper(
        self,
        paper: dict,
        force_redownload: bool = False
    ) -> DownloadResult:
        """
        Download the PDF for a paper if not already present and verified.
        
        Args:
            paper: Dictionary containing 'arxiv_id' and 'pdf_url'
            force_redownload: If True, redownload even if file exists
            
        Returns:
            DownloadResult with status ('downloaded', 'skipped', 'failed', 'redownloaded')
        """
        arxiv_id = paper["arxiv_id"]
        pdf_url = paper.get("pdf_url") or f"https://arxiv.org/pdf/{arxiv_id}.pdf"
        target_path = self.get_target_path(arxiv_id)

        # 1. Check if valid PDF already exists on disk
        if not force_redownload and is_valid_pdf(target_path):
            logger.debug(f"PDF already exists for {arxiv_id} at {target_path}. Skipping.")
            return DownloadResult(
                success=True,
                status="skipped",
                message="Already downloaded and verified on disk",
                file_path=target_path
            )

        # Prepare temporary file for atomic write
        temp_path = target_path.with_suffix(".pdf.tmp")

        attempt = 0
        backoff = 2.0

        while attempt < self.max_retries:
            attempt += 1
            try:
                self._wait_for_rate_limit()
                logger.info(f"Downloading PDF [{attempt}/{self.max_retries}] for {arxiv_id} from {pdf_url}...")

                response = self.session.get(
                    pdf_url,
                    stream=True,
                    timeout=self.timeout,
                    allow_redirects=True
                )

                if response.status_code == 200:
                    # Stream download into temporary file
                    with open(temp_path, "wb") as f:
                        for chunk in response.iter_content(chunk_size=16384):
                            if chunk:
                                f.write(chunk)

                    # Verify that the downloaded file is a genuine PDF
                    if not is_valid_pdf(temp_path):
                        # Inspect first bytes for logging
                        header = b""
                        if temp_path.exists():
                            with open(temp_path, "rb") as f:
                                header = f.read(50)
                            temp_path.unlink(missing_ok=True)

                        err_msg = f"Downloaded content failed PDF magic-byte check. Header: {header[:30]!r}"
                        logger.warning(f"Download invalid for {arxiv_id}: {err_msg}")

                        if attempt < self.max_retries:
                            time.sleep(backoff)
                            backoff *= RETRY_BACKOFF
                            continue
                        else:
                            return DownloadResult(
                                success=False,
                                status="failed",
                                message=err_msg,
                                file_path=None
                            )

                    # Atomic move from temp to final destination
                    os.replace(temp_path, target_path)
                    logger.info(f"Successfully downloaded and verified {arxiv_id} -> {target_path.name}")

                    is_redownload = force_redownload or paper.get("download_status") == "failed"
                    return DownloadResult(
                        success=True,
                        status="redownloaded" if is_redownload else "downloaded",
                        message="Download successful",
                        file_path=target_path
                    )

                elif response.status_code == 429:
                    retry_after_hdr = response.headers.get("Retry-After")
                    wait_seconds = backoff
                    if retry_after_hdr:
                        try:
                            wait_seconds = max(float(retry_after_hdr), 5.0)
                        except ValueError:
                            wait_seconds = max(backoff, 10.0)
                    else:
                        wait_seconds = max(backoff, 5.0)

                    msg = f"⚠ PDF server rate limit (429) for {arxiv_id}! Waiting {wait_seconds:.1f}s (attempt {attempt}/{self.max_retries})..."
                    logger.warning(msg)
                    time.sleep(wait_seconds)
                    backoff = max(backoff * RETRY_BACKOFF, wait_seconds * 1.5)

                elif response.status_code in (500, 502, 503, 504):
                    logger.warning(
                        f"PDF download HTTP {response.status_code} for {arxiv_id} on attempt {attempt}/{self.max_retries}"
                    )
                    time.sleep(backoff)
                    backoff *= RETRY_BACKOFF

                else:
                    err_msg = f"HTTP {response.status_code} error from server"
                    logger.error(f"Cannot download PDF for {arxiv_id}: {err_msg}")
                    temp_path.unlink(missing_ok=True)
                    return DownloadResult(
                        success=False,
                        status="failed",
                        message=err_msg,
                        file_path=None
                    )

            except (requests.RequestException, OSError) as exc:
                temp_path.unlink(missing_ok=True)
                logger.warning(f"Exception downloading PDF for {arxiv_id} (attempt {attempt}/{self.max_retries}): {exc}")
                if attempt >= self.max_retries:
                    return DownloadResult(
                        success=False,
                        status="failed",
                        message=str(exc),
                        file_path=None
                    )
                time.sleep(backoff)
                backoff *= RETRY_BACKOFF

        temp_path.unlink(missing_ok=True)
        return DownloadResult(
            success=False,
            status="failed",
            message="Exceeded maximum retries",
            file_path=None
        )
