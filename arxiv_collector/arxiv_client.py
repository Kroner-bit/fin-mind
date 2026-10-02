"""
ArXiv API client module.
Handles search requests, rate limiting (3.5s delay), retries, and Atom feed parsing.
"""
from datetime import datetime
from typing import Any, Optional
import logging
import time
import urllib.parse
import feedparser
import requests

from .config import (
    ARXIV_API_URL,
    DEFAULT_SORT_BY,
    DEFAULT_SORT_ORDER,
    REQUEST_DELAY,
    MAX_RETRIES,
    RETRY_BACKOFF,
    API_TIMEOUT,
    USER_AGENT,
)
from .utils import clean_text, extract_arxiv_id


logger = logging.getLogger("arxiv_collector")


class ArXivClient:
    """Client for interacting with the official ArXiv API."""

    def __init__(
        self,
        api_url: str = ARXIV_API_URL,
        request_delay: float = REQUEST_DELAY,
        max_retries: int = MAX_RETRIES,
        timeout: int = API_TIMEOUT,
    ):
        self.api_url = api_url
        self.request_delay = request_delay
        self.max_retries = max_retries
        self.timeout = timeout
        self.last_request_time: float = 0.0

        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": USER_AGENT,
            "Accept": "application/atom+xml,application/xml,text/xml",
        })

    def _wait_for_rate_limit(self) -> None:
        """Enforce rate limiting between consecutive arXiv API queries."""
        elapsed = time.time() - self.last_request_time
        if elapsed < self.request_delay:
            wait_time = self.request_delay - elapsed
            logger.debug(f"ArXiv API rate limit: sleeping {wait_time:.2f}s")
            time.sleep(wait_time)
        self.last_request_time = time.time()

    def search(
        self,
        keyword: str,
        max_results: int = 25,
        sort_by: str = DEFAULT_SORT_BY,
        sort_order: str = DEFAULT_SORT_ORDER,
    ) -> list[dict[str, Any]]:
        """
        Search arXiv for a specific keyword or phrase.
        
        Args:
            keyword: The search topic or phrase (e.g. 'momentum trading')
            max_results: Maximum number of results to fetch
            sort_by: Sorting field ('relevance', 'lastUpdatedDate', 'submittedDate')
            sort_order: Sort direction ('descending', 'ascending')
            
        Returns:
            List of parsed paper dictionaries.
        """
        # Wrap multi-word phrases in quotes for precision in arXiv query syntax
        clean_kw = keyword.strip()
        if " " in clean_kw and not (clean_kw.startswith('"') and clean_kw.endswith('"')):
            search_query = f'all:"{clean_kw}"'
        else:
            search_query = f"all:{clean_kw}"

        params = {
            "search_query": search_query,
            "start": 0,
            "max_results": max_results,
            "sortBy": sort_by,
            "sortOrder": sort_order,
        }

        # Build URL for logging & debugging
        query_string = urllib.parse.urlencode(params)
        full_url = f"{self.api_url}?{query_string}"
        logger.info(f"ArXiv API search: keyword='{keyword}', max_results={max_results}, url={full_url}")

        attempt = 0
        backoff = 2.0

        while attempt < self.max_retries:
            attempt += 1
            try:
                self._wait_for_rate_limit()

                response = self.session.get(
                    self.api_url,
                    params=params,
                    timeout=self.timeout
                )

                if response.status_code == 200:
                    feed = feedparser.parse(response.content)

                    # Check for parser errors or empty feed
                    if feed.bozo and not getattr(feed, "entries", None):
                        logger.warning(f"Feed parser bozo warning for keyword '{keyword}': {feed.bozo_exception}")

                    entries = feed.entries
                    logger.info(f"ArXiv API returned {len(entries)} entries for '{keyword}'")

                    papers: list[dict[str, Any]] = []
                    for entry in entries:
                        parsed_paper = self._parse_entry(entry)
                        if parsed_paper:
                            papers.append(parsed_paper)

                    return papers

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

                    msg = f"⚠ ArXiv API Rate Limit (429) hit for '{keyword}'! Waiting {wait_seconds:.1f}s (attempt {attempt}/{self.max_retries})..."
                    print(f"\n{msg}", flush=True)
                    logger.warning(msg)
                    time.sleep(wait_seconds)
                    backoff = max(backoff * RETRY_BACKOFF, wait_seconds * 1.5)

                elif response.status_code in (500, 502, 503, 504):
                    logger.warning(
                        f"ArXiv API HTTP {response.status_code} on attempt {attempt}/{self.max_retries} for '{keyword}'. Backing off {backoff:.1f}s"
                    )
                    time.sleep(backoff)
                    backoff *= RETRY_BACKOFF
                else:
                    logger.error(f"ArXiv API unexpected HTTP {response.status_code}: {response.text[:200]}")
                    break

            except (requests.RequestException, Exception) as exc:
                logger.warning(
                    f"ArXiv API request exception on attempt {attempt}/{self.max_retries} for '{keyword}': {exc}"
                )
                if attempt >= self.max_retries:
                    logger.error(f"ArXiv API max retries reached for keyword '{keyword}'.")
                    raise
                time.sleep(backoff)
                backoff *= RETRY_BACKOFF

        return []

    def _parse_entry(self, entry: Any) -> Optional[dict[str, Any]]:
        """Extract and clean all required metadata fields from a feedparser entry."""
        try:
            raw_id = getattr(entry, "id", "")
            arxiv_id = extract_arxiv_id(raw_id)
            if not arxiv_id:
                return None

            title = clean_text(getattr(entry, "title", ""))
            abstract = clean_text(getattr(entry, "summary", ""))

            # Extract authors
            authors: list[str] = []
            if hasattr(entry, "authors"):
                authors = [clean_text(a.get("name", "")) for a in entry.authors if a.get("name")]
            elif hasattr(entry, "author"):
                authors = [clean_text(entry.author)]

            # Extract dates
            published = getattr(entry, "published", "")
            updated = getattr(entry, "updated", "") or published

            # Extract categories/tags
            categories: list[str] = []
            if hasattr(entry, "tags"):
                categories = [t.get("term", "") for t in entry.tags if t.get("term")]

            # Resolve PDF and Abstract URLs
            pdf_url = ""
            abs_url = f"https://arxiv.org/abs/{arxiv_id}"

            if hasattr(entry, "links"):
                for link in entry.links:
                    rel = link.get("rel")
                    link_type = link.get("type", "")
                    href = link.get("href", "")

                    if link_type == "application/pdf" or "pdf" in href:
                        pdf_url = href
                    elif rel == "alternate":
                        abs_url = href

            # Fallback if pdf_url was not explicitly in links
            if not pdf_url:
                pdf_url = f"https://arxiv.org/pdf/{arxiv_id}.pdf"
            elif not pdf_url.endswith(".pdf"):
                # Ensure .pdf extension in URL for cleaner routing
                if "/pdf/" in pdf_url and not pdf_url.endswith(".pdf"):
                    pdf_url = f"{pdf_url}.pdf"

            return {
                "arxiv_id": arxiv_id,
                "title": title,
                "authors": authors,
                "abstract": abstract,
                "published": published,
                "updated": updated,
                "categories": categories,
                "pdf_url": pdf_url,
                "abs_url": abs_url,
            }

        except Exception as exc:
            logger.error(f"Error parsing arXiv feed entry: {exc}")
            return None
