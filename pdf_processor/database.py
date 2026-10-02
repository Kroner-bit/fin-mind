"""
SQLite database manager for tracking PDF processing status,
API usage (rate limits), and JSON output paths.
Supports multi-API-key quota tracking with per-key RPD/RPM/TPM usage.
"""

import sqlite3
import os
import json
import time
import threading
from datetime import datetime, timedelta, timezone
try:
    from zoneinfo import ZoneInfo
except ImportError:
    ZoneInfo = None
from pathlib import Path


class Database:
    """Manages all SQLite operations for the PDF analyzer with multi-thread safety."""

    @staticmethod
    def get_quota_day_window() -> tuple[datetime, datetime]:
        """
        Get the current daily quota window based on Google Gemini API's official reset cycle.
        Gemini API free tier RPD resets every day at Midnight Pacific Time (00:00 US/Pacific).
        Returns:
            (start_utc, next_reset_utc):
            - start_utc: start of the current quota day (Midnight PT converted to UTC).
            - next_reset_utc: the upcoming midnight reset in PT (converted to UTC).
        """
        if ZoneInfo is not None:
            try:
                pt_tz = ZoneInfo("America/Los_Angeles")
                now_pt = datetime.now(pt_tz)
                today_midnight_pt = now_pt.replace(hour=0, minute=0, second=0, microsecond=0)
                next_midnight_pt = today_midnight_pt + timedelta(days=1)
                start_utc = today_midnight_pt.astimezone(timezone.utc)
                next_reset_utc = next_midnight_pt.astimezone(timezone.utc)
                return start_utc, next_reset_utc
            except Exception:
                pass
        now_utc = datetime.now(timezone.utc)
        offset_hours = -7 if (3 <= now_utc.month <= 11) else -8
        pt_offset = timezone(timedelta(hours=offset_hours))
        now_pt = now_utc.astimezone(pt_offset)
        today_midnight_pt = now_pt.replace(hour=0, minute=0, second=0, microsecond=0)
        next_midnight_pt = today_midnight_pt + timedelta(days=1)
        start_utc = today_midnight_pt.astimezone(timezone.utc)
        next_reset_utc = next_midnight_pt.astimezone(timezone.utc)
        return start_utc, next_reset_utc

    def __init__(self, db_path: str):
        self.db_path = db_path
        self.lock = threading.RLock()
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode = WAL;")
        self.conn.execute("PRAGMA busy_timeout = 30000;")
        self._create_tables()
        self._migrate_api_key_id_column()

    def _create_tables(self):
        """Create all required tables if they don't exist."""
        cursor = self.conn.cursor()

        # PDF tracking table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS pdfs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_name TEXT UNIQUE NOT NULL,
                file_path TEXT NOT NULL,
                file_hash TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                json_path TEXT,
                error_message TEXT,
                tokens_used INTEGER DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                processing_started_at TEXT,
                processing_completed_at TEXT
            )
        """)

        # API usage tracking table - per-request log (api_key_id added via migration)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS api_usage (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                pdf_file_name TEXT,
                prompt_tokens INTEGER DEFAULT 0,
                completion_tokens INTEGER DEFAULT 0,
                total_tokens INTEGER DEFAULT 0,
                model TEXT,
                success INTEGER DEFAULT 1,
                api_key_id TEXT DEFAULT '',
                key_id TEXT DEFAULT ''
            )
        """)

        # Daily usage summary for RPD tracking
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS daily_usage (
                date TEXT PRIMARY KEY,
                request_count INTEGER DEFAULT 0,
                total_tokens INTEGER DEFAULT 0,
                last_updated TEXT NOT NULL
            )
        """)

        # Fast indexed library table for structured research JSON cards
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS research_library (
                file_name TEXT PRIMARY KEY,
                json_path TEXT NOT NULL,
                title TEXT,
                authors TEXT,
                publication_year INTEGER,
                paper_type TEXT,
                has_strategy INTEGER DEFAULT 0,
                strategy_family TEXT,
                strategy_name TEXT,
                asset_classes TEXT,
                reproducibility TEXT,
                live_deployment TEXT,
                sharpe_ratio REAL,
                annual_return REAL,
                max_drawdown REAL,
                win_rate REAL,
                abstract TEXT,
                hypothesis TEXT,
                keywords TEXT,
                formula_count INTEGER DEFAULT 0,
                findings_count INTEGER DEFAULT 0,
                research_question TEXT,
                file_mtime REAL,
                updated_at TEXT
            )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_lib_year ON research_library(publication_year)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_lib_strat ON research_library(has_strategy, strategy_family)")

        # Migration for existing database instances
        try:
            lib_cols = [row[1] for row in cursor.execute("PRAGMA table_info(research_library)").fetchall()]
            if "formula_count" not in lib_cols:
                cursor.execute("ALTER TABLE research_library ADD COLUMN formula_count INTEGER DEFAULT 0")
            if "findings_count" not in lib_cols:
                cursor.execute("ALTER TABLE research_library ADD COLUMN findings_count INTEGER DEFAULT 0")
            if "research_question" not in lib_cols:
                cursor.execute("ALTER TABLE research_library ADD COLUMN research_question TEXT")
        except Exception:
            pass

        self.conn.commit()

    def _migrate_api_key_id_column(self):
        """Add api_key_id column to api_usage if it doesn't exist and migrate legacy usage to primary key."""
        with self.lock:
            try:
                cols = [row[1] for row in self.conn.execute("PRAGMA table_info(api_usage)").fetchall()]
                if "api_key_id" not in cols:
                    self.conn.execute("ALTER TABLE api_usage ADD COLUMN api_key_id TEXT DEFAULT ''")
                    self.conn.commit()
                if "key_id" not in cols:
                    self.conn.execute("ALTER TABLE api_usage ADD COLUMN key_id TEXT DEFAULT ''")
                    self.conn.commit()

                # Migrate legacy requests to the primary key
                # 1) If key_id has values, copy to api_key_id
                if "key_id" in cols:
                    self.conn.execute(
                        "UPDATE api_usage SET api_key_id = key_id WHERE (api_key_id IS NULL OR api_key_id = '') AND key_id IS NOT NULL AND key_id != ''"
                    )
                    self.conn.commit()

                # 2) Any remaining legacy unassigned requests (api_key_id is empty or NULL) belong to the primary key ('key_1')
                self.conn.execute(
                    "UPDATE api_usage SET api_key_id = 'key_1' WHERE api_key_id IS NULL OR api_key_id = ''"
                )
                if "key_id" in cols:
                    self.conn.execute(
                        "UPDATE api_usage SET key_id = 'key_1' WHERE key_id IS NULL OR key_id = ''"
                    )
                self.conn.commit()
            except Exception:
                pass

    def close(self):
        """Close the database connection."""
        if self.conn:
            self.conn.close()

    # ─── PDF Tracking ─────────────────────────────────────────────

    def get_existing_file_names(self) -> set[str]:
        """Get set of all registered file names quickly."""
        with self.lock:
            rows = self.conn.execute("SELECT file_name FROM pdfs").fetchall()
            return {r[0] for r in rows}

    def add_pdfs_batch(self, items: list[tuple[str, str]]) -> int:
        """
        Batch add new PDFs without reading file content or computing hashes up front.
        items: list of (file_name, file_path)
        """
        if not items:
            return 0
        now = datetime.now(timezone.utc).isoformat()
        records = [(name, path, "", "pending", now, now) for name, path in items]
        with self.lock:
            cursor = self.conn.cursor()
            cursor.executemany(
                """INSERT OR IGNORE INTO pdfs (file_name, file_path, file_hash, status, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                records
            )
            self.conn.commit()
            return cursor.rowcount

    def add_pdf(self, file_name: str, file_path: str, file_hash: str = "") -> bool:
        """Add a new PDF to tracking. Returns True if added, False if already exists."""
        now = datetime.now(timezone.utc).isoformat()
        with self.lock:
            try:
                self.conn.execute(
                    """INSERT INTO pdfs (file_name, file_path, file_hash, status, created_at, updated_at)
                       VALUES (?, ?, ?, 'pending', ?, ?)""",
                    (file_name, file_path, file_hash, now, now)
                )
                self.conn.commit()
                return True
            except sqlite3.IntegrityError:
                return False

    def get_pdf_status(self, file_name: str) -> dict | None:
        """Get the status of a specific PDF."""
        with self.lock:
            row = self.conn.execute(
                "SELECT * FROM pdfs WHERE file_name = ?", (file_name,)
            ).fetchone()
            return dict(row) if row else None

    def get_all_pdfs(self) -> list[dict]:
        """Get all tracked PDFs."""
        with self.lock:
            rows = self.conn.execute(
                "SELECT * FROM pdfs ORDER BY created_at DESC"
            ).fetchall()
            return [dict(r) for r in rows]

    def get_pdfs_by_status(self, status: str) -> list[dict]:
        """Get PDFs filtered by status."""
        with self.lock:
            rows = self.conn.execute(
                "SELECT * FROM pdfs WHERE status = ? ORDER BY created_at DESC", (status,)
            ).fetchall()
            return [dict(r) for r in rows]

    def get_pending_pdfs(self) -> list[dict]:
        """Get all PDFs that haven't been processed yet."""
        with self.lock:
            rows = self.conn.execute(
                "SELECT * FROM pdfs WHERE status = 'pending' ORDER BY created_at ASC"
            ).fetchall()
            return [dict(r) for r in rows]

    def claim_next_pending_pdf(self) -> dict | None:
        """Atomically claim the next pending PDF for processing by a worker."""
        with self.lock:
            now = datetime.now(timezone.utc).isoformat()
            cursor = self.conn.cursor()
            cursor.execute(
                "SELECT * FROM pdfs WHERE status = 'pending' ORDER BY created_at ASC LIMIT 1"
            )
            row = cursor.fetchone()
            if not row:
                return None
            pdf_dict = dict(row)
            cursor.execute(
                """UPDATE pdfs SET status = 'processing', processing_started_at = ?, updated_at = ?
                   WHERE id = ? AND status = 'pending'""",
                (now, now, pdf_dict["id"])
            )
            self.conn.commit()
            if cursor.rowcount > 0:
                return pdf_dict
            return None

    def claim_next_for_buffer(self) -> dict | None:
        """Atomically claim the next pending PDF for pre-extraction buffer."""
        with self.lock:
            now = datetime.now(timezone.utc).isoformat()
            cursor = self.conn.cursor()
            cursor.execute(
                "SELECT * FROM pdfs WHERE status = 'pending' ORDER BY created_at ASC LIMIT 1"
            )
            row = cursor.fetchone()
            if not row:
                return None
            pdf_dict = dict(row)
            cursor.execute(
                """UPDATE pdfs SET status = 'buffered', updated_at = ?
                   WHERE id = ? AND status = 'pending'""",
                (now, pdf_dict["id"])
            )
            self.conn.commit()
            if cursor.rowcount > 0:
                return pdf_dict
            return None

    def get_pending_count(self) -> int:
        """Count number of pending PDFs in queue."""
        with self.lock:
            row = self.conn.execute("SELECT COUNT(*) FROM pdfs WHERE status = 'pending'").fetchone()
            return row[0] if row else 0

    def reset_buffered_to_pending(self, file_names: list[str] = None) -> int:
        """Reset buffered PDFs back to pending state."""
        now = datetime.now(timezone.utc).isoformat()
        with self.lock:
            if file_names:
                placeholders = ",".join("?" for _ in file_names)
                cursor = self.conn.execute(
                    f"""UPDATE pdfs SET status = 'pending', updated_at = ?
                       WHERE status = 'buffered' AND file_name IN ({placeholders})""",
                    [now] + list(file_names)
                )
            else:
                cursor = self.conn.execute(
                    """UPDATE pdfs SET status = 'pending', updated_at = ?
                       WHERE status = 'buffered'""",
                    (now,)
                )
            self.conn.commit()
            return cursor.rowcount

    def update_pdf_status(self, file_name: str, status: str,
                          json_path: str = None, error_message: str = None,
                          tokens_used: int = 0, file_hash: str = None):
        """Update the processing status of a PDF."""
        now = datetime.now(timezone.utc).isoformat()
        with self.lock:
            if status == 'processing':
                self.conn.execute(
                    """UPDATE pdfs SET status = ?, updated_at = ?, processing_started_at = ?
                       WHERE file_name = ?""",
                    (status, now, now, file_name)
                )
            elif status == 'buffered':
                self.conn.execute(
                    """UPDATE pdfs SET status = ?, updated_at = ?
                       WHERE file_name = ?""",
                    (status, now, file_name)
                )
            elif status == 'completed':
                if file_hash:
                    self.conn.execute(
                        """UPDATE pdfs SET status = ?, json_path = ?, tokens_used = ?,
                           file_hash = ?, updated_at = ?, processing_completed_at = ?
                           WHERE file_name = ?""",
                        (status, json_path, tokens_used, file_hash, now, now, file_name)
                    )
                else:
                    self.conn.execute(
                        """UPDATE pdfs SET status = ?, json_path = ?, tokens_used = ?,
                           updated_at = ?, processing_completed_at = ?
                           WHERE file_name = ?""",
                        (status, json_path, tokens_used, now, now, file_name)
                    )
            elif status == 'error':
                self.conn.execute(
                    """UPDATE pdfs SET status = ?, error_message = ?, updated_at = ?
                       WHERE file_name = ?""",
                    (status, error_message, now, file_name)
                )
            elif status == 'pending':
                # Reset to pending (e.g., for retry)
                self.conn.execute(
                    """UPDATE pdfs SET status = ?, error_message = NULL, json_path = NULL,
                       updated_at = ?, processing_started_at = NULL, processing_completed_at = NULL
                       WHERE file_name = ?""",
                    (status, now, file_name)
                )
            self.conn.commit()

    def get_stats(self) -> dict:
        """Get processing statistics atomically in a single query with lock."""
        with self.lock:
            row = self.conn.execute("""
                SELECT 
                    COUNT(*),
                    COALESCE(SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END), 0),
                    COALESCE(SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END), 0),
                    COALESCE(SUM(CASE WHEN status = 'error' THEN 1 ELSE 0 END), 0),
                    COALESCE(SUM(CASE WHEN status = 'processing' THEN 1 ELSE 0 END), 0),
                    COALESCE(SUM(CASE WHEN status = 'buffered' THEN 1 ELSE 0 END), 0)
                FROM pdfs
            """).fetchone()
            if row:
                buffered = row[5] or 0
                pending = (row[2] or 0) + buffered
                return {
                    "total": row[0] or 0,
                    "completed": row[1] or 0,
                    "pending": pending,
                    "errors": row[3] or 0,
                    "processing": row[4] or 0,
                    "buffered": buffered
                }
            return {"total": 0, "completed": 0, "pending": 0, "errors": 0, "processing": 0, "buffered": 0}

    def is_pdf_processed(self, file_name: str) -> bool:
        """Check if a PDF has already been processed successfully."""
        with self.lock:
            row = self.conn.execute(
                "SELECT status FROM pdfs WHERE file_name = ?", (file_name,)
            ).fetchone()
            return row is not None and row["status"] == "completed"

    def reset_stale_processing(self):
        """Reset any PDFs stuck in 'processing' or 'buffered' state (from interrupted runs)."""
        now = datetime.now(timezone.utc).isoformat()
        with self.lock:
            self.conn.execute(
                """UPDATE pdfs SET status = 'pending', updated_at = ?
                   WHERE status IN ('processing', 'buffered')""",
                (now,)
            )
            self.conn.commit()

    def reset_errors_to_pending(self) -> int:
        """Reset all errored PDFs back to pending state for retry."""
        now = datetime.now(timezone.utc).isoformat()
        with self.lock:
            cursor = self.conn.execute(
                """UPDATE pdfs SET status = 'pending', error_message = NULL, updated_at = ?
                   WHERE status = 'error'""",
                (now,)
            )
            self.conn.commit()
            return cursor.rowcount

    # ─── API Usage Tracking ───────────────────────────────────────

    def log_api_call(self, pdf_file_name: str, prompt_tokens: int,
                     completion_tokens: int, total_tokens: int,
                     model: str, success: bool = True, api_key_id: str = ""):
        """Log an API call for rate limiting tracking, tagged by api_key_id."""
        now = datetime.now(timezone.utc).isoformat()
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        with self.lock:
            cols = [row[1] for row in self.conn.execute("PRAGMA table_info(api_usage)").fetchall()]
            if "key_id" in cols:
                self.conn.execute(
                    """INSERT INTO api_usage (timestamp, pdf_file_name, prompt_tokens,
                       completion_tokens, total_tokens, model, success, api_key_id, key_id)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (now, pdf_file_name, prompt_tokens, completion_tokens, total_tokens,
                     model, 1 if success else 0, api_key_id, api_key_id)
                )
            else:
                self.conn.execute(
                    """INSERT INTO api_usage (timestamp, pdf_file_name, prompt_tokens,
                       completion_tokens, total_tokens, model, success, api_key_id)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (now, pdf_file_name, prompt_tokens, completion_tokens, total_tokens,
                     model, 1 if success else 0, api_key_id)
                )

            # Update daily summary
            existing = self.conn.execute(
                "SELECT * FROM daily_usage WHERE date = ?", (today,)
            ).fetchone()

            if existing:
                self.conn.execute(
                    """UPDATE daily_usage SET request_count = request_count + 1,
                       total_tokens = total_tokens + ?, last_updated = ?
                       WHERE date = ?""",
                    (total_tokens, now, today)
                )
            else:
                self.conn.execute(
                    """INSERT INTO daily_usage (date, request_count, total_tokens, last_updated)
                       VALUES (?, 1, ?, ?)""",
                    (today, total_tokens, now)
                )

            self.conn.commit()

    def get_requests_last_minute(self, api_key_id: str = None) -> int:
        """Get number of API requests in the last 60 seconds, optionally filtered by key (excludes quota sync adjustments)."""
        cutoff = (datetime.now(timezone.utc) - timedelta(seconds=60)).isoformat()
        with self.lock:
            if api_key_id:
                row = self.conn.execute(
                    """SELECT COUNT(*) FROM api_usage
                       WHERE timestamp > ? AND (api_key_id = ? OR key_id = ?)
                       AND pdf_file_name != '[Google Daily Quota Sync]'""",
                    (cutoff, api_key_id, api_key_id)
                ).fetchone()
            else:
                row = self.conn.execute(
                    """SELECT COUNT(*) FROM api_usage
                       WHERE timestamp > ?
                       AND pdf_file_name != '[Google Daily Quota Sync]'""",
                    (cutoff,)
                ).fetchone()
            return row[0] if row else 0

    def get_tokens_last_minute(self, api_key_id: str = None) -> int:
        """Get total tokens used in the last 60 seconds, optionally filtered by key (excludes quota sync adjustments)."""
        cutoff = (datetime.now(timezone.utc) - timedelta(seconds=60)).isoformat()
        with self.lock:
            if api_key_id:
                row = self.conn.execute(
                    """SELECT COALESCE(SUM(total_tokens), 0) FROM api_usage
                       WHERE timestamp > ? AND (api_key_id = ? OR key_id = ?)
                       AND pdf_file_name != '[Google Daily Quota Sync]'""",
                    (cutoff, api_key_id, api_key_id)
                ).fetchone()
            else:
                row = self.conn.execute(
                    """SELECT COALESCE(SUM(total_tokens), 0) FROM api_usage
                       WHERE timestamp > ?
                       AND pdf_file_name != '[Google Daily Quota Sync]'""",
                    (cutoff,)
                ).fetchone()
            return row[0] if row else 0

    def get_requests_today(self, api_key_id: str = None) -> int:
        """Get number of API requests in the rolling 24-hour window from usage, optionally filtered by key."""
        cutoff_24h = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
        with self.lock:
            if api_key_id:
                row = self.conn.execute(
                    "SELECT COUNT(*) FROM api_usage WHERE timestamp > ? AND (api_key_id = ? OR key_id = ?)",
                    (cutoff_24h, api_key_id, api_key_id)
                ).fetchone()
            else:
                row = self.conn.execute(
                    "SELECT COUNT(*) FROM api_usage WHERE timestamp > ?", (cutoff_24h,)
                ).fetchone()
            return row[0] if row else 0

    def sync_daily_quota_exhausted(self, api_key_id: str, limit: int = 500):
        """
        Synchronize local RPD counter to limit (default 500) when Google returns 429 Daily Quota Exceeded.
        Ensures that local tracking immediately reflects the limit without inflating RPM.
        """
        cutoff_24h = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
        with self.lock:
            if api_key_id:
                row = self.conn.execute(
                    "SELECT COUNT(*) FROM api_usage WHERE timestamp > ? AND (api_key_id = ? OR key_id = ?)",
                    (cutoff_24h, api_key_id, api_key_id)
                ).fetchone()
            else:
                row = self.conn.execute(
                    "SELECT COUNT(*) FROM api_usage WHERE timestamp > ?", (cutoff_24h,)
                ).fetchone()
            current_rpd = row[0] if row else 0
            needed = max(0, limit - current_rpd)
            if needed > 0:
                # Place timestamp safely in the past (e.g. 2 hours ago) so it counts towards 24h RPD but NEVER towards 60s RPM
                sync_time = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
                cols = [row[1] for row in self.conn.execute("PRAGMA table_info(api_usage)").fetchall()]
                has_key_id = "key_id" in cols
                cursor = self.conn.cursor()
                for _ in range(needed):
                    if has_key_id:
                        cursor.execute(
                            """INSERT INTO api_usage (timestamp, pdf_file_name, prompt_tokens,
                               completion_tokens, total_tokens, model, success, api_key_id, key_id)
                               VALUES (?, '[Google Daily Quota Sync]', 0, 0, 0, 'gemini-3.5-flash-lite', 1, ?, ?)""",
                            (sync_time, api_key_id, api_key_id)
                        )
                    else:
                        cursor.execute(
                            """INSERT INTO api_usage (timestamp, pdf_file_name, prompt_tokens,
                               completion_tokens, total_tokens, model, success, api_key_id)
                               VALUES (?, '[Google Daily Quota Sync]', 0, 0, 0, 'gemini-3.5-flash-lite', 1, ?)""",
                            (sync_time, api_key_id)
                        )
                self.conn.commit()

    def get_rpd_reset_info(self, api_key_id: str = None) -> dict:
        """
        Calculate rolling 24-hour reset timestamps from usage:
        - full_reset_ts / full_reset_seconds: 24h from the LATEST request in the 24h window (when RPD resets completely back to 0/500).
        - next_available_ts / next_available_seconds: 24h from the OLDEST request (when the very next 1 request frees up).
        """
        cutoff_24h = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
        now_dt = datetime.now(timezone.utc)
        with self.lock:
            if api_key_id:
                row = self.conn.execute(
                    """SELECT MIN(timestamp), MAX(timestamp), COUNT(*) FROM api_usage
                       WHERE timestamp > ? AND (api_key_id = ? OR key_id = ?)""",
                    (cutoff_24h, api_key_id, api_key_id)
                ).fetchone()
            else:
                row = self.conn.execute(
                    """SELECT MIN(timestamp), MAX(timestamp), COUNT(*) FROM api_usage
                       WHERE timestamp > ?""",
                    (cutoff_24h,)
                ).fetchone()

            if row and row[2] > 0 and row[0] and row[1]:
                min_dt = datetime.fromisoformat(row[0])
                max_dt = datetime.fromisoformat(row[1])

                next_avail_dt = min_dt + timedelta(hours=24)
                full_reset_dt = max_dt + timedelta(hours=24)

                next_avail_sec = max(0.0, (next_avail_dt - now_dt).total_seconds())
                full_reset_sec = max(0.0, (full_reset_dt - now_dt).total_seconds())

                return {
                    "full_reset_ts": full_reset_dt.isoformat(),
                    "full_reset_seconds": full_reset_sec,
                    "next_available_ts": next_avail_dt.isoformat(),
                    "next_available_seconds": next_avail_sec,
                    "rpd_count": row[2]
                }

        return {
            "full_reset_ts": None,
            "full_reset_seconds": 0.0,
            "next_available_ts": None,
            "next_available_seconds": 0.0,
            "rpd_count": 0
        }

    def reset_key_daily_quota(self, api_key_id: str = None):
        """
        Manually clear/reset daily usage for a key (or all keys) by removing [Google Daily Quota Sync]
        records and shifting requests in the last 24h to 25 hours ago.
        """
        cutoff_24h = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
        yesterday_iso = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
        with self.lock:
            if api_key_id:
                self.conn.execute(
                    """DELETE FROM api_usage WHERE timestamp > ? 
                       AND (api_key_id = ? OR key_id = ?)
                       AND pdf_file_name = '[Google Daily Quota Sync]'""",
                    (cutoff_24h, api_key_id, api_key_id)
                )
                self.conn.execute(
                    """UPDATE api_usage SET timestamp = ?
                       WHERE timestamp > ? AND (api_key_id = ? OR key_id = ?)""",
                    (yesterday_iso, cutoff_24h, api_key_id, api_key_id)
                )
            else:
                self.conn.execute(
                    """DELETE FROM api_usage WHERE timestamp > ? 
                       AND pdf_file_name = '[Google Daily Quota Sync]'""",
                    (cutoff_24h,)
                )
                self.conn.execute(
                    """UPDATE api_usage SET timestamp = ?
                       WHERE timestamp > ?""",
                    (yesterday_iso, cutoff_24h)
                )
            self.conn.commit()

    def get_tokens_today(self) -> int:
        """Get total tokens used today."""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        with self.lock:
            row = self.conn.execute(
                "SELECT total_tokens FROM daily_usage WHERE date = ?", (today,)
            ).fetchone()
            return row[0] if row else 0

    def get_total_tokens_all_time(self) -> int:
        """Get total tokens used across all time."""
        with self.lock:
            row = self.conn.execute(
                "SELECT COALESCE(SUM(total_tokens), 0) FROM api_usage"
            ).fetchone()
            return row[0] if row else 0

    def get_total_requests_all_time(self) -> int:
        """Get total API requests across all time."""
        with self.lock:
            row = self.conn.execute(
                "SELECT COUNT(*) FROM api_usage"
            ).fetchone()
            return row[0] if row else 0

    def can_make_request(self, rpm_limit: int, tpm_limit: int, rpd_limit: int,
                         estimated_tokens: int = 0,
                         max_utilization_pct: float = 0.80,
                         api_key_id: str = None) -> tuple[bool, str, float]:
        """
        Check if we can make an API request within rate limits, adhering to a utilization threshold.
        max_utilization_pct: e.g. 0.80 (stops/waits if >= 80% of limit is used).
        If api_key_id is given, checks limits for that specific key.
        Returns (can_proceed, reason, wait_seconds).
        """
        effective_rpm = max(1, int(rpm_limit * max_utilization_pct))
        effective_tpm = max(1000, int(tpm_limit * max_utilization_pct))
        # RPD limit is NOT capped by max_utilization_pct; it goes up to 100% of rpd_limit
        effective_rpd = rpd_limit

        # Check RPM
        rpm_current = self.get_requests_last_minute(api_key_id=api_key_id)
        if rpm_current >= effective_rpm:
            # Find oldest request in the last minute to know when we can retry
            cutoff = (datetime.now(timezone.utc) - timedelta(seconds=60)).isoformat()
            with self.lock:
                if api_key_id:
                    oldest = self.conn.execute(
                        """SELECT timestamp FROM api_usage
                           WHERE timestamp > ? AND (api_key_id = ? OR key_id = ?)
                           AND pdf_file_name != '[Google Daily Quota Sync]'
                           ORDER BY timestamp ASC LIMIT 1""",
                        (cutoff, api_key_id, api_key_id)
                    ).fetchone()
                else:
                    oldest = self.conn.execute(
                        """SELECT timestamp FROM api_usage
                           WHERE timestamp > ?
                           AND pdf_file_name != '[Google Daily Quota Sync]'
                           ORDER BY timestamp ASC LIMIT 1""",
                        (cutoff,)
                    ).fetchone()
            if oldest:
                oldest_time = datetime.fromisoformat(oldest[0])
                wait = 60 - (datetime.now(timezone.utc) - oldest_time).total_seconds()
                wait = max(wait, 1)
            else:
                wait = 5
            return False, f"RPM threshold reached ({rpm_current}/{effective_rpm} at {int(max_utilization_pct*100)}% cap)", wait

        # Check TPM
        tpm_current = self.get_tokens_last_minute(api_key_id=api_key_id)
        if estimated_tokens > 0 and (tpm_current + estimated_tokens) > effective_tpm:
            return False, f"TPM limit threshold reached ({tpm_current + estimated_tokens:,}/{effective_tpm:,} at {int(max_utilization_pct*100)}% cap)", 15

        # Check RPD (Rolling 24-hour cycle)
        rpd_current = self.get_requests_today(api_key_id=api_key_id)
        if rpd_current >= effective_rpd:
            rpd_info = self.get_rpd_reset_info(api_key_id=api_key_id)
            wait = max(rpd_info.get("next_available_seconds", 60.0), 15.0)
            return False, f"RPD napi kvóta elérve ({rpd_current}/{effective_rpd} kérés). Következő szabad kérés {wait/60:.1f} perc múlva.", wait

        return True, "OK", 0

    def get_usage_summary(self, api_key_id: str = None) -> dict:
        """Get a comprehensive usage summary for the GUI, optionally for a specific key."""
        rpd_info = self.get_rpd_reset_info(api_key_id=api_key_id)
        return {
            "rpm_current": self.get_requests_last_minute(api_key_id=api_key_id),
            "tpm_current": self.get_tokens_last_minute(api_key_id=api_key_id),
            "rpd_current": self.get_requests_today(api_key_id=api_key_id),
            "tokens_today": self.get_tokens_today(),
            "total_tokens": self.get_total_tokens_all_time(),
            "total_requests": self.get_total_requests_all_time(),
            "rpd_reset_ts": rpd_info["full_reset_ts"],
            "rpd_reset_seconds": rpd_info["full_reset_seconds"],
            "rpd_next_available_ts": rpd_info["next_available_ts"],
            "rpd_next_available_seconds": rpd_info["next_available_seconds"],
        }

    def get_per_key_usage(self, api_keys: list[dict]) -> list[dict]:
        """
        Get usage summary for each API key.
        api_keys: list of dicts with at minimum {"id": "key_id", "rpd": rpd_limit}
        Returns list of dicts with id, rpd_used, rpd_limit, rpd_remaining, rpm_current, tpm_current.
        """
        result = []
        for key_cfg in api_keys:
            kid = key_cfg.get("id", "")
            rpd_limit = key_cfg.get("rpd", 500)
            rpm_limit = key_cfg.get("rpm", 15)
            tpm_limit = key_cfg.get("tpm", 250000)

            rpd_used = self.get_requests_today(api_key_id=kid)
            rpm_current = self.get_requests_last_minute(api_key_id=kid)
            tpm_current = self.get_tokens_last_minute(api_key_id=kid)
            rpd_info = self.get_rpd_reset_info(api_key_id=kid)

            result.append({
                "id": kid,
                "label": key_cfg.get("label", kid[:8] + "..."),
                "rpd_used": rpd_used,
                "rpd_limit": rpd_limit,
                "rpd_remaining": max(0, rpd_limit - rpd_used),
                "rpd_pct": round((rpd_used / max(1, rpd_limit)) * 100, 1),
                "rpm_current": rpm_current,
                "rpm_limit": rpm_limit,
                "tpm_current": tpm_current,
                "tpm_limit": tpm_limit,
                "rpd_reset_ts": rpd_info["full_reset_ts"],
                "rpd_reset_seconds": rpd_info["full_reset_seconds"],
                "rpd_next_available_ts": rpd_info["next_available_ts"],
                "rpd_next_available_seconds": rpd_info["next_available_seconds"],
            })
        return result

    def select_best_key(self, api_keys: list[dict], max_utilization_pct: float = 0.80) -> dict | None:
        """
        Select the API key with the most remaining RPD quota that is not over capacity.
        Returns the key dict or None if all keys exhausted.
        api_keys: list of dicts with {"id", "key", "label", "rpd", "rpm", "tpm"}
        """
        best_key = None
        best_remaining = -1

        for key_cfg in api_keys:
            kid = key_cfg.get("id", "")
            rpd_limit = key_cfg.get("rpd", 500)
            rpd_used = self.get_requests_today(api_key_id=kid)
            rpd_remaining = rpd_limit - rpd_used

            if rpd_remaining > 0 and rpd_remaining > best_remaining:
                best_remaining = rpd_remaining
                best_key = key_cfg

        return best_key

    def get_recent_api_calls(self, limit: int = 20) -> list[dict]:
        """Get recent API call logs."""
        rows = self.conn.execute(
            "SELECT * FROM api_usage ORDER BY timestamp DESC LIMIT ?",
            (limit,)
        ).fetchall()
        return [dict(r) for r in rows]

    # ─── Research Library Methods ─────────────────────────────────────────────

    def _parse_json_for_library(self, file_path: Path, mtime: float = None) -> tuple | None:
        """Parse structured research JSON file into database library tuple."""
        try:
            if mtime is None:
                mtime = file_path.stat().st_mtime
            with open(file_path, "r", encoding="utf-8") as fp:
                data = json.load(fp)

            doc = data.get("document", {}) or {}
            strat = data.get("strategy", {}) or {}
            perf = data.get("performance", {}) or {}
            mkts = data.get("markets", {}) or {}
            repro = data.get("reproducibility", {}) or {}
            dep = data.get("live_deployment", {}) or {}
            res = data.get("research", {}) or {}

            def parse_num(val):
                if isinstance(val, (int, float)):
                    return float(val)
                return None

            fn = file_path.name
            title = doc.get("title") or file_path.stem

            raw_authors = doc.get("authors") or []
            authors_clean = []
            for a in raw_authors:
                if isinstance(a, str):
                    authors_clean.append(a.strip())
                elif isinstance(a, dict) and "name" in a:
                    authors_clean.append(str(a["name"]).strip())
            authors_json = json.dumps(authors_clean, ensure_ascii=False)

            pub_year = doc.get("publication_year")
            try:
                pub_year = int(pub_year) if pub_year else None
            except Exception:
                pub_year = None

            paper_type = doc.get("paper_type") or "Research"
            has_strategy = 1 if strat.get("present") is True else 0
            strategy_family = strat.get("family")
            strategy_name = strat.get("name")

            raw_assets = mkts.get("asset_classes") or []
            asset_classes_json = json.dumps(raw_assets if isinstance(raw_assets, list) else [str(raw_assets)], ensure_ascii=False)

            reproducibility = repro.get("classification") if isinstance(repro, dict) else str(repro) if repro else "Unknown"
            live_deployment = dep.get("technical_feasibility") if isinstance(dep, dict) else str(dep) if dep else "Unknown"

            sharpe = parse_num(perf.get("sharpe_ratio"))
            cagr = parse_num(perf.get("annualized_return") or perf.get("cagr") or perf.get("total_return"))
            mdd = parse_num(perf.get("max_drawdown"))
            win_rate = parse_num(perf.get("win_rate"))

            abstract = (doc.get("abstract") or "")[:800]
            hypothesis = (res.get("hypothesis") or "")[:800]
            research_question = (res.get("research_question") or "")[:800]
            formula_count = len(data.get("formulas") or [])
            findings_count = len(data.get("key_findings") or [])
            keywords = json.dumps(doc.get("keywords") or [], ensure_ascii=False)
            now_iso = datetime.now(timezone.utc).isoformat()

            return (
                fn,
                str(file_path),
                title,
                authors_json,
                pub_year,
                paper_type,
                has_strategy,
                strategy_family,
                strategy_name,
                asset_classes_json,
                reproducibility,
                live_deployment,
                sharpe,
                cagr,
                mdd,
                win_rate,
                abstract,
                hypothesis,
                keywords,
                formula_count,
                findings_count,
                research_question,
                mtime,
                now_iso
            )
        except Exception:
            return None

    def sync_library_index(self, json_dir: Path | str) -> int:
        """Scan json_dir and incrementally index all research JSONs into research_library."""
        json_dir = Path(json_dir)
        if not json_dir.exists():
            return 0

        with self.lock:
            cur = self.conn.cursor()
            cur.execute("SELECT file_name, file_mtime FROM research_library")
            existing_mtimes = dict(cur.fetchall())

            files = list(json_dir.glob("*.json"))
            batch = []

            for f in files:
                try:
                    mtime = f.stat().st_mtime
                    fn = f.name
                    if fn in existing_mtimes and existing_mtimes[fn] == mtime:
                        continue
                    item_tuple = self._parse_json_for_library(f, mtime)
                    if item_tuple:
                        batch.append(item_tuple)
                except Exception:
                    continue

            if batch:
                cur.executemany("""
                    INSERT OR REPLACE INTO research_library (
                        file_name, json_path, title, authors, publication_year, paper_type,
                        has_strategy, strategy_family, strategy_name, asset_classes,
                        reproducibility, live_deployment, sharpe_ratio, annual_return,
                        max_drawdown, win_rate, abstract, hypothesis, keywords,
                        formula_count, findings_count, research_question,
                        file_mtime, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, batch)
                self.conn.commit()

            return len(batch)

    def upsert_library_item_from_json(self, json_path: Path | str):
        """Upsert a single JSON file into the research_library table."""
        json_path = Path(json_path)
        if not json_path.exists():
            return
        item_tuple = self._parse_json_for_library(json_path)
        if not item_tuple:
            return
        with self.lock:
            self.conn.execute("""
                INSERT OR REPLACE INTO research_library (
                    file_name, json_path, title, authors, publication_year, paper_type,
                    has_strategy, strategy_family, strategy_name, asset_classes,
                    reproducibility, live_deployment, sharpe_ratio, annual_return,
                    max_drawdown, win_rate, abstract, hypothesis, keywords,
                    formula_count, findings_count, research_question,
                    file_mtime, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, item_tuple)
            self.conn.commit()

    def get_library_filters(self) -> dict:
        """Get distinct strategy families, asset classes, and summary statistics for the library."""
        with self.lock:
            cur = self.conn.cursor()
            cur.execute("SELECT count(*) FROM research_library")
            total = cur.fetchone()[0] or 0

            cur.execute("SELECT count(*) FROM research_library WHERE has_strategy = 1")
            has_strategy_count = cur.fetchone()[0] or 0

            cur.execute("""
                SELECT strategy_family, count(*) as cnt
                FROM research_library
                WHERE strategy_family IS NOT NULL AND strategy_family != ''
                GROUP BY strategy_family
                ORDER BY cnt DESC
            """)
            families = [{"family": r[0], "count": r[1]} for r in cur.fetchall()]

            cur.execute("""
                SELECT asset_classes FROM research_library
                WHERE asset_classes IS NOT NULL AND asset_classes != '' AND asset_classes != '[]'
            """)
            asset_counter = {}
            for row in cur.fetchall():
                try:
                    ac_list = json.loads(row[0])
                    for ac in ac_list:
                        if ac and isinstance(ac, str):
                            asset_counter[ac] = asset_counter.get(ac, 0) + 1
                except Exception:
                    pass

            sorted_assets = sorted(asset_counter.items(), key=lambda x: x[1], reverse=True)
            asset_classes = [{"asset_class": k, "count": v} for k, v in sorted_assets[:20]]

            cur.execute("""
                SELECT DISTINCT publication_year FROM research_library
                WHERE publication_year IS NOT NULL AND publication_year > 1980 AND publication_year < 2030
                ORDER BY publication_year DESC
            """)
            years = [r[0] for r in cur.fetchall()]

            cur.execute("SELECT count(*) FROM research_library WHERE formula_count > 0")
            formulas_count = cur.fetchone()[0] or 0

            return {
                "total_count": total,
                "has_strategy_count": has_strategy_count,
                "formulas_count": formulas_count,
                "families": families,
                "asset_classes": asset_classes,
                "years": years
            }

    def query_library(self, page: int = 1, limit: int = 24, search: str = "",
                      family: str = "", asset_class: str = "",
                      has_strategy: str = "", reproducibility: str = "",
                      sort_by: str = "year_desc") -> dict:
        """
        Execute filtered paginated query for the research library.
        Returns dict with total, page, limit, total_pages, and parsed item dicts.
        """
        page = max(1, page)
        limit = max(1, min(100, limit))
        offset = (page - 1) * limit

        where_clauses = []
        params = []

        if search:
            s = f"%{search.strip()}%"
            where_clauses.append("""(
                title LIKE ? OR
                file_name LIKE ? OR
                authors LIKE ? OR
                strategy_name LIKE ? OR
                keywords LIKE ? OR
                abstract LIKE ? OR
                hypothesis LIKE ? OR
                research_question LIKE ?
            )""")
            params.extend([s, s, s, s, s, s, s, s])

        if family:
            where_clauses.append("strategy_family = ?")
            params.append(family)

        if asset_class:
            where_clauses.append("asset_classes LIKE ?")
            params.append(f"%{asset_class}%")

        if has_strategy in ("yes", "true", "1", True):
            where_clauses.append("has_strategy = 1")
        elif has_strategy in ("no", "false", "0", False):
            where_clauses.append("has_strategy = 0")

        if reproducibility:
            where_clauses.append("reproducibility = ?")
            params.append(reproducibility)

        where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

        # Sorting
        sort_map = {
            "year_desc": "publication_year DESC NULLS LAST, file_name ASC",
            "year_asc": "publication_year ASC NULLS LAST, file_name ASC",
            "sharpe_desc": "sharpe_ratio DESC NULLS LAST, publication_year DESC",
            "title_asc": "title ASC",
            "filename_asc": "file_name ASC",
            "file_asc": "file_name ASC"
        }
        order_sql = sort_map.get(sort_by, "publication_year DESC NULLS LAST, file_name ASC")

        with self.lock:
            cur = self.conn.cursor()

            # Count total matching
            count_query = f"SELECT count(*) FROM research_library {where_sql}"
            cur.execute(count_query, params)
            total = cur.fetchone()[0] or 0

            # Fetch page items
            data_query = f"""
                SELECT file_name, json_path, title, authors, publication_year, paper_type,
                       has_strategy, strategy_family, strategy_name, asset_classes,
                       reproducibility, live_deployment, sharpe_ratio, annual_return,
                       max_drawdown, win_rate, abstract, hypothesis, keywords, updated_at,
                       formula_count, findings_count, research_question
                FROM research_library
                {where_sql}
                ORDER BY {order_sql}
                LIMIT ? OFFSET ?
            """
            cur.execute(data_query, params + [limit, offset])
            rows = cur.fetchall()

            import math
            total_pages = math.ceil(total / limit) if total > 0 else 1

            items = []
            for r in rows:
                try:
                    authors = json.loads(r[3]) if r[3] else []
                except Exception:
                    authors = []
                try:
                    asset_classes = json.loads(r[9]) if r[9] else []
                except Exception:
                    asset_classes = []
                try:
                    keywords = json.loads(r[18]) if r[18] else []
                except Exception:
                    keywords = []

                items.append({
                    "file_name": r[0],
                    "json_path": r[1],
                    "title": r[2] or r[0],
                    "authors": authors,
                    "publication_year": r[4],
                    "paper_type": r[5] or "Research",
                    "has_strategy": bool(r[6]),
                    "strategy_family": r[7],
                    "strategy_name": r[8],
                    "asset_classes": asset_classes,
                    "reproducibility": r[10] or "Unknown",
                    "live_deployment": r[11] or "Unknown",
                    "sharpe_ratio": r[12],
                    "annual_return": r[13],
                    "max_drawdown": r[14],
                    "win_rate": r[15],
                    "abstract": r[16] or "",
                    "hypothesis": r[17] or "",
                    "keywords": keywords,
                    "updated_at": r[19],
                    "formula_count": r[20] or 0,
                    "findings_count": r[21] or 0,
                    "research_question": r[22] or ""
                })

            return {
                "total": total,
                "page": page,
                "limit": limit,
                "total_pages": total_pages,
                "items": items
            }


