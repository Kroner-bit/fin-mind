"""
PDF text, table, and structure extraction using PyMuPDF and pdfplumber.

Extraction upgrade (v2) — same public interface and output shapes as v1:

full_text (same "--- PAGE N ---" page-marker format), now with:
  - sub/superscript reconstruction from font geometry: X_t -> X_{t},
    10^4 -> 10^{4}, E[S^2_t] -> E[S^{2}_{t}]
  - reading order fixed: blocks stay in stream order (two-column safe),
    lines y-sorted only within their block
  - rotated arXiv watermark relocated to a clean line at the top of page 1
  - running headers/footers and bare page numbers stripped (pages 2+)
  - ligature expansion (fi/fl/...) and hyphenation repair (word-\\nword)
  - authoritative arXiv metadata header line (read-only lookup in
    arxiv_collector/data/papers.db) so identity/date come from the
    arXiv API record, not from LLM inference on body text

tables (same output dicts: page, table_index, headers, rows, raw), now with:
  - caption-anchored extraction ("Table N." / Roman numerals) using a
    layout/text strategy that works on borderless LaTeX tables
  - quality filtering that drops figure-fragment / empty / paragraph
    false positives
  - caption and bbox recorded when known

pdf_metadata (same keys), now enriched with authoritative arXiv fields
  (arxiv_id, arxiv_title, arxiv_authors, arxiv_published, arxiv_updated,
  arxiv_categories) and fallback-filled title/author/creation_date.
"""

import fitz  # PyMuPDF
import pdfplumber
import hashlib
import json
import re
import sqlite3
import statistics
import threading
import urllib.parse
from pathlib import Path

# Suppress harmless MuPDF syntax warnings for non-standard PDF streams (pagesize, unknown keywords, color space)
try:
    fitz.TOOLS.mupdf_display_errors(False)
except Exception:
    pass


# ─── Constants ────────────────────────────────────────────────────────────────

_LIGATURES = {
    "\ufb00": "ff", "\ufb01": "fi", "\ufb02": "fl", "\ufb03": "ffi",
    "\ufb04": "ffl", "\ufb05": "st", "\ufb06": "st",
}

# characters that indicate a text row is (part of) a displayed equation;
# such rows are never dehyphenated/merged across lines
_MATHY_CHARS = "=∫∑∏√∞±×÷≤≥∈∩∪∂∇⇒∝∼≈"

# running header/footer detection
_ZONE_PT = 72.0            # rows starting above this (or ending below page_height - this) are in the running-head zone
_STRIP_MIN_PAGES = 3       # never strip anything in documents with fewer pages than this
_STRIP_PAGE_FRAC = 0.30    # a zone signature must repeat on this fraction of pages to be stripped

# table caption detection (strict: number followed by punctuation or end of line)
_TABLE_CAPTION_RE = re.compile(
    r"^(?:Table|Tab\.|TABLE)\s*(?:[A-Z]?\d{1,3}|[IVXLCDM]{1,7})\s*(?:[.:]|$)",
    re.IGNORECASE,
)
_FIG_CAPTION_RE = re.compile(
    r"^(?:Figure|Fig\.|FIG\.|FIG)\s*(?:[A-Z]?\d{1,3}|[IVXLCDM]{1,7})\b",
    re.IGNORECASE,
)

# cells that count as numeric for table quality filtering
_NUMERIC_CHARS = set("0123456789.,-+±%*()")

_TEXT_TABLE_SETTINGS = {
    "vertical_strategy": "text",
    "horizontal_strategy": "text",
    "intersection_tolerance": 5,
}

# arXiv watermark pattern (rotated sidebar text)
_ARXIV_WM_RE = re.compile(r"arXiv[:\s]", re.IGNORECASE)

# authoritative arXiv metadata (read-only, loaded once per process)
_ARXIV_DB_PATH = (Path(__file__).resolve().parent.parent / "arxiv_collector" / "data" / "papers.db"
                  if (Path(__file__).resolve().parent.parent / "arxiv_collector" / "data" / "papers.db").exists()
                  else Path(__file__).resolve().parent / "arxiv_collector" / "data" / "papers.db")
_ARXIV_LOCK = threading.Lock()
_ARXIV_CACHE_SENTINEL = "not_loaded"
_arxiv_by_id = _ARXIV_CACHE_SENTINEL


def _expand_ligatures(text: str) -> str:
    for src, dst in _LIGATURES.items():
        if src in text:
            text = text.replace(src, dst)
    return text


def _is_mathy(text: str) -> bool:
    if any(ch in text for ch in _MATHY_CHARS):
        return True
    return "_{" in text or "^{" in text


def _zone_signature(text: str) -> str:
    return re.sub(r"[^a-z]", "", text.lower())


class PDFProcessor:
    """Extracts text, tables, metadata, and structural info from PDFs."""

    @staticmethod
    def compute_file_hash(file_path: str) -> str:
        """Compute SHA-256 hash of a file for change detection."""
        sha256 = hashlib.sha256()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                sha256.update(chunk)
        return sha256.hexdigest()

    # ─── arXiv metadata authority (read-only) ────────────────────────────────

    @classmethod
    def _load_arxiv_db(cls):
        """Load {arxiv_id: record} from the collector's papers.db (read-only)."""
        try:
            uri = "file:" + urllib.parse.quote(str(_ARXIV_DB_PATH).replace("\\", "/")) + "?mode=ro"
            conn = sqlite3.connect(uri, uri=True)
            cur = conn.cursor()
            cur.execute("SELECT arxiv_id, title, authors, published, updated, categories FROM papers")
            by_id = {}
            for aid, title, authors, published, updated, categories in cur.fetchall():
                try:
                    authors_list = json.loads(authors) if authors else []
                    if not isinstance(authors_list, list):
                        authors_list = [str(authors)]
                except Exception:
                    authors_list = [str(authors)] if authors else []
                try:
                    cats = json.loads(categories) if categories else []
                    if not isinstance(cats, list):
                        cats = [str(categories)]
                except Exception:
                    cats = [str(categories)] if categories else []
                by_id[str(aid)] = {
                    "arxiv_id": str(aid),
                    "title": (title or "").strip(),
                    "authors": [str(a).strip() for a in authors_list if str(a).strip()],
                    "published": (published or ""),
                    "updated": (updated or ""),
                    "categories": [str(c) for c in cats if str(c).strip()],
                }
            conn.close()
            return by_id
        except Exception:
            return False  # unavailable: fall back to v1 behavior silently

    @classmethod
    def _lookup_arxiv(cls, stem: str):
        """Authoritative arXiv metadata for a PDF filename stem, or None."""
        global _arxiv_by_id
        with _ARXIV_LOCK:
            if _arxiv_by_id is _ARXIV_CACHE_SENTINEL:
                _arxiv_by_id = cls._load_arxiv_db()
            table = _arxiv_by_id
        if not table:
            return None
        m = re.match(r"^([a-z-]+)_(\d{7})$", stem, re.IGNORECASE)
        key = f"{m.group(1)}/{m.group(2)}" if m else stem
        hit = table.get(key) or table.get(stem)
        return hit or None

    # ─── Row-level text extraction ─────────────────────────────────────────

    @staticmethod
    def _page_rows(page):
        """
        One PDF page -> (rows, watermarks, rotated_other).

        rows: list of dicts {text, x0, y0, y1} in reading order
              (blocks in stream order = two-column safe; lines y-sorted
              within their block; small sub/superscript fragments merged
              back into their parent row with _{...} / ^{...} markers).
        watermarks: rotated lines matching the arXiv pattern.
        rotated_other: any other rotated text (e.g. figure axis labels).
        """
        rows, watermarks, rotated_other = [], [], []
        try:
            d = page.get_text("dict")
        except Exception:
            text = page.get_text("text")
            if text.strip():
                rows = [{"text": t, "x0": 0.0, "y0": 0.0, "y1": 0.0}
                        for t in text.split("\n") if t.strip()]
            return rows, watermarks, rotated_other

        pw, ph = page.rect.width, page.rect.height
        for block in d["blocks"]:
            if block.get("type") != 0:
                continue
            block_lines = []
            for line in block["lines"]:
                spans = []
                for s in line["spans"]:
                    txt = _expand_ligatures(s.get("text") or "")
                    if txt:
                        spans.append({**s, "text": txt})
                if not any(s["text"].strip() for s in spans):
                    continue
                entry = {
                    "bbox": line["bbox"], "dir": line.get("dir", (1, 0)),
                    "spans": spans, "size": max(s["size"] for s in spans),
                }
                if entry["dir"] != (1, 0):
                    txt = "".join(s["text"] for s in spans).strip()
                    if _ARXIV_WM_RE.search(txt):
                        watermarks.append(txt)
                    else:
                        rotated_other.append(txt)
                else:
                    block_lines.append(entry)
            if not block_lines:
                continue

            # merge small sub/superscript fragment lines into the base line
            # they overlap (same block only -> never mixes columns)
            max_size = max(l["size"] for l in block_lines)
            bases = [l for l in block_lines if l["size"] >= 0.85 * max_size]
            frags = [l for l in block_lines if l not in bases]
            for fr in frags:
                best, best_ov = None, 0
                for b in bases:
                    x_ov = min(fr["bbox"][2], b["bbox"][2]) - max(fr["bbox"][0], b["bbox"][0])
                    y_ov = min(fr["bbox"][3], b["bbox"][3]) - max(fr["bbox"][1], b["bbox"][1])
                    fh = fr["bbox"][3] - fr["bbox"][1]
                    if x_ov > 0 and y_ov > 0.25 * fh and x_ov > best_ov:
                        best, best_ov = b, x_ov
                if best is None:
                    bases.append(fr)          # standalone small line (e.g. eq. number)
                else:
                    best.setdefault("frags", []).append(fr)

            bases.sort(key=lambda e: (e["bbox"][1], e["bbox"][0]))
            for ln in bases:
                text = PDFProcessor._render_row(ln, ln["size"])
                if text.strip():
                    rows.append({
                        "text": text,
                        "x0": ln["bbox"][0], "y0": ln["bbox"][1], "y1": ln["bbox"][3],
                    })
        return rows, watermarks, rotated_other

    @staticmethod
    def _render_row(ln, base_size):
        """Concatenate a row's spans (parent line + merged fragments), marking
        sub/superscripts relative to the nearest preceding non-space base span."""
        spans = list(ln["spans"]) + [s for fr in ln.get("frags", []) for s in fr["spans"]]
        spans.sort(key=lambda s: (round(s["bbox"][0], 1), s["origin"][1]))
        body = [s for s in spans if s["size"] >= 0.88 * base_size and s["text"].strip()]
        fallback_y = statistics.median([s["origin"][1] for s in body]) if body else spans[0]["origin"][1]
        parts, prev_end, prev_cls, last_base_y = [], None, None, None
        for idx, s in enumerate(spans):
            cls = "base"
            if s["size"] < 0.88 * base_size:
                parent_y = last_base_y
                if parent_y is None:
                    nxt = [x for x in spans[idx + 1:] if x["size"] >= 0.88 * base_size and x["text"].strip()]
                    parent_y = nxt[0]["origin"][1] if nxt else fallback_y
                dy = s["origin"][1] - parent_y
                if dy < -0.1 * s["size"]:
                    cls = "sup"
                elif dy > 0.1 * s["size"]:
                    cls = "sub"
                elif s.get("flags", 0) & 1 and dy <= 0.15 * s["size"]:
                    cls = "sup"  # MuPDF superscript flag with ~unchanged baseline
            txt = s["text"]
            if not txt:
                continue
            if prev_end is None:
                if cls != "base":
                    parts.append("_{" if cls == "sub" else "^{")
                parts.append(txt)
            else:
                gap = s["bbox"][0] - prev_end
                sep = " " if gap > 0.25 * s["size"] else ""
                if cls != "base" and cls == prev_cls and gap < 1.5 * s["size"]:
                    parts.append(txt)  # continue the same _{...}/^{...} run
                else:
                    if prev_cls != "base":
                        parts.append("}")
                    if sep:
                        parts.append(" ")
                    if cls != "base":
                        parts.append("_{" if cls == "sub" else "^{")
                    parts.append(txt)
            if cls == "base" and s["text"].strip():
                last_base_y = s["origin"][1]
            prev_cls, prev_end = cls, s["bbox"][2]
        if prev_cls != "base":
            parts.append("}")
        return "".join(parts)

    # ─── Running header / footer stripping ──────────────────────────────────

    @staticmethod
    def _detect_running_heads(pages_rows, page_heights):
        """Signatures (zone, sig) to strip: repeated in the same zone on enough pages."""
        n_pages = len(pages_rows)
        to_strip = set()
        if n_pages < _STRIP_MIN_PAGES:
            return to_strip, set()
        threshold = max(_STRIP_MIN_PAGES, int(_STRIP_PAGE_FRAC * n_pages))
        sig_counts, bare_counts = {}, {}
        for pno in range(1, n_pages):
            rows = pages_rows[pno][0]
            ph = page_heights[pno]
            zone_rows = []
            nonempty = [r for r in rows if r["text"].strip()]
            for r in nonempty[:2]:
                if r["y0"] < _ZONE_PT:
                    zone_rows.append(("top", r))
            for r in nonempty[-2:]:
                if r["y1"] > ph - _ZONE_PT:
                    zone_rows.append(("bottom", r))
            seen_sigs, seen_bare = set(), set()
            for zone, r in zone_rows:
                text = r["text"].strip()
                if re.fullmatch(r"[\d]{1,4}[.·]?", text):
                    if zone not in seen_bare:
                        bare_counts[zone] = bare_counts.get(zone, 0) + 1
                        seen_bare.add(zone)
                    continue
                sig = _zone_signature(text)
                if not sig:
                    continue
                k = (zone, sig)
                if k not in seen_sigs:
                    sig_counts[k] = sig_counts.get(k, 0) + 1
                    seen_sigs.add(k)
        for k, c in sig_counts.items():
            if c >= threshold:
                to_strip.add(k)
        bare_zones = {z for z, c in bare_counts.items() if c >= threshold}
        return to_strip, bare_zones

    # ─── Full text ──────────────────────────────────────────────────────────

    @staticmethod
    def extract_full_text(file_path: str) -> str:
        """Extract all text from the PDF (same page-marker format as v1)."""
        stem = Path(file_path).stem
        arxiv = PDFProcessor._lookup_arxiv(stem)

        doc = fitz.open(file_path)
        pages_rows, page_heights = [], []
        for page in doc:
            rows, wm, rot = PDFProcessor._page_rows(page)
            pages_rows.append((rows, wm, rot))
            page_heights.append(page.rect.height)
        doc.close()

        to_strip, bare_zones = PDFProcessor._detect_running_heads(pages_rows, page_heights)

        text_parts = []
        n_pages = len(pages_rows)
        for pno, (rows, wm, rot) in enumerate(pages_rows):
            if pno > 0:
                ph = page_heights[pno]
                kept = []
                nonempty = [r for r in rows if r["text"].strip()]
                for r in nonempty:
                    zone = None
                    if r["y0"] < _ZONE_PT:
                        zone = "top"
                    elif r["y1"] > ph - _ZONE_PT:
                        zone = "bottom"
                    if zone is not None:
                        text = r["text"].strip()
                        if re.fullmatch(r"[\d]{1,4}[.·]?", text) and zone in bare_zones:
                            continue  # bare page number
                        if (zone, _zone_signature(text)) in to_strip:
                            continue  # repeated running head/foot
                    kept.append(r)
                rows = kept

            # join rows, repairing hyphenated line breaks (never inside math)
            lines = []
            for r in rows:
                t = r["text"].rstrip()
                if lines and t:
                    prev = lines[-1]
                    if (re.search(r"[a-z]$", prev[:-1]) and prev.endswith("-")
                            and re.match(r"[a-z]", t)
                            and len(prev) >= 20
                            and not _is_mathy(prev) and not _is_mathy(t)):
                        lines[-1] = prev[:-1] + t
                        continue
                lines.append(t)
            while lines and not lines[-1].strip():
                lines.pop()

            page_lines = []
            if pno == 0:
                if arxiv:
                    cats = "; ".join(arxiv["categories"])
                    title = arxiv["title"][:180]
                    authors = ", ".join(arxiv["authors"])[:200]
                    page_lines.append(
                        "[ARXIV METADATA] "
                        f"arXiv:{arxiv['arxiv_id']} | "
                        f"published: {arxiv['published'][:10]} | "
                        f"updated: {arxiv['updated'][:10]} | "
                        f"categories: {cats} | title: {title} | authors: {authors}"
                    )
                for w in wm:
                    page_lines.append(w)
            page_lines.extend(lines)
            page_lines.extend(rot)

            page_text = "\n".join(x for x in page_lines if x.strip())
            if page_text.strip():
                text_parts.append(f"\n--- PAGE {pno + 1} ---\n{page_text}")
        return "\n".join(text_parts)

    # ─── Tables ─────────────────────────────────────────────────────────────

    @staticmethod
    def _clean_table_cells(table):
        """v1-compatible cell cleaning; drops empty rows/columns."""
        if not table:
            return []
        cleaned = []
        for row in table:
            if row is None:
                continue
            cleaned.append([
                ("" if c is None else str(c).strip().replace("\n", " ")) for c in row
            ])
        if not cleaned:
            return []
        n_cols = max(len(r) for r in cleaned)
        cleaned = [r + [""] * (n_cols - len(r)) for r in cleaned]
        keep_cols = [j for j in range(n_cols) if any(r[j] for r in cleaned)]
        cleaned = [[r[j] for j in keep_cols] for r in cleaned]
        cleaned = [r for r in cleaned if any(r)]
        return cleaned

    @staticmethod
    def _is_numeric_cell(cell: str) -> bool:
        s = cell.replace(" ", "")
        if not s or not any(ch.isdigit() for ch in s):
            return False
        core = "".join(ch for ch in s if ch in _NUMERIC_CHARS)
        return len(core) >= 0.8 * len(s)

    @staticmethod
    def _table_ok(rows) -> bool:
        """Quality gate: rejects figure fragments, empty grids, text walls."""
        if not rows or len(rows) < 3:
            return False
        ncols = max(len(r) for r in rows)
        if ncols < 2:
            return False
        nonempty = sum(1 for r in rows for c in r if c)
        if nonempty / (len(rows) * ncols) < 0.35:
            return False
        numeric_rows = 0
        for r in rows[1:]:
            if sum(1 for c in r if c and PDFProcessor._is_numeric_cell(c)) >= 2:
                numeric_rows += 1
        return numeric_rows >= 2

    @staticmethod
    def _trim_body_text_rows(rows):
        """Drop leading/trailing rows that look like swallowed body paragraphs
        (one long text cell), which the text strategy sometimes appends."""
        def is_body_row(r):
            cells = [c for c in r if c]
            return len(cells) <= 1 and (not cells or len(cells[0]) > 45)
        out = list(rows)
        while out and is_body_row(out[0]):
            out.pop(0)
        while out and is_body_row(out[-1]):
            out.pop()
        return out

    @staticmethod
    def extract_tables(file_path: str) -> list[dict]:
        """Extract tables from PDF (same output dicts as v1, plus optional
        caption/bbox), using caption-anchored layout extraction plus the
        classic line-strategy pass, both behind a quality filter."""
        tables_data = []
        try:
            with pdfplumber.open(file_path) as pdf:
                n_pages = len(pdf.pages)

                # caption map from PyMuPDF rows (title-safe, two-column safe)
                caption_pages = {}
                try:
                    fdoc = fitz.open(file_path)
                    for pno in range(min(n_pages, len(fdoc))):
                        rows, _wm, _rot = PDFProcessor._page_rows(fdoc[pno])
                        caps = [r for r in rows if _TABLE_CAPTION_RE.match(r["text"].strip())]
                        figs = [r for r in rows if _FIG_CAPTION_RE.match(r["text"].strip())]
                        if caps:
                            caption_pages[pno] = (caps, figs)
                    fdoc.close()
                except Exception:
                    caption_pages = {}

                candidates = []  # {page(1-based), y0, bbox, rows, caption}

                # Phase A: caption-anchored (works on borderless LaTeX tables)
                for pno, (caps, figs) in caption_pages.items():
                    page = pdf.pages[pno]
                    pw, ph = page.width, page.height
                    stop_lines = [(r["y0"], r["y1"]) for r in caps + figs]
                    for cap in caps:
                        found = None
                        regions = []
                        below = (cap["y1"] + 2, min(ph - 42, cap["y1"] + 2 + 0.75 * ph))
                        for sy0, sy1 in stop_lines:
                            if cap["y1"] + 8 < sy0 < below[1]:
                                below = (below[0], min(below[1], sy0 - 2))
                        regions.append(below)
                        above = (max(34, cap["y0"] - 2 - 0.75 * ph), cap["y0"] - 2)
                        for sy0, sy1 in stop_lines:
                            if above[0] < sy1 < cap["y0"] - 8:
                                above = (max(above[0], sy1 + 2), above[1])
                        regions.append(above)
                        if cap["y1"] > 0.85 * ph and pno + 1 < n_pages:
                            regions.append(("next_page",))  # table continues on next page
                        for region in regions:
                            if region == ("next_page",):
                                npage = pdf.pages[pno + 1]
                                crop = npage.crop((24, 40, npage.width - 24, 40 + 0.5 * npage.height))
                            else:
                                y0, y1 = region
                                if y1 - y0 < 30:
                                    continue
                                crop = page.crop((24, y0, pw - 24, y1))
                            try:
                                for t in crop.extract_tables(_TEXT_TABLE_SETTINGS):
                                    rows = PDFProcessor._clean_table_cells(t)
                                    rows = PDFProcessor._trim_body_text_rows(rows)
                                    if PDFProcessor._table_ok(rows):
                                        if found is None or len(rows) > len(found["rows"]):
                                            found = {"rows": rows, "caption": cap["text"].strip()[:150]}
                            except Exception:
                                pass
                            if found is not None:
                                break
                        if found is not None:
                            candidates.append({
                                "page": pno + 1, "y0": cap["y0"],
                                "bbox": None, "rows": found["rows"],
                                "caption": found["caption"],
                            })

                # Phase B: classic line-strategy pass (v1 behavior) + quality gate
                for pno, page in enumerate(pdf.pages):
                    try:
                        for ft in page.find_tables():
                            t = ft.extract()
                            rows = PDFProcessor._clean_table_cells(t)
                            if PDFProcessor._table_ok(rows):
                                candidates.append({
                                    "page": pno + 1,
                                    "y0": (ft.bbox[1] if ft.bbox else 0),
                                    "bbox": [round(v, 1) for v in ft.bbox] if ft.bbox else None,
                                    "rows": rows, "caption": None,
                                })
                    except Exception:
                        continue

                # dedupe overlapping candidates on the same page (keep row-rich)
                candidates.sort(key=lambda c: (-len(c["rows"]), c["page"], c["y0"]))
                accepted = []
                for c in candidates:
                    overlap_ok = True
                    for a in accepted:
                        if a["page"] != c["page"] or c["bbox"] is None or a["bbox"] is None:
                            continue
                        ix0, iy0 = max(a["bbox"][0], c["bbox"][0]), max(a["bbox"][1], c["bbox"][1])
                        ix1, iy1 = min(a["bbox"][2], c["bbox"][2]), min(a["bbox"][3], c["bbox"][3])
                        if ix1 > ix0 and iy1 > iy0:
                            inter = (ix1 - ix0) * (iy1 - iy0)
                            a_area = max(1.0, (a["bbox"][2] - a["bbox"][0]) * (a["bbox"][3] - a["bbox"][1]))
                            c_area = max(1.0, (c["bbox"][2] - c["bbox"][0]) * (c["bbox"][3] - c["bbox"][1]))
                            if inter / min(a_area, c_area) > 0.4:
                                overlap_ok = False
                                break
                    if overlap_ok:
                        accepted.append(c)

                accepted.sort(key=lambda c: (c["page"], c["y0"]))
                per_page_count = {}
                for c in accepted:
                    per_page_count[c["page"]] = per_page_count.get(c["page"], 0) + 1
                    entry = {
                        "page": c["page"],
                        "table_index": per_page_count[c["page"]],
                        "headers": c["rows"][0] if c["rows"] else [],
                        "rows": c["rows"][1:] if len(c["rows"]) > 1 else [],
                        "raw": c["rows"],
                    }
                    if c.get("caption"):
                        entry["caption"] = c["caption"]
                    if c.get("bbox"):
                        entry["bbox"] = c["bbox"]
                    tables_data.append(entry)
        except Exception as e:
            tables_data.append({"error": f"Table extraction failed: {str(e)}"})

        return tables_data

    # ─── Metadata ───────────────────────────────────────────────────────────

    @staticmethod
    def extract_metadata(file_path: str) -> dict:
        """Extract PDF metadata (v1 keys) enriched with authoritative arXiv fields."""
        doc = fitz.open(file_path)
        metadata = doc.metadata or {}
        page_count = len(doc)
        doc.close()
        result = {
            "title": metadata.get("title", ""),
            "author": metadata.get("author", ""),
            "subject": metadata.get("subject", ""),
            "creator": metadata.get("creator", ""),
            "producer": metadata.get("producer", ""),
            "creation_date": metadata.get("creationDate", ""),
            "mod_date": metadata.get("modDate", ""),
            "page_count": page_count,
        }
        arxiv = PDFProcessor._lookup_arxiv(Path(file_path).stem)
        if arxiv:
            result["arxiv_id"] = arxiv["arxiv_id"]
            result["arxiv_title"] = arxiv["title"]
            result["arxiv_authors"] = arxiv["authors"]
            result["arxiv_published"] = arxiv["published"][:10]
            result["arxiv_updated"] = arxiv["updated"][:10]
            result["arxiv_categories"] = arxiv["categories"]
            # arXiv record is authoritative for identity fields; PDF-internal
            # values are often tool artifacts ("borodin04.dvi") or empty.
            if arxiv["title"]:
                result["title"] = arxiv["title"]
            if arxiv["authors"]:
                result["author"] = ", ".join(arxiv["authors"])[:300]
            # PDF internal creationDate (e.g. D:2024...) is the arXiv regeneration
            # date, not the publication date: use the authoritative arXiv record.
            result["creation_date"] = f"{arxiv['published'][:10]} (arXiv v1 published)"
        return result

    # ─── Images ─────────────────────────────────────────────────────────────

    @staticmethod
    def extract_images_info(file_path: str) -> list[dict]:
        """Extract information about images/figures in the PDF."""
        images_info = []
        doc = fitz.open(file_path)
        for page_num in range(len(doc)):
            page = doc[page_num]
            image_list = page.get_images(full=True)
            for img_idx, img in enumerate(image_list):
                images_info.append({
                    "page": page_num + 1,
                    "image_index": img_idx + 1,
                    "width": img[2] if len(img) > 2 else None,
                    "height": img[3] if len(img) > 3 else None,
                })
        doc.close()
        return images_info

    # ─── Pipeline entry point ──────────────────────────────────────────────

    @classmethod
    def process_pdf(cls, file_path: str) -> dict:
        """
        Full PDF processing pipeline.
        Returns a dict with all extracted content ready for Gemini analysis.
        """
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"PDF not found: {file_path}")
        if not path.suffix.lower() == ".pdf":
            raise ValueError(f"Not a PDF file: {file_path}")

        # Extract all components
        full_text = cls.extract_full_text(file_path)
        tables = cls.extract_tables(file_path)
        metadata = cls.extract_metadata(file_path)
        images_info = cls.extract_images_info(file_path)
        file_hash = cls.compute_file_hash(file_path)

        # Format tables as text for Gemini
        tables_text = cls._format_tables_as_text(tables)

        # Combine everything into a structured extraction
        return {
            "file_name": path.name,
            "file_path": str(path.absolute()),
            "file_hash": file_hash,
            "page_count": metadata["page_count"],
            "pdf_metadata": metadata,
            "full_text": full_text,
            "tables": tables,
            "tables_text": tables_text,
            "images_count": len(images_info),
            "images_info": images_info,
            "text_length": len(full_text),
        }

    @staticmethod
    def _format_tables_as_text(tables: list[dict]) -> str:
        """Format extracted tables as readable text for the LLM (v1 format)."""
        if not tables:
            return "No tables found in the document."

        parts = []
        for t in tables:
            if "error" in t:
                parts.append(f"[Table extraction error: {t['error']}]")
                continue

            parts.append(f"\n=== TABLE (Page {t['page']}, Table #{t['table_index']}) ===")
            if t.get("caption"):
                parts.append(f"CAPTION: {t['caption']}")
            if t.get("headers"):
                parts.append(" | ".join(str(h) for h in t["headers"]))
                parts.append("-" * 60)
            for row in t.get("rows", []):
                parts.append(" | ".join(str(cell) for cell in row))

        return "\n".join(parts)

    @staticmethod
    def estimate_token_count(text: str) -> int:
        """Rough estimate of token count (about 4 chars per token for English text)."""
        return len(text) // 4
