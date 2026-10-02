"""
Database module for persistent paper metadata, deduplication, and rank tracking.
Uses SQLite for storage at arxiv_collector/data/papers.db.
"""
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
import json
import sqlite3

from .config import DATABASE_PATH


class Database:
    """Manages the SQLite database for papers, downloads, and search rankings."""

    def __init__(self, db_path: Path = DATABASE_PATH):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.init_db()

    def _get_connection(self) -> sqlite3.Connection:
        """Create a sqlite3 connection with row dictionary access."""
        conn = sqlite3.connect(str(self.db_path), timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL;")  # Fast concurrent reading/writing
        return conn

    def init_db(self) -> None:
        """Create tables and indexes if they do not exist."""
        with self._get_connection() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS papers (
                    arxiv_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    authors TEXT,
                    abstract TEXT,
                    published TEXT,
                    updated TEXT,
                    categories TEXT,
                    pdf_url TEXT,
                    abs_url TEXT,
                    first_seen TEXT NOT NULL,
                    last_seen TEXT NOT NULL,
                    downloaded INTEGER DEFAULT 0,
                    pdf_path TEXT,
                    download_status TEXT DEFAULT 'pending',
                    first_keyword TEXT,
                    keywords TEXT NOT NULL,
                    last_rank INTEGER
                );

                CREATE TABLE IF NOT EXISTS paper_ranks (
                    arxiv_id TEXT NOT NULL,
                    keyword TEXT NOT NULL,
                    rank INTEGER NOT NULL,
                    last_updated TEXT NOT NULL,
                    PRIMARY KEY (arxiv_id, keyword),
                    FOREIGN KEY (arxiv_id) REFERENCES papers (arxiv_id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_papers_download_status 
                    ON papers (download_status);
                CREATE INDEX IF NOT EXISTS idx_papers_downloaded 
                    ON papers (downloaded);
                CREATE INDEX IF NOT EXISTS idx_paper_ranks_keyword 
                    ON paper_ranks (keyword);
            """)

    def get_paper(self, arxiv_id: str) -> Optional[dict[str, Any]]:
        """Retrieve a paper record by its canonical arXiv ID."""
        with self._get_connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM papers WHERE arxiv_id = ?",
                (arxiv_id,)
            )
            row = cursor.fetchone()
            if row:
                return dict(row)
            return None

    def upsert_paper_discovery(
        self,
        paper_data: dict[str, Any],
        keyword: str,
        rank: int
    ) -> tuple[bool, dict[str, Any]]:
        """
        Record discovery of a paper under a specific keyword search.
        
        If the paper is already in the database:
          - Does NOT create duplicate
          - Appends the keyword to the 'keywords' JSON list if not already present
          - Updates last_seen timestamp
          - Updates last_rank
          - Refreshes metadata (title, updated, categories, etc.) if changed
          - Updates paper_ranks table
          - Returns (is_new=False, updated_paper_dict)

        If the paper is newly discovered:
          - Inserts new row with downloaded=0, download_status='pending'
          - Initializes keywords=[keyword], first_keyword=keyword
          - Inserts into paper_ranks table
          - Returns (is_new=True, new_paper_dict)
        """
        now_iso = datetime.now().isoformat()
        arxiv_id = paper_data["arxiv_id"]

        with self._get_connection() as conn:
            # Check existing record
            cursor = conn.execute("SELECT * FROM papers WHERE arxiv_id = ?", (arxiv_id,))
            existing = cursor.fetchone()

            if existing:
                existing_dict = dict(existing)
                # Parse existing keywords list
                try:
                    kw_list = json.loads(existing_dict.get("keywords") or "[]")
                except Exception:
                    kw_list = []

                if keyword not in kw_list:
                    kw_list.append(keyword)

                # Update paper record
                conn.execute("""
                    UPDATE papers SET
                        title = ?,
                        authors = ?,
                        abstract = ?,
                        updated = ?,
                        categories = ?,
                        pdf_url = ?,
                        abs_url = ?,
                        last_seen = ?,
                        keywords = ?,
                        last_rank = ?
                    WHERE arxiv_id = ?
                """, (
                    paper_data.get("title", existing_dict.get("title")),
                    json.dumps(paper_data.get("authors", []), ensure_ascii=False),
                    paper_data.get("abstract", existing_dict.get("abstract")),
                    paper_data.get("updated", existing_dict.get("updated")),
                    json.dumps(paper_data.get("categories", []), ensure_ascii=False),
                    paper_data.get("pdf_url", existing_dict.get("pdf_url")),
                    paper_data.get("abs_url", existing_dict.get("abs_url")),
                    now_iso,
                    json.dumps(kw_list, ensure_ascii=False),
                    rank,
                    arxiv_id
                ))

                # Update rank tracking
                conn.execute("""
                    INSERT INTO paper_ranks (arxiv_id, keyword, rank, last_updated)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(arxiv_id, keyword) DO UPDATE SET
                        rank = excluded.rank,
                        last_updated = excluded.last_updated
                """, (arxiv_id, keyword, rank, now_iso))

                existing_dict["keywords"] = kw_list
                existing_dict["last_rank"] = rank
                existing_dict["last_seen"] = now_iso
                return False, existing_dict

            else:
                # Brand new paper
                kw_list = [keyword]
                conn.execute("""
                    INSERT INTO papers (
                        arxiv_id, title, authors, abstract, published, updated,
                        categories, pdf_url, abs_url, first_seen, last_seen,
                        downloaded, pdf_path, download_status, first_keyword,
                        keywords, last_rank
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    arxiv_id,
                    paper_data.get("title", ""),
                    json.dumps(paper_data.get("authors", []), ensure_ascii=False),
                    paper_data.get("abstract", ""),
                    paper_data.get("published", ""),
                    paper_data.get("updated", ""),
                    json.dumps(paper_data.get("categories", []), ensure_ascii=False),
                    paper_data.get("pdf_url", ""),
                    paper_data.get("abs_url", ""),
                    now_iso,
                    now_iso,
                    0,          # downloaded
                    None,       # pdf_path
                    "pending",  # download_status
                    keyword,
                    json.dumps(kw_list, ensure_ascii=False),
                    rank
                ))

                # Insert rank
                conn.execute("""
                    INSERT INTO paper_ranks (arxiv_id, keyword, rank, last_updated)
                    VALUES (?, ?, ?, ?)
                """, (arxiv_id, keyword, rank, now_iso))

                new_record = {
                    "arxiv_id": arxiv_id,
                    "title": paper_data.get("title", ""),
                    "downloaded": 0,
                    "download_status": "pending",
                    "pdf_path": None,
                    "first_keyword": keyword,
                    "keywords": kw_list,
                    "last_rank": rank
                }
                return True, new_record

    def update_download_status(
        self,
        arxiv_id: str,
        status: str,
        pdf_path: Optional[str] = None
    ) -> None:
        """
        Update the download status of a paper.
        Status can be 'downloaded', 'failed', 'skipped', or 'pending'.
        """
        downloaded_flag = 1 if status == "downloaded" else 0
        with self._get_connection() as conn:
            if pdf_path:
                conn.execute("""
                    UPDATE papers SET
                        download_status = ?,
                        downloaded = ?,
                        pdf_path = ?
                    WHERE arxiv_id = ?
                """, (status, downloaded_flag, str(pdf_path), arxiv_id))
            else:
                conn.execute("""
                    UPDATE papers SET
                        download_status = ?,
                        downloaded = ?
                    WHERE arxiv_id = ?
                """, (status, downloaded_flag, arxiv_id))

    def get_statistics(self) -> dict[str, int]:
        """Return high-level summary counts from the database."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM papers")
            total = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM papers WHERE downloaded = 1")
            downloaded = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM papers WHERE download_status = 'failed'")
            failed = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM papers WHERE download_status = 'pending'")
            pending = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(DISTINCT keyword) FROM paper_ranks")
            keywords_tracked = cursor.fetchone()[0]

            return {
                "total_papers": total,
                "downloaded": downloaded,
                "failed": failed,
                "pending": pending,
                "keywords_tracked": keywords_tracked,
            }
