"""
SSRN Quant Research PDF Analyzer - Main GUI Application

tkinter-based GUI with:
- PDF scanning and processing controls
- API rate limit monitoring
- Processing status display
- Start/Stop/Resume functionality
"""

import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
import json
import os
import sys
import time
import threading
from pathlib import Path
from datetime import datetime, timezone

from database import Database
from pdf_processor import PDFProcessor
from gemini_analyzer import GeminiAnalyzer

# ─── Constants ────────────────────────────────────────────────────────────────

APP_TITLE = "FinMind - Quant Research PDF Analyzer"
CONFIG_FILE = "config.json"
REFRESH_INTERVAL_MS = 1000  # GUI refresh interval


# ─── Helper Functions ─────────────────────────────────────────────────────────

def load_config() -> dict:
    """Load configuration from config.json."""
    config_path = Path(__file__).parent / CONFIG_FILE
    if not config_path.exists():
        raise FileNotFoundError(
            f"Configuration file not found: {config_path}\n"
            f"Please create config.json with your API key."
        )
    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)


def format_number(n: int) -> str:
    """Format a number with thousands separators."""
    return f"{n:,}"


# ─── Main Application ────────────────────────────────────────────────────────

class App:
    """Main application window."""

    def __init__(self):
        # Load config
        try:
            self.config = load_config()
        except FileNotFoundError as e:
            root = tk.Tk()
            root.withdraw()
            messagebox.showerror("Configuration Error", str(e))
            sys.exit(1)

        # Validate API key (supports both old single-key and new multi-key format)
        api_keys = self.config.get("api_keys", [])
        if api_keys:
            self.api_key = api_keys[0].get("key", "")
            self.api_key_id = api_keys[0].get("id", "key_1")
            # Use first key's rate limits as defaults
            first_key = api_keys[0]
            self.rpm_limit = first_key.get("rpm", 15)
            self.tpm_limit = first_key.get("tpm", 250000)
            self.rpd_limit = first_key.get("rpd", 500)
        else:
            self.api_key = self.config.get("api_key", "")
            self.api_key_id = "key_1"
            # Rate limits from config (legacy format)
            self.rpm_limit = self.config.get("rate_limits", {}).get("rpm", 15)
            self.tpm_limit = self.config.get("rate_limits", {}).get("tpm", 1000000)
            self.rpd_limit = self.config.get("rate_limits", {}).get("rpd", 1500)

        if not self.api_key or self.api_key == "YOUR_GOOGLE_AI_STUDIO_API_KEY_HERE":
            root = tk.Tk()
            root.withdraw()
            messagebox.showerror(
                "API Key Missing",
                "Please set your Google AI Studio API key in config.json (api_keys array)"
            )
            sys.exit(1)

        # Paths
        self.base_dir = Path(__file__).parent
        self.pdf_dir = self.base_dir / self.config.get("pdf_dir", "pdf")
        self.json_dir = self.base_dir / self.config.get("json_dir", "json")
        self.db_path = str(self.base_dir / self.config.get("db_path", "research.db"))

        # Create directories
        self.pdf_dir.mkdir(exist_ok=True)
        self.json_dir.mkdir(exist_ok=True)

        # Initialize database
        self.db = Database(self.db_path)
        self.db.reset_stale_processing()

        # Processing state
        self.is_processing = False
        self.should_stop = False
        self.worker_threads = []
        self.workers_lock = threading.Lock()
        self.active_workers_count = 0
        self.active_processing_files = {}
        self.current_pdf = None

        # Build GUI
        self._build_gui()

        # Initial scan
        self.scan_pdfs()

        # Start periodic refresh
        self._schedule_refresh()

    def _build_gui(self):
        """Build the complete GUI."""
        self.root = tk.Tk()
        self.root.title(APP_TITLE)
        self.root.geometry("1200x900")
        self.root.minsize(1000, 700)

        # Configure dark theme colors
        self.bg_color = "#1e1e2e"
        self.fg_color = "#cdd6f4"
        self.accent = "#89b4fa"
        self.accent2 = "#a6e3a1"
        self.warning = "#fab387"
        self.error = "#f38ba8"
        self.surface = "#313244"
        self.overlay = "#45475a"

        self.root.configure(bg=self.bg_color)

        # Configure ttk style
        style = ttk.Style()
        style.theme_use("clam")

        style.configure(".", background=self.bg_color, foreground=self.fg_color,
                         fieldbackground=self.surface, borderwidth=0)
        style.configure("TFrame", background=self.bg_color)
        style.configure("TLabel", background=self.bg_color, foreground=self.fg_color,
                         font=("Segoe UI", 10))
        style.configure("TLabelframe", background=self.bg_color, foreground=self.accent,
                         font=("Segoe UI", 10, "bold"))
        style.configure("TLabelframe.Label", background=self.bg_color,
                         foreground=self.accent, font=("Segoe UI", 10, "bold"))
        style.configure("Header.TLabel", font=("Segoe UI", 14, "bold"),
                         foreground=self.accent)
        style.configure("Status.TLabel", font=("Segoe UI", 10),
                         foreground=self.accent2)
        style.configure("Warning.TLabel", font=("Segoe UI", 10),
                         foreground=self.warning)
        style.configure("Error.TLabel", font=("Segoe UI", 10),
                         foreground=self.error)
        style.configure("Metric.TLabel", font=("Segoe UI", 18, "bold"),
                         foreground=self.accent)
        style.configure("MetricLabel.TLabel", font=("Segoe UI", 9),
                         foreground="#a6adc8")
        style.configure("Accent.TButton", font=("Segoe UI", 10, "bold"))

        style.configure("Treeview", background=self.surface,
                         foreground=self.fg_color, fieldbackground=self.surface,
                         font=("Segoe UI", 9), rowheight=28)
        style.configure("Treeview.Heading", background=self.overlay,
                         foreground=self.accent, font=("Segoe UI", 9, "bold"))
        style.map("Treeview", background=[("selected", self.overlay)])

        style.configure("TProgressbar", troughcolor=self.surface,
                         background=self.accent)

        # ─── Top header ──────────────────────────────────────────
        header_frame = ttk.Frame(self.root, padding=10)
        header_frame.pack(fill=tk.X)

        ttk.Label(header_frame, text=APP_TITLE,
                  style="Header.TLabel").pack(side=tk.LEFT)

        self.status_label = ttk.Label(header_frame, text="Idle",
                                      style="Status.TLabel")
        self.status_label.pack(side=tk.RIGHT)

        # ─── Metrics bar ─────────────────────────────────────────
        metrics_frame = ttk.Frame(self.root, padding=(10, 5))
        metrics_frame.pack(fill=tk.X)

        # Create metric cards
        self.metric_vars = {}
        metrics = [
            ("rpm", "RPM", f"/ {self.rpm_limit}"),
            ("tpm", "TPM (last min)", f"/ {format_number(self.tpm_limit)}"),
            ("rpd", "Requests Today", f"/ {format_number(self.rpd_limit)}"),
            ("tokens_today", "Tokens Today", ""),
            ("total_tokens", "Total Tokens", "all time"),
            ("total_requests", "Total Requests", "all time"),
        ]

        for key, label, suffix in metrics:
            card = tk.Frame(metrics_frame, bg=self.surface, padx=15, pady=8,
                            highlightbackground=self.overlay, highlightthickness=1)
            card.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=3)

            var = tk.StringVar(value="0")
            self.metric_vars[key] = var

            val_label = tk.Label(card, textvariable=var, bg=self.surface,
                                 fg=self.accent, font=("Segoe UI", 16, "bold"))
            val_label.pack()

            desc = f"{label} {suffix}" if suffix else label
            tk.Label(card, text=desc, bg=self.surface, fg="#a6adc8",
                     font=("Segoe UI", 8)).pack()

        # ─── Control buttons ─────────────────────────────────────
        btn_frame = ttk.Frame(self.root, padding=(10, 5))
        btn_frame.pack(fill=tk.X)

        self.start_btn = tk.Button(
            btn_frame, text="Start Processing", command=self.start_processing,
            bg="#a6e3a1", fg="#1e1e2e", font=("Segoe UI", 11, "bold"),
            relief="flat", padx=20, pady=6, cursor="hand2"
        )
        self.start_btn.pack(side=tk.LEFT, padx=5)

        self.stop_btn = tk.Button(
            btn_frame, text="Stop", command=self.stop_processing,
            bg="#f38ba8", fg="#1e1e2e", font=("Segoe UI", 11, "bold"),
            relief="flat", padx=20, pady=6, cursor="hand2", state=tk.DISABLED
        )
        self.stop_btn.pack(side=tk.LEFT, padx=5)

        self.scan_btn = tk.Button(
            btn_frame, text="Scan PDFs", command=self.scan_pdfs,
            bg=self.overlay, fg=self.fg_color, font=("Segoe UI", 10),
            relief="flat", padx=15, pady=6, cursor="hand2"
        )
        self.scan_btn.pack(side=tk.LEFT, padx=5)

        self.retry_btn = tk.Button(
            btn_frame, text="Retry Errors", command=self.retry_errors,
            bg=self.overlay, fg=self.fg_color, font=("Segoe UI", 10),
            relief="flat", padx=15, pady=6, cursor="hand2"
        )
        self.retry_btn.pack(side=tk.LEFT, padx=5)

        # Model info
        model_label = tk.Label(
            btn_frame,
            text=f"Model: {self.config.get('model', 'gemini-2.0-flash')}",
            bg=self.bg_color, fg="#a6adc8", font=("Segoe UI", 9)
        )
        model_label.pack(side=tk.RIGHT, padx=10)

        # ─── Settings panel (collapsible) ─────────────────────────
        self.settings_visible = False
        self.settings_toggle_btn = tk.Button(
            btn_frame, text="Settings", command=self._toggle_settings,
            bg=self.overlay, fg=self.fg_color, font=("Segoe UI", 10),
            relief="flat", padx=15, pady=6, cursor="hand2"
        )
        self.settings_toggle_btn.pack(side=tk.LEFT, padx=5)

        self.settings_frame = tk.Frame(self.root, bg=self.surface,
                                        padx=10, pady=8,
                                        highlightbackground=self.overlay,
                                        highlightthickness=1)
        # Don't pack yet — starts hidden

        proc_cfg = self.config.get("processing", {})
        retry_cfg = self.config.get("retry", {})

        # Row 0: Concurrency & Rate Limit Cap
        row0 = tk.Frame(self.settings_frame, bg=self.surface)
        row0.pack(fill=tk.X, pady=3)

        tk.Label(row0, text="Parallel Processing", bg=self.surface,
                 fg=self.accent, font=("Segoe UI", 10, "bold")).pack(side=tk.LEFT, padx=(0, 15))

        # Concurrent workers
        tk.Label(row0, text="Workers (PDFs at once):", bg=self.surface, fg=self.fg_color,
                 font=("Segoe UI", 9)).pack(side=tk.LEFT, padx=(5, 3))
        self.max_workers_var = tk.IntVar(value=proc_cfg.get("concurrent_workers", 2))
        max_workers_spin = tk.Spinbox(
            row0, from_=1, to=4, width=3, textvariable=self.max_workers_var,
            bg=self.bg_color, fg=self.fg_color, font=("Segoe UI", 9),
            buttonbackground=self.overlay, insertbackground=self.fg_color,
            relief="flat", highlightbackground=self.overlay, highlightthickness=1,
            command=self._save_settings
        )
        max_workers_spin.pack(side=tk.LEFT, padx=(0, 15))

        # Max limit utilization %
        tk.Label(row0, text="Limit Cap (%):", bg=self.surface, fg=self.fg_color,
                 font=("Segoe UI", 9)).pack(side=tk.LEFT, padx=(5, 3))
        self.max_utilization_var = tk.IntVar(value=proc_cfg.get("max_utilization_pct", 80))
        max_utilization_spin = tk.Spinbox(
            row0, from_=30, to=95, increment=5, width=4, textvariable=self.max_utilization_var,
            bg=self.bg_color, fg=self.fg_color, font=("Segoe UI", 9),
            buttonbackground=self.overlay, insertbackground=self.fg_color,
            relief="flat", highlightbackground=self.overlay, highlightthickness=1,
            command=self._save_settings
        )
        max_utilization_spin.pack(side=tk.LEFT, padx=(0, 10))

        tk.Label(row0, text="(waits if RPM/TPM reaches this % of quota)", bg=self.surface,
                 fg="#a6adc8", font=("Segoe UI", 8)).pack(side=tk.LEFT)

        # Row 1: Retry settings
        row1 = tk.Frame(self.settings_frame, bg=self.surface)
        row1.pack(fill=tk.X, pady=3)

        tk.Label(row1, text="Retry & Backoff", bg=self.surface,
                 fg=self.accent, font=("Segoe UI", 10, "bold")).pack(side=tk.LEFT, padx=(0, 15))

        # Max retries
        tk.Label(row1, text="Max Retries:", bg=self.surface, fg=self.fg_color,
                 font=("Segoe UI", 9)).pack(side=tk.LEFT, padx=(5, 3))
        self.max_retries_var = tk.IntVar(value=retry_cfg.get("max_retries", 5))
        max_retries_spin = tk.Spinbox(
            row1, from_=1, to=20, width=4, textvariable=self.max_retries_var,
            bg=self.bg_color, fg=self.fg_color, font=("Segoe UI", 9),
            buttonbackground=self.overlay, insertbackground=self.fg_color,
            relief="flat", highlightbackground=self.overlay, highlightthickness=1,
            command=self._save_settings
        )
        max_retries_spin.pack(side=tk.LEFT, padx=(0, 10))

        # Initial delay
        tk.Label(row1, text="Initial Delay (s):", bg=self.surface,
                 fg=self.fg_color, font=("Segoe UI", 9)).pack(side=tk.LEFT, padx=(5, 3))
        self.initial_delay_var = tk.IntVar(value=retry_cfg.get("initial_delay_seconds", 10))
        initial_delay_spin = tk.Spinbox(
            row1, from_=1, to=300, width=5, textvariable=self.initial_delay_var,
            bg=self.bg_color, fg=self.fg_color, font=("Segoe UI", 9),
            buttonbackground=self.overlay, insertbackground=self.fg_color,
            relief="flat", highlightbackground=self.overlay, highlightthickness=1,
            command=self._save_settings
        )
        initial_delay_spin.pack(side=tk.LEFT, padx=(0, 10))

        # Max delay
        tk.Label(row1, text="Max Delay (s):", bg=self.surface,
                 fg=self.fg_color, font=("Segoe UI", 9)).pack(side=tk.LEFT, padx=(5, 3))
        self.max_delay_var = tk.IntVar(value=retry_cfg.get("max_delay_seconds", 120))
        max_delay_spin = tk.Spinbox(
            row1, from_=10, to=600, width=5, textvariable=self.max_delay_var,
            bg=self.bg_color, fg=self.fg_color, font=("Segoe UI", 9),
            buttonbackground=self.overlay, insertbackground=self.fg_color,
            relief="flat", highlightbackground=self.overlay, highlightthickness=1,
            command=self._save_settings
        )
        max_delay_spin.pack(side=tk.LEFT, padx=(0, 10))

        # Backoff multiplier
        tk.Label(row1, text="Backoff ×:", bg=self.surface,
                 fg=self.fg_color, font=("Segoe UI", 9)).pack(side=tk.LEFT, padx=(5, 3))
        self.backoff_var = tk.DoubleVar(value=retry_cfg.get("backoff_multiplier", 2.0))
        backoff_spin = tk.Spinbox(
            row1, from_=1.0, to=5.0, increment=0.5, width=4,
            textvariable=self.backoff_var, format="%.1f",
            bg=self.bg_color, fg=self.fg_color, font=("Segoe UI", 9),
            buttonbackground=self.overlay, insertbackground=self.fg_color,
            relief="flat", highlightbackground=self.overlay, highlightthickness=1,
            command=self._save_settings
        )
        backoff_spin.pack(side=tk.LEFT, padx=(0, 10))

        # Row 2: Model info
        row2 = tk.Frame(self.settings_frame, bg=self.surface)
        row2.pack(fill=tk.X, pady=2)

        fallbacks = self.config.get("fallback_models", [])
        fallback_str = " → ".join(fallbacks) if fallbacks else "none"
        tk.Label(row2, text=f"Model chain: {self.config.get('model', '?')} → {fallback_str}",
                 bg=self.surface, fg="#a6adc8", font=("Segoe UI", 8)).pack(side=tk.LEFT)

        # Bind spinbox keyboard events to save too
        all_spins = [max_workers_spin, max_utilization_spin, max_retries_spin,
                     initial_delay_spin, max_delay_spin, backoff_spin]
        for spin in all_spins:
            spin.bind("<Return>", lambda e: self._save_settings())
            spin.bind("<FocusOut>", lambda e: self._save_settings())

        # ─── Progress bar ────────────────────────────────────────
        prog_frame = ttk.Frame(self.root, padding=(10, 2))
        prog_frame.pack(fill=tk.X)

        self.progress_var = tk.DoubleVar(value=0)
        self.progress_bar = ttk.Progressbar(
            prog_frame, variable=self.progress_var, maximum=100, mode="determinate"
        )
        self.progress_bar.pack(fill=tk.X)

        self.progress_label = ttk.Label(prog_frame, text="", style="Status.TLabel")
        self.progress_label.pack(anchor=tk.W)

        # ─── Main content: Treeview + Log ─────────────────────────
        paned = ttk.PanedWindow(self.root, orient=tk.VERTICAL)
        paned.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        # PDF List (Treeview)
        tree_frame = ttk.LabelFrame(paned, text="PDF Files", padding=5)
        paned.add(tree_frame, weight=2)

        columns = ("status", "file_name", "tokens", "json_path", "updated")
        self.tree = ttk.Treeview(tree_frame, columns=columns, show="headings",
                                  selectmode="browse")

        self.tree.heading("status", text="Status")
        self.tree.heading("file_name", text="File Name")
        self.tree.heading("tokens", text="Tokens Used")
        self.tree.heading("json_path", text="JSON Output")
        self.tree.heading("updated", text="Last Updated")

        self.tree.column("status", width=100, minwidth=80)
        self.tree.column("file_name", width=300, minwidth=200)
        self.tree.column("tokens", width=100, minwidth=80)
        self.tree.column("json_path", width=300, minwidth=150)
        self.tree.column("updated", width=160, minwidth=120)

        tree_scroll = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL,
                                     command=self.tree.yview)
        self.tree.configure(yscrollcommand=tree_scroll.set)

        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        tree_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        # Log area
        log_frame = ttk.LabelFrame(paned, text="Processing Log", padding=5)
        paned.add(log_frame, weight=1)

        self.log_text = scrolledtext.ScrolledText(
            log_frame, wrap=tk.WORD, height=12,
            bg=self.surface, fg=self.fg_color,
            font=("Consolas", 9), insertbackground=self.fg_color,
            selectbackground=self.overlay, relief="flat", borderwidth=0
        )
        self.log_text.pack(fill=tk.BOTH, expand=True)

        # ─── Bottom status bar ───────────────────────────────────
        status_bar = tk.Frame(self.root, bg=self.overlay, height=28)
        status_bar.pack(fill=tk.X, side=tk.BOTTOM)
        status_bar.pack_propagate(False)

        self.bottom_status = tk.Label(
            status_bar,
            text=f"PDF: {self.pdf_dir}  |  JSON: {self.json_dir}  |  "
                 f"DB: {self.db_path}",
            bg=self.overlay, fg="#a6adc8", font=("Segoe UI", 8),
            anchor=tk.W, padx=10
        )
        self.bottom_status.pack(fill=tk.X, expand=True)

        # Handle window close
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ─── Settings Panel ───────────────────────────────────────────────────────

    def _toggle_settings(self):
        """Toggle the settings panel visibility."""
        if self.settings_visible:
            self.settings_frame.pack_forget()
            self.settings_toggle_btn.config(text="Settings")
            self.settings_visible = False
        else:
            # Insert settings_frame after the button row (before progress bar)
            # We need to position it correctly in the pack order
            self.settings_frame.pack(fill=tk.X, padx=10, pady=(0, 2),
                                      before=self.progress_bar.master)
            self.settings_toggle_btn.config(text="Hide Settings")
            self.settings_visible = True

    def _save_settings(self):
        """Save retry and processing settings from GUI to config.json and update in-memory config."""
        try:
            new_retry = {
                "max_retries": self.max_retries_var.get(),
                "initial_delay_seconds": self.initial_delay_var.get(),
                "max_delay_seconds": self.max_delay_var.get(),
                "backoff_multiplier": self.backoff_var.get(),
            }
            new_processing = {
                "concurrent_workers": self.max_workers_var.get(),
                "max_utilization_pct": self.max_utilization_var.get(),
            }
        except (tk.TclError, ValueError):
            return  # Invalid input, ignore

        # Update in-memory config
        self.config["retry"] = new_retry
        self.config["processing"] = new_processing

        # Save to file
        config_path = self.base_dir / CONFIG_FILE
        try:
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(self.config, f, indent=4, ensure_ascii=False)
        except Exception as e:
            self.log(f"Failed to save config: {e}", "error")

    _save_retry_settings = _save_settings

    # ─── Logging ──────────────────────────────────────────────────────────────

    def log(self, message: str, level: str = "info"):
        """Add a message to the log area."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        prefix = {"info": "[INFO]", "success": "[OK]", "warning": "[WARN]",
                  "error": "[HIBA]", "processing": "[RUN]"}.get(level, "•")

        self.root.after(0, self._append_log, f"[{timestamp}] {prefix} {message}\n")

    def _append_log(self, text: str):
        """Thread-safe log append."""
        self.log_text.insert(tk.END, text)
        self.log_text.see(tk.END)

    # ─── PDF Scanning ─────────────────────────────────────────────────────────

    def scan_pdfs(self):
        """Scan the PDF directory and quickly register new PDFs by filename only (no upfront hashing)."""
        pdf_files = list(self.pdf_dir.glob("*.pdf"))

        # Fast bulk comparison against existing database records
        existing_names = self.db.get_existing_file_names()
        new_items = [(p.name, str(p)) for p in pdf_files if p.name not in existing_names]

        new_count = self.db.add_pdfs_batch(new_items) if new_items else 0
        self.log(f"Scanned {len(pdf_files)} PDF(s). {new_count} new file(s) found.",
                 "info" if new_count == 0 else "success")

        self._refresh_tree()

    # ─── Tree Refresh ─────────────────────────────────────────────────────────

    def _refresh_tree(self):
        """Refresh the PDF treeview from database."""
        # Clear existing items
        self.tree.delete(*self.tree.get_children())
        self._tree_items = {}

        # Load from DB
        pdfs = self.db.get_all_pdfs()
        for pdf in pdfs:
            status = pdf["status"]
            status_icon = {
                "pending": "Pending",
                "processing": "Processing",
                "completed": "Done",
                "error": "Error"
            }.get(status, status)

            json_display = ""
            if pdf.get("json_path"):
                json_display = Path(pdf["json_path"]).name

            tokens = format_number(pdf.get("tokens_used", 0)) if pdf.get("tokens_used") else ""

            updated = ""
            if pdf.get("updated_at"):
                try:
                    dt = datetime.fromisoformat(pdf["updated_at"])
                    updated = dt.strftime("%Y-%m-%d %H:%M")
                except (ValueError, TypeError):
                    updated = pdf["updated_at"][:16]

            item_id = self.tree.insert("", tk.END, values=(
                status_icon, pdf["file_name"], tokens, json_display, updated
            ))
            self._tree_items[pdf["file_name"]] = item_id

    def _update_tree_item(self, file_name: str, status: str, tokens: str = "", json_name: str = ""):
        """Quickly update status of a single row in the treeview without full reload."""
        if hasattr(self, "_tree_items") and file_name in self._tree_items:
            item_id = self._tree_items[file_name]
            status_icon = {
                "pending": "Pending",
                "processing": "Processing",
                "completed": "Done",
                "error": "Error"
            }.get(status, status)
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
            old_vals = list(self.tree.item(item_id, "values"))
            if len(old_vals) >= 5:
                old_vals[0] = status_icon
                if tokens:
                    old_vals[2] = tokens
                if json_name:
                    old_vals[3] = json_name
                old_vals[4] = now_str
                self.tree.item(item_id, values=old_vals)

    # ─── Metrics Refresh ──────────────────────────────────────────────────────

    def _refresh_metrics(self):
        """Refresh the API usage metrics display."""
        usage = self.db.get_usage_summary()

        self.metric_vars["rpm"].set(str(usage["rpm_current"]))
        self.metric_vars["tpm"].set(format_number(usage["tpm_current"]))
        self.metric_vars["rpd"].set(format_number(usage["rpd_current"]))
        self.metric_vars["tokens_today"].set(format_number(usage["tokens_today"]))
        self.metric_vars["total_tokens"].set(format_number(usage["total_tokens"]))
        self.metric_vars["total_requests"].set(format_number(usage["total_requests"]))

    def _schedule_refresh(self):
        """Schedule periodic GUI refresh."""
        self._refresh_metrics()

        # Only reload entire tree when marked dirty (not every second)
        if getattr(self, "_tree_dirty", False):
            self._tree_dirty = False
            self._refresh_tree()

        if self.is_processing:
            stats = self.db.get_stats()
            total = stats["total"]
            done = stats["completed"]
            if total > 0:
                pct = (done / total) * 100
                self.progress_var.set(pct)
                self.progress_label.config(
                    text=f"{done}/{total} completed ({pct:.0f}%) "
                         f"| {stats['pending']} pending | {stats['errors']} errors"
                )

        self.root.after(REFRESH_INTERVAL_MS, self._schedule_refresh)

    # ─── Processing Control ──────────────────────────────────────────────────

    def start_processing(self):
        """Start processing pending PDFs with concurrent workers."""
        if self.is_processing:
            return

        # Rescan for new PDFs
        self.scan_pdfs()

        pending = self.db.get_pending_pdfs()
        if not pending:
            self.log("No pending PDFs to process.", "info")
            messagebox.showinfo("Info", "No pending PDFs to process.\n"
                                "Add PDF files to the 'pdf' folder and click 'Scan PDFs'.")
            return

        num_workers = max(1, self.max_workers_var.get())
        cap_pct = self.max_utilization_var.get()

        self.is_processing = True
        self.should_stop = False
        self.start_btn.config(state=tk.DISABLED)
        self.stop_btn.config(state=tk.NORMAL)
        self.status_label.config(text=f"Processing with {num_workers} worker(s)...", style="Warning.TLabel")

        self.log(f"Starting processing. {len(pending)} PDF(s) in queue. Parallel workers: {num_workers}, Rate cap: {cap_pct}%.", "processing")

        self.worker_threads = []
        with self.workers_lock:
            self.active_workers_count = num_workers
            self.active_processing_files.clear()

        for worker_id in range(1, num_workers + 1):
            t = threading.Thread(
                target=self._worker_loop, args=(worker_id,), daemon=True
            )
            self.worker_threads.append(t)
            t.start()

    def stop_processing(self):
        """Signal all worker threads to stop."""
        if not self.is_processing:
            return

        self.should_stop = True
        self.log("Stop requested. Active workers will finish their current PDF and stop.", "warning")
        self.status_label.config(text="Stopping workers...", style="Warning.TLabel")

    def _worker_loop(self, worker_id: int):
        """Worker loop running in background thread."""
        retry_cfg = self.config.get("retry", {})
        try:
            analyzer = GeminiAnalyzer(
                api_key=self.api_key,
                model_name=self.config.get("model", "gemini-2.0-flash"),
                fallback_models=self.config.get("fallback_models", []),
                max_retries=retry_cfg.get("max_retries", 5),
                initial_delay=retry_cfg.get("initial_delay_seconds", 10),
                max_delay=retry_cfg.get("max_delay_seconds", 120),
                backoff_multiplier=retry_cfg.get("backoff_multiplier", 2),
            )
        except Exception as e:
            self.log(f"[W{worker_id}] Failed to initialize Gemini client: {e}", "error")
            with self.workers_lock:
                self.active_workers_count -= 1
                if self.active_workers_count == 0:
                    self.root.after(0, self._processing_finished)
            return

        while not self.should_stop:
            try:
                # Atomically claim the next pending PDF
                pdf_info = self.db.claim_next_pending_pdf()
                if not pdf_info:
                    # No more pending PDFs
                    break

                file_name = pdf_info["file_name"]
                file_path = pdf_info["file_path"]

                with self.workers_lock:
                    self.active_processing_files[worker_id] = file_name
                    active_list = list(self.active_processing_files.values())

                self.root.after(0, lambda fn=file_name: self._update_tree_item(fn, "processing"))
                self.root.after(0, lambda al=active_list:
                                self.status_label.config(
                                    text=f"Processing ({len(al)}): {', '.join(al[:3])}{'...' if len(al) > 3 else ''}",
                                    style="Warning.TLabel"))

                # Check if file still exists
                if not Path(file_path).exists():
                    self.log(f"[W{worker_id}] File not found: {file_name}. Skipping.", "error")
                    self.db.update_pdf_status(file_name, "error", error_message="File not found")
                    self.root.after(0, lambda fn=file_name: self._update_tree_item(fn, "error"))
                    with self.workers_lock:
                        self.active_processing_files.pop(worker_id, None)
                    continue

                try:
                    self._process_single_pdf(analyzer, file_name, file_path, worker_id)
                except InterruptedError:
                    self.log(f"[W{worker_id}] Processing interrupted for {file_name}. Will resume later.", "warning")
                    self.db.update_pdf_status(file_name, "pending")
                    self.root.after(0, lambda fn=file_name: self._update_tree_item(fn, "pending"))
                    with self.workers_lock:
                        self.active_processing_files.pop(worker_id, None)
                    break
                except Exception as e:
                    self.log(f"[W{worker_id}] Error processing {file_name}: {e}", "error")
                    self.db.update_pdf_status(file_name, "error", error_message=str(e)[:500])
                    self.root.after(0, lambda fn=file_name: self._update_tree_item(fn, "error"))

                with self.workers_lock:
                    self.active_processing_files.pop(worker_id, None)

            except Exception as loop_err:
                self.log(f"[W{worker_id}] Worker loop error: {loop_err}", "warning")
                with self.workers_lock:
                    self.active_processing_files.pop(worker_id, None)
                time.sleep(1)

        with self.workers_lock:
            self.active_workers_count -= 1
            is_last = (self.active_workers_count <= 0)

        if is_last:
            self.log("All active workers finished.", "success")
            self.root.after(0, self._processing_finished)

    def _process_single_pdf(self, analyzer: GeminiAnalyzer,
                            file_name: str, file_path: str, worker_id: int):
        """Process a single PDF file with designated worker."""
        self.log(f"[W{worker_id}] Processing: {file_name}", "processing")
        self.db.update_pdf_status(file_name, "processing")
        self.root.after(0, lambda fn=file_name: self._update_tree_item(fn, "processing"))

        # Step 1: Extract PDF content (computes file_hash only for this current file)
        self.log(f"[W{worker_id}]   Extracting text and tables from {file_name}...", "info")
        pdf_data = PDFProcessor.process_pdf(file_path)
        self.log(f"[W{worker_id}]   Extracted {pdf_data['text_length']:,} chars, "
                 f"{len(pdf_data['tables'])} tables, "
                 f"{pdf_data['images_count']} images.", "info")

        # Step 2: Check rate limits and wait if needed (enforces limit utilization cap, e.g. 80%)
        estimated_tokens = PDFProcessor.estimate_token_count(pdf_data["full_text"])
        self._wait_for_rate_limit(estimated_tokens, worker_id)

        if self.should_stop:
            self.db.update_pdf_status(file_name, "pending")
            self.root.after(0, lambda fn=file_name: self._update_tree_item(fn, "pending"))
            return

        # Step 3: Send to Gemini (with retry + fallback)
        self.log(f"[W{worker_id}]   Sending to Gemini API...", "processing")
        result, prompt_tok, completion_tok, total_tok = analyzer.analyze_paper(
            pdf_data,
            on_status=lambda msg: self.log(f"[W{worker_id}]   {msg}", "info"),
            should_stop=lambda: self.should_stop,
        )

        # Step 4: Log API usage
        self.db.log_api_call(
            pdf_file_name=file_name,
            prompt_tokens=prompt_tok,
            completion_tokens=completion_tok,
            total_tokens=total_tok,
            model=self.config.get("model", "gemini-2.0-flash"),
            success=True,
            api_key_id=self.api_key_id
        )

        # Step 5: Save JSON
        json_filename = Path(file_name).stem + ".json"
        json_path = str(self.json_dir / json_filename)

        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)

        # Step 6: Update database with status, tokens, json path, and file hash
        file_hash = pdf_data.get("file_hash")
        self.db.update_pdf_status(
            file_name, "completed",
            json_path=json_path,
            tokens_used=total_tok,
            file_hash=file_hash
        )

        self.root.after(0, lambda fn=file_name, tok=format_number(total_tok), jf=json_filename:
                        self._update_tree_item(fn, "completed", tok, jf))

        self.log(f"[W{worker_id}]   Completed: {file_name} → {json_filename} "
                 f"({format_number(total_tok)} tokens)", "success")

    def _wait_for_rate_limit(self, estimated_tokens: int, worker_id: int):
        """Wait until rate limits allow the next API call (capped at max_utilization_var %)."""
        utilization_cap = max(0.1, min(1.0, self.max_utilization_var.get() / 100.0))

        while not self.should_stop:
            can_proceed, reason, wait_seconds = self.db.can_make_request(
                self.rpm_limit, self.tpm_limit, self.rpd_limit,
                estimated_tokens=estimated_tokens,
                max_utilization_pct=utilization_cap,
                api_key_id=self.api_key_id
            )

            if can_proceed:
                return

            self.log(f"[W{worker_id}] Rate limit gate ({int(utilization_cap*100)}% cap): {reason}. Waiting {wait_seconds:.0f}s...", "warning")
            self.root.after(0, lambda r=reason:
                            self.status_label.config(
                                text=f"Rate limit gate: {r}",
                                style="Warning.TLabel"))

            wait_end = time.time() + wait_seconds
            while time.time() < wait_end and not self.should_stop:
                time.sleep(0.5)

    def _processing_finished(self):
        """Called when all worker loops end."""
        self.is_processing = False
        self.should_stop = False
        self.start_btn.config(state=tk.NORMAL)
        self.stop_btn.config(state=tk.DISABLED)
        self.status_label.config(text="Idle", style="Status.TLabel")
        self._refresh_tree()
        self._refresh_metrics()

        stats = self.db.get_stats()
        self.progress_label.config(
            text=f"Done. {stats['completed']}/{stats['total']} completed, "
                 f"{stats['errors']} errors."
        )

    # ─── Retry Errors ─────────────────────────────────────────────────────────

    def retry_errors(self):
        """Reset all error PDFs back to pending."""
        with self.db.lock:
            self.db.conn.execute(
                """UPDATE pdfs SET status = 'pending', error_message = NULL,
                   updated_at = ? WHERE status = 'error'""",
                (datetime.now(timezone.utc).isoformat(),)
            )
            self.db.conn.commit()
        self._refresh_tree()
        self.log("All errored PDFs reset to pending.", "info")

    # ─── Window Close ─────────────────────────────────────────────────────────

    def _on_close(self):
        """Handle window close event."""
        if self.is_processing:
            if messagebox.askyesno(
                "Processing in Progress",
                "Processing is still running. Stop and exit?"
            ):
                self.should_stop = True
                for t in getattr(self, "worker_threads", []):
                    if t and t.is_alive():
                        t.join(timeout=1.5)
                self.db.reset_stale_processing()
                self.db.close()
                self.root.destroy()
        else:
            self.db.close()
            self.root.destroy()

    def run(self):
        """Start the application main loop."""
        self.log("Application started. Add PDFs to the 'pdf' folder and click "
                 "'Start Processing'.", "info")
        self.root.mainloop()


# ─── Entry Point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app = App()
    app.run()
