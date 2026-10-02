"""
Web-based GUI for arXiv Research PDF Processor.
FastAPI + WebSocket backend providing real-time multithreaded processing,
dedicated worker log streams, live quota utilization percentage tracking,
multi-API-key management with per-key RPD tracking and automatic key selection,
and zero UI freezing.
"""

import os
import sys
import json
import time
import asyncio
import logging
import threading
import webbrowser
import hashlib
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Any
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, BackgroundTasks
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import uvicorn
from websockets.exceptions import ConnectionClosed, ConnectionClosedError

from database import Database
from pdf_processor import PDFProcessor
from gemini_analyzer import (
    GeminiAnalyzer,
    DailyQuotaExhaustedError,
    is_daily_quota_error,
    is_demand_spike_error,
    is_per_minute_quota_error,
    extract_retry_delay
)

# Base paths
BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "config.json"
WEB_DIR = BASE_DIR / "web"
WEB_DIR.mkdir(exist_ok=True)

@asynccontextmanager
async def lifespan(app: FastAPI):
    global loop
    loop = asyncio.get_running_loop()
    worker_mgr.cleanup_buffers_to_pending()
    threading.Thread(target=lambda: worker_mgr.db.sync_library_index(worker_mgr.json_dir), daemon=True).start()
    metrics_task = asyncio.create_task(metrics_broadcaster_loop())
    try:
        yield
    finally:
        metrics_task.cancel()



# App instance
app = FastAPI(title="FinMind Research Studio", lifespan=lifespan)

# Mount static files if present
if WEB_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")


def _generate_key_id(key_value: str) -> str:
    """Generate a stable short ID from the API key value."""
    return "key_" + hashlib.sha256(key_value.encode()).hexdigest()[:8]


def migrate_config(cfg: dict) -> dict:
    """Migrate old single api_key config to multi-key api_keys format."""
    if "api_key" in cfg and "api_keys" not in cfg:
        old_key = cfg.pop("api_key", "")
        old_rate = cfg.get("rate_limits", {})
        if old_key:
            cfg["api_keys"] = [{
                "id": _generate_key_id(old_key),
                "key": old_key,
                "label": "Barni",
                "rpm": old_rate.get("rpm", 15),
                "tpm": old_rate.get("tpm", 250000),
                "rpd": old_rate.get("rpd", 500),
            }]
        else:
            cfg["api_keys"] = []
        cfg["active_key_mode"] = "auto"
        cfg["active_key_id"] = None
    if "api_keys" not in cfg:
        cfg["api_keys"] = []
    if "active_key_mode" not in cfg:
        cfg["active_key_mode"] = "auto"
    if "active_key_id" not in cfg:
        cfg["active_key_id"] = None
    return cfg


class ConnectionManager:
    """Manages active WebSocket connections and broadcasts events."""

    def __init__(self):
        self.active_connections: List[WebSocket] = []
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        async with self._lock:
            self.active_connections.append(websocket)

    async def disconnect(self, websocket: WebSocket):
        async with self._lock:
            if websocket in self.active_connections:
                self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        async with self._lock:
            living_connections = []
            for connection in self.active_connections:
                try:
                    await connection.send_json(message)
                    living_connections.append(connection)
                except Exception:
                    pass
            self.active_connections = living_connections


manager = ConnectionManager()
loop: Optional[asyncio.AbstractEventLoop] = None


class WorkerManager:
    """Manages multithreaded background workers for PDF processing."""

    def __init__(self):
        self.config = self.load_config()
        raw_db_path = self.config.get("db_path", "research.db")
        db_path = Path(raw_db_path) if Path(raw_db_path).is_absolute() else (BASE_DIR / raw_db_path)
        self.db = Database(str(db_path))
        self.pdf_dir = BASE_DIR / self.config.get("pdf_dir", "pdf")
        self.json_dir = BASE_DIR / self.config.get("json_dir", "json")
        self.pdf_dir.mkdir(exist_ok=True)
        self.json_dir.mkdir(exist_ok=True)
        try:
            self.scan_pdfs()
        except Exception as e:
            print(f"[Startup] Initial PDF scan notice: {e}")

        self.is_processing = False
        self.should_stop = False
        self.worker_threads: List[threading.Thread] = []
        self.buffer_threads: List[threading.Thread] = []
        self.worker_buffer_slots: Dict[int, Dict[int, Dict[str, Any]]] = {}
        self.buffer_lock = threading.Lock()
        self.active_workers_count = 0
        self.worker_status: Dict[int, Dict[str, Any]] = {}
        self.workers_lock = threading.Lock()
        self.last_dispatched_slot: Dict[int, int] = {}

    def load_config(self) -> dict:
        if CONFIG_PATH.exists():
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            cfg = migrate_config(cfg)
            return cfg
        return {
            "api_keys": [],
            "active_key_mode": "auto",
            "active_key_id": None,
            "model": "gemini-3.5-flash-lite",
            "fallback_models": [],
            "processing": {"concurrent_workers": 2, "max_utilization_pct": 80}
        }

    def save_config(self, new_cfg: dict):
        # Merge with disk config so external changes to keys or labels are preserved
        if CONFIG_PATH.exists():
            try:
                with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                    disk_cfg = json.load(f)
                disk_keys = {k["id"]: k for k in disk_cfg.get("api_keys", []) if "id" in k}
                mem_keys = new_cfg.get("api_keys", [])
                for mk in mem_keys:
                    kid = mk.get("id")
                    if kid in disk_keys and "label" in disk_keys[kid]:
                        mk["label"] = disk_keys[kid]["label"]
                mem_ids = {mk.get("id") for mk in mem_keys}
                for kid, dk in disk_keys.items():
                    if kid not in mem_ids:
                        mem_keys.append(dk)
                new_cfg["api_keys"] = mem_keys
            except Exception:
                pass
        self.config.update(new_cfg)
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(self.config, f, indent=4, ensure_ascii=False)

    def reload_config(self) -> dict:
        try:
            self.config = self.load_config()
        except Exception:
            pass
        return self.config

    def get_api_keys(self) -> list[dict]:
        """Return the list of configured API keys."""
        self.reload_config()
        return self.config.get("api_keys", [])

    def get_active_key(self) -> dict | None:
        """
        Get the currently active API key based on mode:
        - 'manual': use the key specified by active_key_id
        - 'auto': use the key with most remaining RPD quota
        """
        api_keys = self.get_api_keys()
        if not api_keys:
            return None

        mode = self.config.get("active_key_mode", "auto")
        active_id = self.config.get("active_key_id")

        if mode == "manual" and active_id:
            for k in api_keys:
                if k["id"] == active_id:
                    return k

        # Auto mode: select best key
        proc_cfg = self.config.get("processing", {})
        utilization_cap = max(0.1, min(1.0, proc_cfg.get("max_utilization_pct", 80) / 100.0))
        best = self.db.select_best_key(api_keys, max_utilization_pct=utilization_cap)
        return best if best else (api_keys[0] if api_keys else None)

    def log_event(self, worker_id: Any, message: str, level: str = "info"):
        """Emit real-time log event to WebSocket clients."""
        ts = datetime.now().strftime("%H:%M:%S")
        data = {
            "type": "log",
            "worker_id": worker_id,
            "message": message,
            "level": level,
            "timestamp": ts
        }
        if loop and loop.is_running():
            asyncio.run_coroutine_threadsafe(manager.broadcast(data), loop)

    def build_metrics_payload(self) -> dict:
        """Build standardized live metrics dict, focusing RPD and limits on the active key."""
        api_keys = self.get_api_keys()
        active_key = self.get_active_key()
        active_key_id = active_key["id"] if active_key else None

        # Per-key usage data (RPD used, remaining, reset countdown for each key)
        per_key_usage = self.db.get_per_key_usage(api_keys) if api_keys else []

        # Active key's usage
        active_usage = next((u for u in per_key_usage if u["id"] == active_key_id), None)
        if not active_usage and per_key_usage:
            active_usage = per_key_usage[0]

        # Active key RPD stats (daily limit belongs to the selected key)
        key_rpd_current = active_usage["rpd_used"] if active_usage else 0
        key_rpd_limit = active_usage["rpd_limit"] if active_usage else (active_key.get("rpd", 500) if active_key else 500)
        key_rpd_pct = active_usage["rpd_pct"] if active_usage else 0.0
        key_rpd_reset_ts = active_usage["rpd_reset_ts"] if active_usage else None
        key_rpd_reset_seconds = active_usage["rpd_reset_seconds"] if active_usage else 0.0
        key_rpd_next_ts = active_usage.get("rpd_next_available_ts") if active_usage else None
        key_rpd_next_seconds = active_usage.get("rpd_next_available_seconds", 0.0) if active_usage else 0.0

        # Overall usage summary for tokens and requests
        overall_usage = self.db.get_usage_summary(api_key_id=active_key_id)

        # Active key throughput limits
        key_rpm_limit = active_key.get("rpm", 15) if active_key else 15
        key_tpm_limit = active_key.get("tpm", 250000) if active_key else 250000
        rpm_current = overall_usage.get("rpm_current", 0)
        tpm_current = overall_usage.get("tpm_current", 0)

        proc_config = self.config.get("processing", {})
        utilization_cap = proc_config.get("max_utilization_pct", 80)

        return {
            "rpm": rpm_current,
            "rpm_limit": key_rpm_limit,
            "rpm_pct": round((rpm_current / max(1, key_rpm_limit)) * 100, 1),
            "tpm": tpm_current,
            "tpm_limit": key_tpm_limit,
            "tpm_pct": round((tpm_current / max(1, key_tpm_limit)) * 100, 1),
            "rpd": key_rpd_current,
            "rpd_limit": key_rpd_limit,
            "rpd_pct": key_rpd_pct,
            "rpd_reset_ts": key_rpd_reset_ts,
            "rpd_reset_seconds": key_rpd_reset_seconds,
            "rpd_next_available_ts": key_rpd_next_ts,
            "rpd_next_available_seconds": key_rpd_next_seconds,
            "tokens_today": overall_usage.get("tokens_today", 0),
            "total_tokens": overall_usage.get("total_tokens", 0),
            "total_requests": overall_usage.get("total_requests", 0),
            "utilization_cap": utilization_cap,
            "per_key_usage": per_key_usage,
            "active_key_id": active_key_id,
            "active_key_label": active_key.get("label", "Barni") if active_key else "Nincs kulcs",
            "active_key_mode": self.config.get("active_key_mode", "auto"),
            "worker_buffers": self.get_worker_buffers_summary(),
        }

    def get_worker_buffers_summary(self) -> dict:
        """Return structured summary of the 3 pre-extraction buffer slots for each worker."""
        with self.buffer_lock:
            summary = {}
            for wid, slots in self.worker_buffer_slots.items():
                slot_list = []
                last_sid = self.last_dispatched_slot.get(wid, 0)
                for sid in (1, 2, 3):
                    s = slots.get(sid, {"status": "idle", "file_name": None, "item": None, "detail": "Üres (Készenlét)"})
                    slot_list.append({
                        "slot": sid,
                        "status": s.get("status", "idle"),
                        "file_name": s.get("file_name"),
                        "estimated_tokens": s.get("item", {}).get("estimated_tokens", 0) if s.get("item") else 0,
                        "detail": s.get("detail", "Üres (Készenlét)"),
                        "is_last_dispatched": (sid == last_sid)
                    })
                summary[str(wid)] = slot_list
            return summary

    def cleanup_buffers_to_pending(self):
        """Reset all buffered items back to pending in database so no PDFs are lost."""
        with self.buffer_lock:
            file_names_to_reset = []
            for wid, slots in self.worker_buffer_slots.items():
                for sid, s in slots.items():
                    fn = s.get("file_name")
                    if fn:
                        file_names_to_reset.append(fn)
                    slots[sid] = {
                        "status": "idle",
                        "file_name": None,
                        "item": None,
                        "detail": "Üres (Készenlét)"
                    }
            for fn in file_names_to_reset:
                self.db.update_pdf_status(fn, "pending")
                self.broadcast_pdf_update(fn, "pending")
            self.db.reset_buffered_to_pending()
            self.db.reset_stale_processing()
            self.last_dispatched_slot.clear()
        self.broadcast_worker_buffers()

    def broadcast_worker_buffers(self):
        """Broadcast buffer state to all connected WebSocket clients."""
        data = {
            "type": "worker_buffers_update",
            "worker_buffers": self.get_worker_buffers_summary()
        }
        if loop and loop.is_running():
            asyncio.run_coroutine_threadsafe(manager.broadcast(data), loop)

    def broadcast_metrics(self):
        """Calculate live usage and percentage utilization, including per-key data and buffers."""
        try:
            metrics = self.build_metrics_payload()
            stats = self.db.get_stats()
            data = {
                "type": "metrics",
                "metrics": metrics,
                "stats": stats,
                "is_processing": self.is_processing,
                "worker_status": dict(self.worker_status),
                "worker_buffers": self.get_worker_buffers_summary()
            }
            if loop and loop.is_running():
                asyncio.run_coroutine_threadsafe(manager.broadcast(data), loop)
        except Exception as e:
            pass

    def broadcast_pdf_update(self, file_name: str, status: str, tokens_used: int = 0,
                             json_path: str = None, error_message: str = None):
        """Broadcast real-time status update for a specific PDF row."""
        data = {
            "type": "pdf_update",
            "pdf": {
                "file_name": file_name,
                "status": status,
                "tokens_used": tokens_used,
                "json_path": json_path,
                "error_message": error_message
            }
        }
        if loop and loop.is_running():
            asyncio.run_coroutine_threadsafe(manager.broadcast(data), loop)

    def broadcast_refresh(self):
        """Signal all connected clients to reload the full PDF table."""
        data = {"type": "refresh_table"}
        if loop and loop.is_running():
            asyncio.run_coroutine_threadsafe(manager.broadcast(data), loop)

    def scan_pdfs(self) -> dict:
        """Scan the local PDF directory and register new files."""
        pdf_files = list(self.pdf_dir.glob("*.pdf"))
        existing_names = self.db.get_existing_file_names()
        new_items = [(p.name, str(p)) for p in pdf_files if p.name not in existing_names]

        new_count = self.db.add_pdfs_batch(new_items) if new_items else 0
        self.log_event("system", f"Scanned {len(pdf_files)} PDF(s). Found {new_count} new file(s).",
                       "info" if new_count == 0 else "success")
        self.broadcast_metrics()
        self.broadcast_refresh()
        return {"total_scanned": len(pdf_files), "new_added": new_count}

    def start_processing(self) -> dict:
        """Start parallel workers to process queue with background prefetch buffers."""
        if self.is_processing:
            return {"status": "already_running"}

        # Check for any API keys
        if not self.get_api_keys():
            self.log_event("system", "Nincs API kulcs konfigurálva! Adj hozzá kulcsot a beállításokban.", "error")
            return {"status": "no_api_keys", "message": "No API keys configured."}

        self.db.reset_stale_processing()
        self.cleanup_buffers_to_pending()
        self.scan_pdfs()
        pending = self.db.get_pending_pdfs()
        if not pending:
            self.log_event("system", "Nincs feldolgozásra váró PDF a listában.", "warning")
            return {"status": "empty_queue", "message": "No pending PDFs in queue."}

        proc_cfg = self.config.get("processing", {})
        num_workers = max(1, proc_cfg.get("concurrent_workers", 2))
        cap_pct = proc_cfg.get("max_utilization_pct", 80)

        self.is_processing = True
        self.should_stop = False
        self.worker_threads.clear()
        self.buffer_threads.clear()

        with self.buffer_lock:
            self.last_dispatched_slot.clear()
            self.worker_buffer_slots.clear()
            for wid in range(1, num_workers + 1):
                self.worker_buffer_slots[wid] = {
                    sid: {
                        "status": "idle",
                        "file_name": None,
                        "item": None,
                        "detail": "Üres (Készenlét)"
                    }
                    for sid in (1, 2, 3)
                }

        with self.workers_lock:
            self.active_workers_count = num_workers
            self.worker_status.clear()
            for wid in range(1, num_workers + 1):
                self.worker_status[wid] = {"status": "Készenlét (Idle)", "current_file": None, "tokens": None}

        self.log_event("system", f"Feldolgozás elindítva {num_workers} workerrel (3 párhuzamos puffer szál worker-enként).", "processing")
        self.broadcast_metrics()
        self.broadcast_worker_buffers()

        # 1. Start 3 dedicated buffer slot threads per worker (Slot 1, Slot 2, Slot 3)
        for worker_id in range(1, num_workers + 1):
            for slot_id in (1, 2, 3):
                bt = threading.Thread(
                    target=self._buffer_slot_loop,
                    args=(worker_id, slot_id),
                    daemon=True
                )
                self.buffer_threads.append(bt)
                bt.start()

        # 2. Start worker LLM threads
        for worker_id in range(1, num_workers + 1):
            wt = threading.Thread(target=self._worker_loop, args=(worker_id,), daemon=True)
            self.worker_threads.append(wt)
            wt.start()

        return {"status": "started", "workers": num_workers}

    def stop_processing(self) -> dict:
        """Request all workers and buffer threads to stop, wait for completion, then clean up."""
        if not self.is_processing and not self.should_stop:
            return {"status": "not_running"}

        if self.should_stop:
            return {"status": "already_stopping"}

        self.should_stop = True
        self.log_event("system", "Leállítás kérve. Megvárjuk, amíg a folyamatban lévő szálak befejeződnek...", "warning")
        self.broadcast_metrics()

        cleanup_thread = threading.Thread(target=self._stop_and_cleanup_worker, daemon=True)
        cleanup_thread.start()
        return {"status": "stopping"}

    def _stop_and_cleanup_worker(self):
        """Wait for all buffer threads and worker threads to exit, then purge buffers and processing list."""
        try:
            # 1. Wait for buffer threads to finish
            for bt in list(self.buffer_threads):
                if bt.is_alive():
                    bt.join(timeout=8.0)

            # 2. Wait for worker threads to finish
            for wt in list(self.worker_threads):
                if wt.is_alive():
                    wt.join(timeout=3.0)

        except Exception as e:
            self.log_event("system", f"Hiba a szálak leállítási várakozásakor: {e}", "warning")

        # 3. Clean up buffers and return all buffered items to pending in DB
        with self.buffer_lock:
            file_names_to_reset = []
            for wid, slots in self.worker_buffer_slots.items():
                for sid, s in slots.items():
                    fn = s.get("file_name")
                    if fn:
                        file_names_to_reset.append(fn)
                    slots[sid] = {
                        "status": "idle",
                        "file_name": None,
                        "item": None,
                        "detail": "Üres (Készenlét)"
                    }
            for fn in file_names_to_reset:
                self.db.update_pdf_status(fn, "pending")
                self.broadcast_pdf_update(fn, "pending")

            self.db.reset_buffered_to_pending()
            self.last_dispatched_slot.clear()

        # 4. Clean up any stale processing items in DB back to pending
        self.db.reset_stale_processing()

        # 5. Clear in-memory worker status
        with self.workers_lock:
            self.active_workers_count = 0
            for wid in list(self.worker_status.keys()):
                self.worker_status[wid] = {"status": "Készenlét (Idle)", "current_file": None, "tokens": None}

        # 6. Clear thread lists and reset flags
        self.worker_threads.clear()
        self.buffer_threads.clear()
        self.is_processing = False
        self.should_stop = False

        self.log_event("system", "Minden szál sikeresen leállt. A pufferek és az épp feldolgozás alatt lévő lista kiürítve.", "success")

        # 7. Notify all clients
        self.broadcast_worker_buffers()
        self.broadcast_metrics()
        self.broadcast_refresh()

    def _buffer_slot_loop(self, worker_id: int, slot_id: int):
        """
        Dedicated thread for worker_id buffer slot slot_id.
        Continuously ensures this buffer slot holds a pre-extracted PDF.
        Runs completely independently of LLM API network / rate limit pauses.
        """
        while not self.should_stop:
            with self.buffer_lock:
                slot_data = self.worker_buffer_slots.get(worker_id, {}).get(slot_id, {})
                is_ready = (slot_data.get("status") == "ready")

            if is_ready:
                time.sleep(0.25)
                continue

            if self.should_stop:
                break

            # Atomically claim the next pending PDF for this buffer slot
            pdf_info = self.db.claim_next_for_buffer()
            if not pdf_info:
                time.sleep(0.3)
                if self.should_stop:
                    break
                pending_count = self.db.get_pending_count()
                with self.buffer_lock:
                    all_slots_empty = all(
                        s.get("status") == "idle"
                        for w_slots in self.worker_buffer_slots.values()
                        for s in w_slots.values()
                    )
                if pending_count == 0 and all_slots_empty:
                    with self.workers_lock:
                        if self.active_workers_count <= 0:
                            break
                continue

            if self.should_stop:
                self.db.update_pdf_status(pdf_info["file_name"], "pending")
                self.broadcast_pdf_update(pdf_info["file_name"], "pending")
                break

            file_name = pdf_info["file_name"]
            file_path = pdf_info["file_path"]

            with self.buffer_lock:
                if worker_id in self.worker_buffer_slots and slot_id in self.worker_buffer_slots[worker_id]:
                    self.worker_buffer_slots[worker_id][slot_id] = {
                        "status": "extracting",
                        "file_name": file_name,
                        "item": None,
                        "detail": f"Kinyerés: {file_name}..."
                    }
            self.broadcast_worker_buffers()
            self.broadcast_pdf_update(file_name, "buffered")
            self.broadcast_metrics()

            if not Path(file_path).exists():
                self.log_event(worker_id, f"[Slot #{slot_id}] Fájl nem található: {file_name}. Kihagyás.", "error")
                self.db.update_pdf_status(file_name, "error", error_message="File not found on disk")
                self.broadcast_pdf_update(file_name, "error", error_message="File not found on disk")
                with self.buffer_lock:
                    if worker_id in self.worker_buffer_slots and slot_id in self.worker_buffer_slots[worker_id]:
                        self.worker_buffer_slots[worker_id][slot_id] = {
                            "status": "idle",
                            "file_name": None,
                            "item": None,
                            "detail": "Hiba: Fájl hiányzik"
                        }
                self.broadcast_worker_buffers()
                self.broadcast_metrics()
                continue

            try:
                # Text, table, and image extraction (PyMuPDF & pdfplumber)
                pdf_data = PDFProcessor.process_pdf(file_path)
                estimated_tokens = PDFProcessor.estimate_token_count(pdf_data.get("full_text", ""))

                item = {
                    "pdf_info": pdf_info,
                    "pdf_data": pdf_data,
                    "estimated_tokens": estimated_tokens
                }

                if self.should_stop:
                    self.db.update_pdf_status(file_name, "pending")
                    self.broadcast_pdf_update(file_name, "pending")
                    break

                with self.buffer_lock:
                    if worker_id in self.worker_buffer_slots and slot_id in self.worker_buffer_slots[worker_id]:
                        self.worker_buffer_slots[worker_id][slot_id] = {
                            "status": "ready",
                            "file_name": file_name,
                            "item": item,
                            "detail": f"Kész: {file_name} (~{estimated_tokens:,} tok)"
                        }

                self.broadcast_worker_buffers()
                self.broadcast_metrics()

            except Exception as e:
                if self.should_stop:
                    self.db.update_pdf_status(file_name, "pending")
                    self.broadcast_pdf_update(file_name, "pending")
                    break
                self.log_event(worker_id, f"[Slot #{slot_id}] Hiba az előfeldolgozás során ({file_name}): {e}", "error")
                err_msg = str(e)[:500]
                self.db.update_pdf_status(file_name, "error", error_message=err_msg)
                self.broadcast_pdf_update(file_name, "error", error_message=err_msg)
                with self.buffer_lock:
                    if worker_id in self.worker_buffer_slots and slot_id in self.worker_buffer_slots[worker_id]:
                        self.worker_buffer_slots[worker_id][slot_id] = {
                            "status": "idle",
                            "file_name": None,
                            "item": None,
                            "detail": "Hiba történt"
                        }
                self.broadcast_worker_buffers()
                self.broadcast_metrics()

    def _worker_loop(self, worker_id: int):
        retry_cfg = self.config.get("retry", {})
        self.log_event(worker_id, f"Worker #{worker_id} online és feladatra kész.", "info")

        while not self.should_stop:
            try:
                item = None
                with self.buffer_lock:
                    # Alternating round-robin order between buffer slots 1, 2, 3
                    last_sid = self.last_dispatched_slot.get(worker_id, 3)
                    check_order = [((last_sid + i - 1) % 3) + 1 for i in range(1, 4)]
                    w_slots = self.worker_buffer_slots.get(worker_id, {})
                    for sid in check_order:
                        s = w_slots.get(sid, {})
                        if s.get("status") == "ready" and s.get("item"):
                            item = s["item"]
                            self.last_dispatched_slot[worker_id] = sid
                            w_slots[sid] = {
                                "status": "idle",
                                "file_name": None,
                                "item": None,
                                "detail": "Üres (Készenlét)"
                            }
                            break

                # Work-stealing fallback if my worker slots are empty but another worker has a ready slot
                if not item:
                    with self.buffer_lock:
                        for other_wid, o_slots in self.worker_buffer_slots.items():
                            if other_wid != worker_id:
                                other_last_sid = self.last_dispatched_slot.get(other_wid, 3)
                                other_order = [((other_last_sid + i - 1) % 3) + 1 for i in range(1, 4)]
                                for sid in other_order:
                                    s = o_slots.get(sid, {})
                                    if s.get("status") == "ready" and s.get("item"):
                                        item = s["item"]
                                        self.last_dispatched_slot[other_wid] = sid
                                        o_slots[sid] = {
                                            "status": "idle",
                                            "file_name": None,
                                            "item": None,
                                            "detail": "Üres (Készenlét)"
                                        }
                                        break
                                if item:
                                    break

                if not item:
                    # No ready item in slots. Check if there are still pending PDFs or active extractions
                    pending = self.db.get_pending_count()
                    with self.buffer_lock:
                        any_active = any(
                            s.get("status") in ("extracting", "ready")
                            for w_slots in self.worker_buffer_slots.values()
                            for s in w_slots.values()
                        )
                    if pending == 0 and not any_active:
                        break
                    time.sleep(0.15)
                    continue

                # Immediately broadcast buffer update so that slot's thread wakes up and begins fetching next!
                self.broadcast_worker_buffers()
                self.broadcast_metrics()

                pdf_info = item["pdf_info"]
                pdf_data = item["pdf_data"]
                estimated_tokens = item["estimated_tokens"]
                file_name = pdf_info["file_name"]
                file_path = pdf_info["file_path"]

                # Select the best API key for this request
                active_key = self.get_active_key()
                if not active_key:
                    self.log_event(worker_id, "Nincs elérhető API kulcs (összes kvóta elfogyott)! Várakozás 60s...", "error")
                    with self.buffer_lock:
                        if worker_id in self.worker_buffer_slots:
                            for sid in (1, 2, 3):
                                if self.worker_buffer_slots[worker_id][sid]["status"] == "idle":
                                    self.worker_buffer_slots[worker_id][sid] = {
                                        "status": "ready",
                                        "file_name": file_name,
                                        "item": item,
                                        "detail": f"Kész: {file_name}"
                                    }
                                    break
                    self._interruptible_sleep(60)
                    continue

                key_id = active_key["id"]
                key_value = active_key["key"]
                key_label = active_key.get("label", key_id[:8])

                try:
                    analyzer = GeminiAnalyzer(
                        api_key=key_value,
                        model_name=self.config.get("model", "gemini-3.5-flash-lite"),
                        fallback_models=self.config.get("fallback_models", []),
                        max_retries=retry_cfg.get("max_retries", 3),
                        initial_delay=retry_cfg.get("initial_delay_seconds", 10),
                        max_delay=retry_cfg.get("max_delay_seconds", 120),
                        backoff_multiplier=retry_cfg.get("backoff_multiplier", 2.0),
                    )
                except Exception as e:
                    self.log_event(worker_id, f"Nem sikerült inicializálni a Gemini analyzert ('{key_label}'): {e}", "error")
                    self._interruptible_sleep(10)
                    continue

                # Rate limit wait (per-key) BEFORE claiming active LLM status
                # Notice: All 3 buffer slot threads keep extracting during this wait!
                self._wait_for_rate_limit(estimated_tokens, worker_id, api_key_id=key_id)
                if self.should_stop:
                    self.db.update_pdf_status(file_name, "pending")
                    self.broadcast_pdf_update(file_name, "pending")
                    break

                # STRICTLY AT THIS POINT: Item is sent to Gemini LLM API -> "Épp Feldolgozás Alatt"
                self.db.update_pdf_status(file_name, "processing")
                with self.workers_lock:
                    self.worker_status[worker_id] = {
                        "status": "Épp Feldolgozás Alatt (LLM API)",
                        "current_file": file_name,
                        "tokens": estimated_tokens
                    }
                self.broadcast_pdf_update(file_name, "processing")
                self.broadcast_metrics()

                self.log_event(worker_id, f"Kiküldés Gemini LLM API-ra (~{estimated_tokens:,} token, kulcs: '{key_label}')...", "processing")

                try:
                    result, prompt_tok, completion_tok, total_tok = analyzer.analyze_paper(
                        pdf_data,
                        on_status=lambda msg: self.log_event(worker_id, f"  {msg}", "info"),
                        should_stop=lambda: self.should_stop,
                    )

                    # Log API call
                    self.db.log_api_call(
                        pdf_file_name=file_name,
                        prompt_tokens=prompt_tok,
                        completion_tokens=completion_tok,
                        total_tokens=total_tok,
                        model=self.config.get("model", "gemini-3.5-flash-lite"),
                        success=True,
                        api_key_id=key_id
                    )

                    # Save JSON locally
                    json_filename = Path(file_name).stem + ".json"
                    json_path = str(self.json_dir / json_filename)
                    with open(json_path, "w", encoding="utf-8") as f:
                        json.dump(result, f, indent=2, ensure_ascii=False)

                    # Update DB
                    file_hash = pdf_data.get("file_hash")
                    self.db.update_pdf_status(
                        file_name, "completed",
                        json_path=json_path,
                        tokens_used=total_tok,
                        file_hash=file_hash
                    )
                    try:
                        self.db.upsert_library_item_from_json(json_path)
                    except Exception as lib_err:
                        logger.warning(f"Library index frissitesi hiba ({json_filename}): {lib_err}")
                    self.log_event(worker_id, f"Befejezve: {file_name} -> {json_filename} ({total_tok:,} token)", "success")
                    self.broadcast_pdf_update(file_name, "completed", tokens_used=total_tok, json_path=json_path)

                except InterruptedError:
                    self.log_event(worker_id, f"Megszakítva feldolgozás közben: {file_name}. Visszaállítás várakozóra.", "warning")
                    self.db.update_pdf_status(file_name, "pending")
                    self.broadcast_pdf_update(file_name, "pending")
                    break
                except (DailyQuotaExhaustedError, Exception) as e:
                    if isinstance(e, DailyQuotaExhaustedError) or is_daily_quota_error(e):
                        limit = getattr(e, 'limit', 500)
                        self.db.sync_daily_quota_exhausted(key_id, limit=limit)
                        self.db.update_pdf_status(file_name, "pending")
                        self.broadcast_pdf_update(file_name, "pending")
                        with self.workers_lock:
                            self.worker_status[worker_id] = {"status": "Készenlét (Idle)", "current_file": None, "tokens": None}
                        self.log_event(
                            worker_id,
                            f"Napi kvóta ({limit} RPD) elérve a(z) '{key_label}' kulcson! RPD számláló automatikusan átírva {limit}-ra.",
                            "warning"
                        )
                        self.broadcast_metrics()
                        self.broadcast_worker_buffers()
                        self.broadcast_refresh()
                        self._interruptible_sleep(1)
                        continue
                    elif is_demand_spike_error(e):
                        # Demand Spike (503 UNAVAILABLE): Keep PDF as pending, wait 15s and retry next loop
                        self.db.update_pdf_status(file_name, "pending")
                        self.broadcast_pdf_update(file_name, "pending")
                        with self.workers_lock:
                            self.worker_status[worker_id] = {"status": "Készenlét (Demand Spike várakozás)", "current_file": None, "tokens": None}
                        self.log_event(
                            worker_id,
                            f"Gemini modell átmenetileg túlterhelt (Demand Spike / 503). {file_name} visszatéve a sorba, várakozás 15s...",
                            "warning"
                        )
                        self.broadcast_metrics()
                        self.broadcast_worker_buffers()
                        self.broadcast_refresh()
                        self._interruptible_sleep(15)
                        continue
                    elif is_per_minute_quota_error(e):
                        # Per-minute quota gate (TPM / RPM 429): Keep PDF as pending, wait Google's delay and retry next loop
                        delay_sec = extract_retry_delay(e) or 15.0
                        wait_sec = max(delay_sec + 2.0, 10.0)
                        self.db.update_pdf_status(file_name, "pending")
                        self.broadcast_pdf_update(file_name, "pending")
                        with self.workers_lock:
                            self.worker_status[worker_id] = {"status": "Készenlét (TPM/RPM várakozás)", "current_file": None, "tokens": None}
                        self.log_event(
                            worker_id,
                            f"Átmeneti perces kvótakorlát (TPM/RPM). {file_name} visszatéve a sorba, várakozás {wait_sec:.0f}s...",
                            "warning"
                        )
                        self.broadcast_metrics()
                        self.broadcast_worker_buffers()
                        self.broadcast_refresh()
                        self._interruptible_sleep(wait_sec)
                        continue
                    else:
                        self.log_event(worker_id, f"Hiba a feldolgozás során ({file_name}): {e}", "error")
                        err_str = str(e)[:500]
                        self.db.update_pdf_status(file_name, "error", error_message=err_str)
                        self.broadcast_pdf_update(file_name, "error", error_message=err_str)
                        try:
                            self.db.log_api_call(
                                pdf_file_name=file_name,
                                prompt_tokens=0,
                                completion_tokens=0,
                                total_tokens=0,
                                model=self.config.get("model", "gemini-3.5-flash-lite"),
                                success=False,
                                api_key_id=key_id
                            )
                        except Exception:
                            pass

                with self.workers_lock:
                    self.worker_status[worker_id] = {"status": "Készenlét (Idle)", "current_file": None, "tokens": None}
                self.broadcast_metrics()

            except Exception as loop_err:
                self.log_event(worker_id, f"Worker ciklus hiba: {loop_err}", "warning")
                time.sleep(1)

        with self.workers_lock:
            self.active_workers_count -= 1
            self.worker_status[worker_id] = {"status": "Készenlét (Idle)", "current_file": None, "tokens": None}

        self.log_event(worker_id, f"Worker #{worker_id} leállt.", "info")
        self._check_all_finished()

    def _interruptible_sleep(self, seconds: float):
        """Sleep that can be interrupted by should_stop."""
        end_time = time.time() + seconds
        while time.time() < end_time:
            if self.should_stop:
                return
            time.sleep(min(1, end_time - time.time()))

    def _check_all_finished(self):
        with self.workers_lock:
            all_done = (self.active_workers_count <= 0)

        if all_done and self.is_processing and not self.should_stop:
            self.is_processing = False
            self.should_stop = False
            self.cleanup_buffers_to_pending()
            with self.workers_lock:
                for wid in list(self.worker_status.keys()):
                    self.worker_status[wid] = {"status": "Készenlét (Idle)", "current_file": None, "tokens": None}
            self.log_event("system", "Minden aktív worker befejezte a feldolgozási sort. A pufferek és a lista kiürítve.", "success")
            self.broadcast_metrics()
            self.broadcast_worker_buffers()
            self.broadcast_refresh()

    def _wait_for_rate_limit(self, estimated_tokens: int, worker_id: int, api_key_id: str = None):
        proc_cfg = self.config.get("processing", {})
        utilization_cap = max(0.1, min(1.0, proc_cfg.get("max_utilization_pct", 80) / 100.0))

        # Get limits for the specific key
        api_keys = self.get_api_keys()
        key_cfg = None
        for k in api_keys:
            if k["id"] == api_key_id:
                key_cfg = k
                break

        rpm_limit = key_cfg.get("rpm", 15) if key_cfg else 15
        tpm_limit = key_cfg.get("tpm", 250000) if key_cfg else 250000
        rpd_limit = key_cfg.get("rpd", 500) if key_cfg else 500

        while not self.should_stop:
            can_proceed, reason, wait_seconds = self.db.can_make_request(
                rpm_limit, tpm_limit, rpd_limit,
                estimated_tokens=estimated_tokens,
                max_utilization_pct=utilization_cap,
                api_key_id=api_key_id
            )

            if can_proceed:
                return

            self.log_event(worker_id, f"Kvóta korlát ({int(utilization_cap * 100)}% plafon): {reason}. Várakozás {wait_seconds:.0f}s...", "warning")
            self.broadcast_metrics()

            wait_end = time.time() + wait_seconds
            while time.time() < wait_end and not self.should_stop:
                time.sleep(0.5)


worker_mgr = WorkerManager()


# ─── REST Endpoints ───────────────────────────────────────────────────────────

@app.get("/")
async def get_index():
    index_path = WEB_DIR / "index.html"
    if not index_path.exists():
        return HTMLResponse("<h1>Web GUI is initializing... Please refresh shortly.</h1>")
    return FileResponse(index_path)


@app.get("/api/status")
async def get_status():
    """Get full system status, metrics, and workers."""
    worker_mgr.reload_config()
    return {
        "is_processing": worker_mgr.is_processing,
        "config": worker_mgr.config,
        "metrics": worker_mgr.build_metrics_payload(),
        "stats": worker_mgr.db.get_stats(),
        "worker_status": worker_mgr.worker_status,
        "worker_buffers": worker_mgr.get_worker_buffers_summary()
    }


@app.get("/api/pdfs")
async def get_pdfs(status: Optional[str] = None, search: Optional[str] = None, limit: int = 5000):
    """Retrieve list of PDFs with optional filter."""
    if status and status != "all":
        pdfs = worker_mgr.db.get_pdfs_by_status(status)
    else:
        pdfs = worker_mgr.db.get_all_pdfs()

    if search:
        search_lower = search.lower()
        pdfs = [p for p in pdfs if search_lower in p["file_name"].lower()]

    return {"count": len(pdfs), "pdfs": pdfs[:limit]}


@app.post("/api/scan")
async def scan_directory():
    """Trigger PDF directory scan."""
    result = worker_mgr.scan_pdfs()
    return result


@app.post("/api/start")
async def start_job():
    """Start workers."""
    return worker_mgr.start_processing()


@app.post("/api/stop")
async def stop_job():
    """Stop workers."""
    return worker_mgr.stop_processing()


@app.post("/api/retry-errors")
async def retry_errors():
    """Reset all error status PDFs to pending."""
    count = worker_mgr.db.reset_errors_to_pending()
    worker_mgr.log_event("system", f"Reset {count} error item(s) back to pending.", "info")
    worker_mgr.broadcast_metrics()
    worker_mgr.broadcast_refresh()
    return {"reset_count": count}


# ─── API Key Management Endpoints ────────────────────────────────────────────

@app.get("/api/keys")
async def get_api_keys():
    """Get list of API keys with usage stats (key values masked)."""
    api_keys = worker_mgr.get_api_keys()
    per_key_usage = worker_mgr.db.get_per_key_usage(api_keys) if api_keys else []

    # Mask actual key values for security
    safe_keys = []
    for k in api_keys:
        safe_k = {**k}
        key_val = safe_k.get("key", "")
        safe_k["key_masked"] = key_val[:6] + "..." + key_val[-4:] if len(key_val) > 10 else "***"
        del safe_k["key"]
        safe_keys.append(safe_k)

    return {
        "keys": safe_keys,
        "per_key_usage": per_key_usage,
        "active_key_mode": worker_mgr.config.get("active_key_mode", "auto"),
        "active_key_id": worker_mgr.config.get("active_key_id"),
    }


class AddKeyRequest(BaseModel):
    key: str
    label: Optional[str] = None
    rpm: int = 15
    tpm: int = 250000
    rpd: int = 500


@app.post("/api/keys/add")
async def add_api_key(req: AddKeyRequest):
    """Add a new API key."""
    key_id = _generate_key_id(req.key)
    existing = worker_mgr.config.get("api_keys", [])

    # Check for duplicates
    for k in existing:
        if k["id"] == key_id:
            raise HTTPException(status_code=409, detail="Ez a kulcs már létezik!")

    new_key = {
        "id": key_id,
        "key": req.key,
        "label": req.label or f"Kulcs #{len(existing) + 1}",
        "rpm": req.rpm,
        "tpm": req.tpm,
        "rpd": req.rpd,
    }
    existing.append(new_key)
    worker_mgr.config["api_keys"] = existing
    worker_mgr.save_config(worker_mgr.config)
    worker_mgr.log_event("system", f"API kulcs hozzáadva: '{new_key['label']}' (RPD: {req.rpd})", "success")
    worker_mgr.broadcast_metrics()
    return {"status": "ok", "key_id": key_id}


class RemoveKeyRequest(BaseModel):
    key_id: str


@app.post("/api/keys/remove")
async def remove_api_key(req: RemoveKeyRequest):
    """Remove an API key by ID."""
    existing = worker_mgr.config.get("api_keys", [])
    new_list = [k for k in existing if k["id"] != req.key_id]
    if len(new_list) == len(existing):
        raise HTTPException(status_code=404, detail="Kulcs nem található!")

    worker_mgr.config["api_keys"] = new_list
    # If the removed key was the active one, reset to auto
    if worker_mgr.config.get("active_key_id") == req.key_id:
        worker_mgr.config["active_key_mode"] = "auto"
        worker_mgr.config["active_key_id"] = None
    worker_mgr.save_config(worker_mgr.config)
    worker_mgr.log_event("system", f"API kulcs eltávolítva: {req.key_id}", "info")
    worker_mgr.broadcast_metrics()
    return {"status": "ok"}


class UpdateKeyRequest(BaseModel):
    key_id: str
    label: Optional[str] = None
    rpm: Optional[int] = None
    tpm: Optional[int] = None
    rpd: Optional[int] = None


@app.post("/api/keys/update")
async def update_api_key(req: UpdateKeyRequest):
    """Update an existing API key's metadata."""
    existing = worker_mgr.config.get("api_keys", [])
    for k in existing:
        if k["id"] == req.key_id:
            if req.label is not None:
                k["label"] = req.label
            if req.rpm is not None:
                k["rpm"] = req.rpm
            if req.tpm is not None:
                k["tpm"] = req.tpm
            if req.rpd is not None:
                k["rpd"] = req.rpd
            worker_mgr.config["api_keys"] = existing
            worker_mgr.save_config(worker_mgr.config)
            worker_mgr.broadcast_metrics()
            return {"status": "ok"}
    raise HTTPException(status_code=404, detail="Kulcs nem található!")


class UpdateKeyLabelRequest(BaseModel):
    label: str


@app.post("/api/keys/{key_id}/label")
async def update_key_label(key_id: str, req: UpdateKeyLabelRequest):
    """Update label for an existing key."""
    worker_mgr.reload_config()
    for k in worker_mgr.config.get("api_keys", []):
        if k["id"] == key_id:
            k["label"] = req.label.strip()
            worker_mgr.save_config(worker_mgr.config)
            worker_mgr.broadcast_metrics()
            return {"status": "ok", "key_id": key_id, "label": k["label"]}
    raise HTTPException(status_code=404, detail="Kulcs nem található!")


class SetActiveKeyRequest(BaseModel):
    mode: str  # "auto" or "manual"
    key_id: Optional[str] = None


@app.post("/api/keys/active")
async def set_active_key(req: SetActiveKeyRequest):
    """Set active key mode and optionally the manual key ID."""
    worker_mgr.config["active_key_mode"] = req.mode
    worker_mgr.config["active_key_id"] = req.key_id if req.mode == "manual" else None
    worker_mgr.save_config(worker_mgr.config)

    if req.mode == "auto":
        worker_mgr.log_event("system", "Kulcsválasztás: AUTOMATIKUS (legtöbb szabad RPD)", "info")
    else:
        # Find the label
        label = req.key_id
        for k in worker_mgr.get_api_keys():
            if k["id"] == req.key_id:
                label = k.get("label", req.key_id)
                break
        worker_mgr.log_event("system", f"Kulcsválasztás: KÉZI → '{label}'", "info")

    worker_mgr.broadcast_metrics()
    return {"status": "ok", "mode": req.mode, "key_id": req.key_id}


# ─── Config Endpoints ────────────────────────────────────────────────────────

class ConfigUpdate(BaseModel):
    concurrent_workers: Optional[int] = None
    max_utilization_pct: Optional[int] = None
    model: Optional[str] = None


@app.post("/api/config")
async def update_settings(cfg: ConfigUpdate):
    """Update settings (model, workers, utilization cap)."""
    changed = False
    current_cfg = worker_mgr.config
    if "processing" not in current_cfg:
        current_cfg["processing"] = {}

    if cfg.concurrent_workers is not None:
        current_cfg["processing"]["concurrent_workers"] = max(1, min(8, cfg.concurrent_workers))
        changed = True
    if cfg.max_utilization_pct is not None:
        current_cfg["processing"]["max_utilization_pct"] = max(10, min(100, cfg.max_utilization_pct))
        changed = True
    if cfg.model:
        current_cfg["model"] = cfg.model
        changed = True

    if changed:
        worker_mgr.save_config(current_cfg)
        worker_mgr.log_event("system", "Configuration saved.", "info")
        worker_mgr.broadcast_metrics()

    return {"status": "ok", "config": current_cfg}


@app.get("/api/json-view/{file_name}")
async def view_json(file_name: str):
    """View generated JSON for a PDF."""
    stem = Path(file_name).stem
    json_path = worker_mgr.json_dir / f"{stem}.json"
    if not json_path.exists():
        raise HTTPException(status_code=404, detail="JSON file not found")
    with open(json_path, "r", encoding="utf-8") as f:
        return json.load(f)


@app.get("/api/library")
async def get_library(
    page: int = 1,
    limit: int = 24,
    search: Optional[str] = None,
    family: Optional[str] = None,
    discipline: Optional[str] = None,
    asset_class: Optional[str] = None,
    has_strategy: Optional[bool] = None,
    reproducibility: Optional[str] = None,
    sort_by: str = "year_desc"
):
    """Retrieve paginated and filtered research library papers."""
    return worker_mgr.db.query_library(
        page=page,
        limit=limit,
        search=search,
        family=family,
        discipline=discipline,
        asset_class=asset_class,
        has_strategy=has_strategy,
        reproducibility=reproducibility,
        sort_by=sort_by
    )


@app.get("/api/library/filters")
async def get_library_filters():
    """Retrieve filter metadata for the library (families, asset classes, years, counts)."""
    return worker_mgr.db.get_library_filters()


@app.post("/api/library/sync")
async def sync_library():
    """Manually trigger library index synchronization from json/ directory."""
    def run_sync():
        worker_mgr.db.sync_library_index(worker_mgr.json_dir)
    threading.Thread(target=run_sync, daemon=True).start()
    return {"status": "sync_started"}


@app.post("/api/obsidian/generate")
async def generate_obsidian(force: bool = False):
    """Trigger generation of Obsidian Vault (incremental by default, processing only new JSONs)."""
    obsidian_dir = str(BASE_DIR.parent / "obsidian")
    if obsidian_dir not in sys.path:
        sys.path.insert(0, obsidian_dir)
    import generate_obsidian_vault
    try:
        res = await asyncio.to_thread(generate_obsidian_vault.build_vault, force_full=force)
        return res
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class OpenFolderRequest(BaseModel):
    folder: str  # "pdf", "json", "obsidian", or "root"


@app.post("/api/open-folder")
async def open_folder(req: OpenFolderRequest):
    """Open folder directly in Windows Explorer."""
    target_path = BASE_DIR.parent if req.folder == "root" else BASE_DIR
    if req.folder == "pdf":
        target_path = worker_mgr.pdf_dir
    elif req.folder == "json":
        target_path = worker_mgr.json_dir
    elif req.folder == "obsidian":
        target_path = BASE_DIR.parent / "obsidian" / "vault"
        if not target_path.exists():
            target_path = BASE_DIR.parent / "obsidian"

    try:
        if sys.platform == "win32":
            os.startfile(str(target_path))
        return {"status": "ok", "path": str(target_path)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class QuotaResetRequest(BaseModel):
    api_key_id: Optional[str] = None


@app.post("/api/quota/reset")
async def reset_quota(req: QuotaResetRequest = QuotaResetRequest()):
    """Manually reset RPD daily quota counter for a key or all keys."""
    worker_mgr.db.reset_key_daily_quota(req.api_key_id)
    worker_mgr.broadcast_metrics()
    return {"status": "ok", "message": "Kvóta számláló sikeresen nullázva"}


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket connection for real-time logs, metrics, and worker status."""
    await manager.connect(websocket)
    try:
        worker_mgr.reload_config()
        # Send initial metrics right after connecting
        await websocket.send_json({
            "type": "init",
            "is_processing": worker_mgr.is_processing,
            "config": worker_mgr.config,
            "metrics": worker_mgr.build_metrics_payload(),
            "stats": worker_mgr.db.get_stats(),
            "worker_status": worker_mgr.worker_status,
            "worker_buffers": worker_mgr.get_worker_buffers_summary()
        })

        while True:
            try:
                msg = await websocket.receive_text()
                if msg == "ping":
                    await websocket.send_text("pong")
            except (WebSocketDisconnect, ConnectionClosed, asyncio.CancelledError):
                break
            except Exception:
                break
    except Exception:
        pass
    finally:
        await manager.disconnect(websocket)


async def metrics_broadcaster_loop():
    """Background task to broadcast metrics every 2 seconds for stable sliding window updates."""
    while True:
        try:
            worker_mgr.broadcast_metrics()
        except Exception:
            pass
        await asyncio.sleep(2)




def main():
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    port = 8000
    url = f"http://localhost:{port}"
    print("\n=======================================================")
    print(" arXiv PDF Processor - Modern Web GUI")
    print(f" Server running at: {url}")
    print(f" Local PDF dir: {worker_mgr.pdf_dir}")
    print(f" Local JSON dir: {worker_mgr.json_dir}")
    print(f" Database: {worker_mgr.db.db_path}")
    print(f" API Keys: {len(worker_mgr.get_api_keys())} configured")
    print("=======================================================\n")

    # Automatically open browser
    def open_browser():
        time.sleep(1.2)
        webbrowser.open(url)

    threading.Thread(target=open_browser, daemon=True).start()
    uvicorn.run(
        "web_app:app",
        host="127.0.0.1",
        port=port,
        log_level="warning",
        ws_ping_interval=None,
        ws_ping_timeout=None
    )


if __name__ == "__main__":
    main()
