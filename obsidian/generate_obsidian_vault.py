"""
generate_obsidian_vault.py
Algoritmikus Obsidian Brain (Knowledge Graph Vault) Generátor.
100% helyi, determinisztikus Python motor (LLM nélkül), amely a kinyert kutatási JSON fájlokból
teljesen összekapcsolt, kétirányú linkekkel (backlinks) ellátott Obsidian tudásbázist épít.

Támogatja:
  1. Inkrementális mód (Alapértelmezett): Csak az új vagy módosult JSON-öket dolgozza fel,
     a meglévő tanulmányjegyzeteket NEM írja felül (megőrzi az egyéni jegyzeteket),
     így 0.1 másodperc alatt fut le!
  2. Teljes mód (--force vagy --full): Minden tanulmány és kapcsolati háló teljes újraépítése.

Struktúra:
  obsidian_vault/
    _Home.md               -> Központi vezérlőpult (MOC / Dashboard)
    Papers/                -> Tanulmány jegyzetek (kérdések, képletek, szabályok, metrikák)
    Authors/               -> Szerzői profilok (publikációk, társszerzői hálózat linkekkel)
    Strategies/            -> Kvant stratégia család gyűjtőoldalak
    Assets/                -> Eszközosztály gyűjtőoldalak
    Years/                 -> Évenkénti idővonalak
    Topics/                -> Kulcstémák & fogalmak hálózata
    .vault_manifest.json   -> Gyorsítótár a már beemelt fájlok nyilvántartására
    .obsidian/             -> Optimalizált Obsidian konfiguráció és Graph View színbeállítások
"""

import os
import re
import sys
import json
import glob
import time
import argparse
from pathlib import Path
from collections import defaultdict, Counter

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE_DIR = Path(__file__).parent.resolve()
PROJECT_ROOT = BASE_DIR.parent

_candidate_json = PROJECT_ROOT / "pdf_processor" / "json"
if not _candidate_json.exists():
    _candidate_json = PROJECT_ROOT / "json"
JSON_DIR = Path(os.getenv("OBSIDIAN_JSON_DIR", str(_candidate_json)))

_candidate_vault = BASE_DIR / "vault"
if not _candidate_vault.exists() and (BASE_DIR / "obsidian_vault").exists():
    _candidate_vault = BASE_DIR / "obsidian_vault"
VAULT_DIR = Path(os.getenv("OBSIDIAN_VAULT_DIR", str(_candidate_vault)))
MANIFEST_FILE = VAULT_DIR / ".vault_manifest.json"

def sanitize_name(text: str, max_len: int = 90) -> str:
    """Windows- és Obsidian-biztos fájlnév készítése."""
    if not text:
        return "Untitled"
    cleaned = re.sub(r'[<>:"/\\|?*#^\[\]\t\n\r]', '_', str(text))
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    cleaned = cleaned.rstrip('. ')
    if len(cleaned) > max_len:
        cleaned = cleaned[:max_len].rstrip('. ')
    return cleaned or "Untitled"

def yaml_escape(text: str) -> str:
    """Biztonságos YAML sztring idézőjelezés."""
    if text is None:
        return ""
    return str(text).replace('"', '\\"').replace('\n', ' ')

def extract_arxiv_id(file_name: str) -> str:
    stem = Path(file_name).stem
    m = re.search(r'(\d{4}\.\d{4,5})', stem)
    if m:
        return m.group(1)
    m2 = re.search(r'([a-z\-]+(?:\.[a-z]{2})?[\/_]\d{7})', stem, re.IGNORECASE)
    if m2:
        return m2.group(1).replace('_', '/')
    return stem

def safe_float(val):
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return float(val)
    if isinstance(val, str):
        m = re.search(r'[-+]?\d*\.?\d+', val)
        if m:
            try:
                return float(m.group(0))
            except Exception:
                pass
    return None

def format_data_item(it) -> str:
    if isinstance(it, str):
        return it
    if isinstance(it, dict):
        parts = []
        if it.get("data_type"): parts.append(str(it["data_type"]))
        if it.get("frequency"): parts.append(f"({it['frequency']})")
        if it.get("source"): parts.append(f"[{it['source']}]")
        if it.get("lookback"): parts.append(f"- {it['lookback']}")
        return " ".join(parts) if parts else json.dumps(it, ensure_ascii=False)
    return str(it)

def load_manifest() -> dict:
    if MANIFEST_FILE.exists():
        try:
            with open(MANIFEST_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_manifest(manifest: dict):
    try:
        with open(MANIFEST_FILE, "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"⚠️ Hiba a manifest mentésekor: {e}")

def parse_single_json(fpath: Path) -> tuple[dict, dict]:
    """Egyetlen JSON fájl beolvasása és átalakítása belső reprezentációra."""
    with open(fpath, "r", encoding="utf-8") as f:
        data = json.load(f)

    doc = data.get("document") or {}
    research = data.get("research") or {}
    strategy = data.get("strategy") or data.get("quantitative_trading_strategy") or {}
    performance = data.get("performance") or data.get("backtest_results") or {}
    backtest = data.get("backtest") or {}
    statistics = data.get("statistics") or {}
    reproducibility = data.get("reproducibility") or {}
    data_req = data.get("data_requirements") or data.get("data_and_empirical_validation") or {}
    markets = data.get("markets") or {}

    formulas = data.get("formulas") or []
    findings = data.get("key_findings") or []
    limitations = data.get("limitations") or []
    key_parameters = data.get("key_parameters") or {}
    references = data.get("source_references") or []

    file_name = doc.get("file_name") or fpath.name
    arxiv_id = extract_arxiv_id(file_name)
    title = doc.get("title") or arxiv_id
    year = doc.get("publication_year") or doc.get("year")
    year_str = str(year) if year else "Ismeretlen"

    raw_authors = doc.get("authors") or []
    clean_authors = [a.strip() for a in raw_authors if a and isinstance(a, str) and a.strip()]

    strat_present = bool(strategy.get("present") or (strategy.get("family") and strategy.get("family") != "None") or strategy.get("has_concrete_strategy"))
    strat_family = strategy.get("family") or ("Kvant Stratégia" if strat_present else "Elméleti Modell")
    if strat_family == "None":
        strat_family = "Elméleti Modell"

    clean_assets = [ac.strip() for ac in (markets.get("asset_classes") or []) if ac and isinstance(ac, str)]
    clean_keywords = [kw.strip() for kw in (doc.get("keywords") or []) if kw and isinstance(kw, str)]

    clean_arxiv_part = sanitize_name(arxiv_id, 30)
    clean_title_part = sanitize_name(title, 80)
    paper_filename = f"{clean_arxiv_part} - {clean_title_part}.md"
    paper_rel_link = f"Papers/{clean_arxiv_part} - {clean_title_part}"

    mtime = os.path.getmtime(fpath)

    paper_obj = {
        "arxiv_id": arxiv_id,
        "title": title,
        "filename": paper_filename,
        "rel_link": paper_rel_link,
        "year": year_str,
        "authors": clean_authors,
        "paper_type": doc.get("paper_type") or "Research",
        "has_strategy": strat_present,
        "strategy_family": strat_family,
        "asset_classes": clean_assets,
        "keywords": clean_keywords,
        "reproducibility": reproducibility.get("classification") or "Közepes",
        "sharpe_ratio": performance.get("sharpe_ratio"),
        "annual_return": performance.get("annualized_return") or performance.get("cagr") or performance.get("total_return"),
        "max_drawdown": performance.get("max_drawdown"),
        "win_rate": performance.get("win_rate"),
        "doc": doc,
        "research": research,
        "strategy": strategy,
        "performance": performance,
        "backtest": backtest,
        "statistics": statistics,
        "reproducibility_obj": reproducibility,
        "data_req": data_req,
        "formulas": formulas,
        "findings": findings,
        "limitations": limitations,
        "key_parameters": key_parameters,
        "references": references,
        "mtime": mtime
    }

    # Tömör összefoglaló a gyorstárhoz (manifesthez)
    manifest_summary = {
        "mtime": mtime,
        "arxiv_id": arxiv_id,
        "title": title,
        "filename": paper_filename,
        "rel_link": paper_rel_link,
        "year": year_str,
        "authors": clean_authors,
        "has_strategy": strat_present,
        "strategy_family": strat_family,
        "asset_classes": clean_assets,
        "keywords": clean_keywords,
        "reproducibility": reproducibility.get("classification") or "Közepes",
        "sharpe_ratio": performance.get("sharpe_ratio"),
        "annual_return": performance.get("annualized_return") or performance.get("cagr") or performance.get("total_return"),
        "formula_count": len(formulas),
        "findings_count": len(findings)
    }

    return paper_obj, manifest_summary

def render_paper_markdown(p: dict) -> str:
    """Teljes értékű Markdown jegyzet készítése egy tanulmányról."""
    md = []
    doc = p["doc"]
    res = p["research"]
    strat = p["strategy"]
    perf = p["performance"]
    bk = p["backtest"]
    stats = p["statistics"]
    repro = p["reproducibility_obj"]
    dreq = p["data_req"]
    forms = p["formulas"]
    finds = p["findings"]
    lims = p["limitations"]

    # YAML Frontmatter
    md.append("---")
    md.append("type: paper")
    md.append(f'arxiv_id: "{yaml_escape(p["arxiv_id"])}"')
    md.append(f'title: "{yaml_escape(p["title"])}"')
    md.append(f'publication_year: {p["year"] if p["year"].isdigit() else "null"}')
    md.append(f'has_strategy: {str(p["has_strategy"]).lower()}')
    md.append(f'strategy_family: "{yaml_escape(p["strategy_family"])}"')
    md.append(f'reproducibility: "{yaml_escape(p["reproducibility"])}"')
    if p["sharpe_ratio"] is not None:
        md.append(f'sharpe_ratio: {p["sharpe_ratio"]}')
    if p["annual_return"] is not None:
        md.append(f'annual_return: "{yaml_escape(str(p["annual_return"]))}"')
    if p["max_drawdown"] is not None:
        md.append(f'max_drawdown: "{yaml_escape(str(p["max_drawdown"]))}"')
    if p["win_rate"] is not None:
        md.append(f'win_rate: "{yaml_escape(str(p["win_rate"]))}"')
    md.append(f'formula_count: {len(forms)}')
    md.append(f'findings_count: {len(finds)}')

    # Authors array in frontmatter
    md.append("authors:")
    for a in p["authors"]:
        md.append(f'  - "[[Authors/{sanitize_name(a)}|{yaml_escape(a)}]]"')

    # Tags
    md.append("tags:")
    md.append("  - quant-research")
    if p["has_strategy"]:
        md.append("  - strategy")
        fam_tag = re.sub(r'[^a-zA-Z0-9]', '-', p["strategy_family"].lower())
        md.append(f"  - strategy/{fam_tag}")
    else:
        md.append("  - theoretical-model")
    for ac in p["asset_classes"][:2]:
        ac_tag = re.sub(r'[^a-zA-Z0-9]', '-', ac.lower())
        md.append(f"  - asset/{ac_tag}")
    md.append("---")
    md.append("")

    # Cím & Meta sáv
    md.append(f"# {p['title']}")
    md.append("")
    
    meta_parts = []
    if p["authors"]:
        auth_links = [f"[[Authors/{sanitize_name(a)}|{a}]]" for a in p["authors"]]
        meta_parts.append(f"**Szerzők:** {', '.join(auth_links)}")
    if p["year"] != "Ismeretlen":
        meta_parts.append(f"**Év:** [[Years/{p['year']}|{p['year']}]]")
    strat_link = f"[[Strategies/{sanitize_name(p['strategy_family'])}|{p['strategy_family']}]]"
    meta_parts.append(f"**Stratégia:** {strat_link}")
    meta_parts.append(f"[arXiv:{p['arxiv_id']}](https://arxiv.org/abs/{p['arxiv_id']})")
    meta_parts.append("[[ _Home | 🏠 Főoldal ]]")
    md.append(" • ".join(meta_parts))
    md.append("")

    # Eszközosztályok
    if p["asset_classes"]:
        asset_links = [f"[[Assets/{sanitize_name(ac)}|{ac}]]" for ac in p["asset_classes"]]
        md.append(f"> **Kereskedett Eszközök:** {' '.join(asset_links)}")
        md.append("")

    # Kutatási Kérdés & Hipotézis Callout-ok
    if res.get("research_question"):
        md.append("> [!question] Központi Kutatási Kérdés")
        md.append(f"> {res['research_question']}")
        md.append("")

    if res.get("hypothesis"):
        md.append("> [!note] Tudományos Hipotézis")
        md.append(f"> {res['hypothesis']}")
        md.append("")

    if res.get("objective") or res.get("economic_intuition") or res.get("market_phenomenon"):
        md.append("> [!abstract] Célkitűzés & Közgazdasági Intuíció")
        if res.get("objective"):
            md.append(f"> - **Cél:** {res['objective']}")
        if res.get("market_phenomenon"):
            md.append(f"> - **Piaci Jelenség:** {res['market_phenomenon']}")
        if res.get("economic_intuition"):
            md.append(f"> - **Intuició:** {res['economic_intuition']}")
        md.append("")

    # Kulcs Megállapítások
    md.append(f"## 💡 Kulcs Tudományos Megállapítások & Állítások ({len(finds)})")
    if finds:
        for fitem in finds:
            txt = fitem if isinstance(fitem, str) else json.dumps(fitem, ensure_ascii=False)
            md.append(f"- [x] {txt}")
    else:
        md.append("_Nincsenek kinyert explicit állítások._")
    md.append("")

    # Kutatási Korlátok
    if lims:
        md.append(f"## ⚠️ Kutatási Korlátok ({len(lims)})")
        for litem in lims:
            txt = litem if isinstance(litem, str) else json.dumps(litem, ensure_ascii=False)
            md.append(f"- ⚠️ {txt}")
        md.append("")

    # Matematikai Képletek & Modellek
    md.append(f"## 📐 Matematikai Modellek & Képletek ({len(forms)})")
    if forms:
        for f_idx, form in enumerate(forms, 1):
            fname = form.get("name") or f"Képlet #{f_idx}"
            fcode = form.get("formula") or ""
            fpage = form.get("page")
            fpurpose = form.get("purpose")
            vars_dict = form.get("variables") or {}

            page_tag = f" _(Oldal: {fpage})_" if fpage else ""
            md.append(f"### 📐 {fname}{page_tag}")
            if fpurpose:
                md.append(f"> **Cél:** {fpurpose}")
                md.append("")
            
            md.append("$$")
            md.append(str(fcode))
            md.append("$$")
            md.append("")

            if isinstance(vars_dict, dict) and vars_dict:
                md.append("| Változó / Szimbólum | Jelentés / Definíció |")
                md.append("| :--- | :--- |")
                for vk, vv in vars_dict.items():
                    md.append(f"| `{vk}` | {vv} |")
                md.append("")
    else:
        md.append("_Ebben a tanulmányban nincsenek külön zárt matematikai egyenletek rögzítve._")
    md.append("")

    # Kvant Stratégia
    if p["has_strategy"]:
        md.append("## ⚡ Kvantitatív Kereskedési Stratégia")
        md.append(f"- **Stratégia Neve:** {strat.get('name') or p['strategy_family']}")
        md.append(f"- **Típus / Irány:** {strat.get('type') or 'N/A'} | {strat.get('direction') or 'Long/Short'}")
        md.append(f"- **Tartási Idő & Frekvencia:** {strat.get('holding_period') or 'N/A'} | {strat.get('trading_frequency') or 'N/A'}")
        md.append(f"- **Végrehajtási Mód:** {'Szisztematikus' if strat.get('systematic') else 'Diszkrecionális'}")
        md.append("")

        sig = strat.get("signal") or {}
        if sig:
            md.append("### 📡 Kereskedési Jel Generálás (Signal)")
            if sig.get("description"): md.append(f"- **Leírás:** {sig['description']}")
            if sig.get("formula"): md.append(f"- **Jel Képlete:** `{sig['formula']}`")
            if sig.get("indicators"):
                inds = sig["indicators"] if isinstance(sig["indicators"], list) else [sig["indicators"]]
                md.append(f"- **Indikátorok:** {', '.join(str(x) for x in inds)}")
            if sig.get("thresholds"):
                thrs = sig["thresholds"] if isinstance(sig["thresholds"], list) else [sig["thresholds"]]
                md.append(f"- **Küszöbök:** {', '.join(str(x) for x in thrs)}")
            if sig.get("lookback_periods"):
                lbs = sig["lookback_periods"] if isinstance(sig["lookback_periods"], list) else [sig["lookback_periods"]]
                md.append(f"- **Visszatekintési Időszakok:** {', '.join(str(x) for x in lbs)}")
            md.append("")

        ent = strat.get("entry") or {}
        ext = strat.get("exit") or {}
        if ent or ext:
            md.append("### 🎯 Kereskedési Szabályok")
            if ent.get("long"): md.append(f"- **Long Belépés:** {ent['long']}")
            if ent.get("short"): md.append(f"- **Short Belépés:** {ent['short']}")
            if ext.get("stop_loss"): md.append(f"- **Stop Loss:** {ext['stop_loss']}")
            if ext.get("take_profit"): md.append(f"- **Take Profit:** {ext['take_profit']}")
            if ext.get("time_exit"): md.append(f"- **Időalapú Kilépés:** {ext['time_exit']}")
            if ext.get("signal_reversal"): md.append(f"- **Forduló Jel:** {ext['signal_reversal']}")
            md.append("")

        pos = strat.get("position_sizing") or {}
        risk = strat.get("risk_management") or {}
        if pos.get("method") or risk.get("method"):
            md.append("### 🛡️ Pozíció Méretezés & Kockázatkezelés")
            if pos.get("method"): md.append(f"- **Pozíció Méret:** {pos['method']}")
            if risk.get("method"): md.append(f"- **Kockázatkezelés:** {risk['method']}")
            md.append("")

    # Visszateszt & Metrikák
    has_perf = any([p["sharpe_ratio"], p["annual_return"], p["max_drawdown"], p["win_rate"]])
    if has_perf or bk:
        md.append("## 📊 Visszateszt & Metrikák")
        md.append("| Metrika | Érték |")
        md.append("| :--- | :--- |")
        if p["sharpe_ratio"] is not None: md.append(f"| **Sharpe Arány** | **{p['sharpe_ratio']}** |")
        if p["annual_return"] is not None: md.append(f"| **Évesített Hozam** | {p['annual_return']} |")
        if p["max_drawdown"] is not None: md.append(f"| **Maximális Visszaesés** | {p['max_drawdown']} |")
        if p["win_rate"] is not None: md.append(f"| **Nyerési Arány** | {p['win_rate']} |")
        if perf.get("volatility") is not None: md.append(f"| Volatilitás | {perf['volatility']} |")
        if perf.get("sortino_ratio") is not None: md.append(f"| Sortino Arány | {perf['sortino_ratio']} |")
        if perf.get("calmar_ratio") is not None: md.append(f"| Calmar Arány | {perf['calmar_ratio']} |")
        if perf.get("alpha") is not None: md.append(f"| Alpha | {perf['alpha']} |")
        if perf.get("beta") is not None: md.append(f"| Beta | {perf['beta']} |")
        bench = perf.get("benchmark") or {}
        if bench.get("name"): md.append(f"| Benchmark ({bench['name']}) | {bench.get('return') or '-'} |")
        md.append("")

        stests = stats.get("statistical_tests") or []
        tstats = stats.get("t_statistics") or []
        pvals = stats.get("p_values") or []
        if stests or tstats or pvals:
            md.append("### 📐 Statisztikai Szignifikancia")
            if tstats: md.append(f"- **t-Statisztika:** {', '.join(str(x) for x in tstats) if isinstance(tstats, list) else tstats}")
            if pvals: md.append(f"- **p-Érték:** {', '.join(str(x) for x in pvals) if isinstance(pvals, list) else pvals}")
            if stests: md.append(f"- **Elvégzett Tesztek:** {', '.join(str(x) for x in stests) if isinstance(stests, list) else stests}")
            md.append("")

    # Technológia & Adatok
    md.append("## 🖥️ Technológia, Adatok & Reprodukálhatóság")
    md.append(f"- **Reprodukálhatóság:** {p['reproducibility']}")
    md.append(f"- **Kód Elérhetőség:** {'Igen' if repro.get('source_code_available') else 'Nem'}")
    md.append(f"- **Adatok Elérhetők:** {'Igen' if repro.get('data_available') else 'Nem'}")
    
    dsources = dreq.get("data_sources") or []
    if dsources:
        clean_ds = []
        for ds in dsources:
            if isinstance(ds, str): clean_ds.append(ds)
            elif isinstance(ds, dict): clean_ds.append(ds.get("name") or ds.get("source") or json.dumps(ds))
            else: clean_ds.append(str(ds))
        md.append(f"- **Adatforrások:** {', '.join(clean_ds)}")
    if dreq.get("signal_data"):
        sdata_str = "; ".join(format_data_item(x) for x in dreq["signal_data"][:2])
        md.append(f"- **Jel Generálási Adat:** {sdata_str}")
    if dreq.get("backtest_data"):
        bdata_str = "; ".join(format_data_item(x) for x in dreq["backtest_data"][:2])
        md.append(f"- **Visszateszt Adat:** {bdata_str}")
    md.append("")

    # Témakörök
    if p["keywords"]:
        topic_links = [f"[[Topics/{sanitize_name(kw)}|#{kw.replace(' ', '_')}]]" for kw in p["keywords"]]
        md.append("## 🏷️ Témakörök & Címkék")
        md.append(" ".join(topic_links))
        md.append("")

    # Abstract
    if doc.get("abstract"):
        md.append("## 📄 Hivatalos Abstract")
        md.append(f"> {doc['abstract']}")
        md.append("")

    return "\n".join(md)

def build_vault(force_full: bool = False, verbose: bool = True) -> dict:
    start_time = time.time()
    if verbose:
        print("=" * 68)
        print("🧠 Obsidian Brain Generátor indítása...")
        print(f"📁 Forrás könyvtár: {JSON_DIR}")
        print(f"🏛️ Cél Obsidian Vault: {VAULT_DIR}")
        mode_label = "TELJES ÚJRAGENERÁLÁS (--force)" if force_full else "INKREMENTÁLIS (Csak új JSON-ök)"
        print(f"⚙️ Mód: {mode_label}")
        print("=" * 68)

    if not JSON_DIR.exists():
        msg = f"❌ Hiba: A {JSON_DIR} mappa nem létezik!"
        if verbose: print(msg)
        return {"status": "error", "message": msg}

    # Mappák létrehozása
    folders = [
        VAULT_DIR,
        VAULT_DIR / "Papers",
        VAULT_DIR / "Authors",
        VAULT_DIR / "Strategies",
        VAULT_DIR / "Assets",
        VAULT_DIR / "Years",
        VAULT_DIR / "Topics",
        VAULT_DIR / ".obsidian"
    ]
    for folder in folders:
        folder.mkdir(parents=True, exist_ok=True)

    json_files = sorted(glob.glob(str(JSON_DIR / "*.json")))
    total_json_count = len(json_files)
    if verbose:
        print(f"🔍 Lemezről talált JSON fájlok: {total_json_count} db")

    manifest = load_manifest()
    manifest_files = manifest.get("files") or {}

    # Ellenőrizzük, miket kell feldolgozni
    to_process = []
    already_summaries = {}

    for fpath_str in json_files:
        fpath = Path(fpath_str)
        fname = fpath.name
        mtime = os.path.getmtime(fpath)

        if not force_full and fname in manifest_files:
            cached = manifest_files[fname]
            # Ha az mtime megegyezik és a paper markdown fájl létezik a Papers mappában
            paper_md_path = VAULT_DIR / "Papers" / cached.get("filename", "")
            if cached.get("mtime") == mtime and paper_md_path.exists():
                already_summaries[fname] = cached
                continue

        to_process.append(fpath)

    new_count = len(to_process)
    existing_count = len(already_summaries)

    if verbose:
        print(f"📊 Állapot: 🆕 Új / Módosult: {new_count} db | ⏩ Meglévő: {existing_count} db")

    # Ha inkrementális módban vagyunk és nincs új feldolgozandó
    if not force_full and new_count == 0:
        msg = f"✨ Minden kutatási JSON ({total_json_count} db) már fel van dolgozva az Obsidian Vaultban! Nincs új tanulmány."
        if verbose:
            print("-" * 68)
            print(msg)
            print("💡 Újragenerálás kényszerítéséhez: python generate_obsidian_vault.py --force")
            print("=" * 68)
        return {
            "status": "up_to_date",
            "new_count": 0,
            "total_count": total_json_count,
            "message": msg
        }

    # Új / módosult JSON-ök feldolgozása és Papers/ jegyzetek mentése
    updated_summaries = dict(already_summaries)
    written_new_count = 0
    if new_count > 0:
        if verbose:
            print(f"⚡ Új vagy hiányzó jegyzetek vizsgálata ({new_count} db)...")
        for idx, fpath in enumerate(to_process, 1):
            try:
                paper_obj, summary = parse_single_json(fpath)
                target_md = VAULT_DIR / "Papers" / paper_obj["filename"]

                # Ha a jegyzet még nem létezik az Obsidianban, vagy teljes felülírást kért a felhasználó
                if not target_md.exists() or force_full:
                    md_content = render_paper_markdown(paper_obj)
                    with open(target_md, "w", encoding="utf-8") as pf:
                        pf.write(md_content)
                    written_new_count += 1

                updated_summaries[fpath.name] = summary
            except Exception as e:
                print(f"⚠️ Hiba a {fpath.name} feldolgozásakor: {e}")

        if verbose:
            if written_new_count > 0:
                print(f"📝 Valóban újonnan létrehozott jegyzetek: {written_new_count} db")
            else:
                print(f"ℹ️ A jegyzetek már mind léteztek a Papers mappában (0 db felülírás).")

    # Tudásháló relációk felépítése az összes összesített összefoglalóból
    if verbose:
        print("🔗 Kapcsolati hálók frissítése (Authors, Strategies, Assets, Years, Topics)...")

    authors_map = defaultdict(lambda: {
        "papers": [],
        "coauthors": Counter(),
        "asset_classes": Counter(),
        "strategies": Counter(),
        "keywords": Counter()
    })
    strategies_map = defaultdict(lambda: {"papers": []})
    assets_map = defaultdict(lambda: {"papers": []})
    years_map = defaultdict(lambda: {"papers": []})
    topics_map = defaultdict(lambda: {"papers": []})

    total_formulas = 0
    total_findings = 0
    all_papers_list = []

    for fname, sm in updated_summaries.items():
        all_papers_list.append(sm)
        total_formulas += sm.get("formula_count", 0)
        total_findings += sm.get("findings_count", 0)

        # Szerzők & Társszerzők
        authors = sm.get("authors") or []
        for a in authors:
            authors_map[a]["papers"].append(sm)
            for ca in authors:
                if ca != a:
                    authors_map[a]["coauthors"][ca] += 1
            for ac in sm.get("asset_classes") or []:
                authors_map[a]["asset_classes"][ac] += 1
            fam = sm.get("strategy_family") or "Elméleti Modell"
            if fam != "Elméleti Modell":
                authors_map[a]["strategies"][fam] += 1
            for kw in sm.get("keywords") or []:
                authors_map[a]["keywords"][kw] += 1

        # Stratégiák
        fam = sm.get("strategy_family") or "Elméleti Modell"
        strategies_map[fam]["papers"].append(sm)

        # Eszközök
        for ac in sm.get("asset_classes") or []:
            assets_map[ac]["papers"].append(sm)

        # Évek
        y_str = sm.get("year") or "Ismeretlen"
        years_map[y_str]["papers"].append(sm)

        # Témák
        for kw in sm.get("keywords") or []:
            topics_map[kw]["papers"].append(sm)

    # ── Szerzői Jegyzetek Mentése ──
    for author, adata in authors_map.items():
        auth_filename = f"{sanitize_name(author)}.md"
        auth_papers = adata["papers"]
        coauthors = adata["coauthors"]
        strat_count = sum(1 for p in auth_papers if p.get("has_strategy"))

        md = []
        md.append("---")
        md.append("type: author")
        md.append(f'name: "{yaml_escape(author)}"')
        md.append(f"paper_count: {len(auth_papers)}")
        md.append(f"strategy_count: {strat_count}")
        md.append(f"coauthor_count: {len(coauthors)}")
        md.append("tags:")
        md.append("  - author")
        if len(auth_papers) >= 5:
            md.append("  - prolific-author")
        md.append("---")
        md.append("")
        md.append(f"# 👤 {author}")
        md.append("")
        md.append(f"[[ _Home | 🏠 Főoldal ]] • **Publikációk száma:** {len(auth_papers)} db • **Kvant stratégiák:** {strat_count} db • **Társszerzők:** {len(coauthors)} fő")
        md.append("")

        md.append(f"## 📚 Publikált Tanulmányok ({len(auth_papers)})")
        sorted_papers = sorted(auth_papers, key=lambda x: (x.get("year", "0") if x.get("year", "").isdigit() else "0"), reverse=True)
        for p in sorted_papers:
            strat_pill = f"[[Strategies/{sanitize_name(p['strategy_family'])}|{p['strategy_family']}]]"
            sharpe_pill = f" (Sharpe: **{p['sharpe_ratio']}**)" if p.get('sharpe_ratio') is not None else ""
            year_pill = f"[[Years/{p['year']}|{p['year']}]]" if p.get('year') != "Ismeretlen" else "Ismeretlen"
            md.append(f"- [[{p['rel_link']}|{p['title']}]] — {year_pill} • {strat_pill}{sharpe_pill}")
        md.append("")

        if coauthors:
            md.append(f"## 👥 Társszerzői Kapcsolatok ({len(coauthors)})")
            for coauth, count in coauthors.most_common(25):
                cname_clean = sanitize_name(coauth)
                md.append(f"- [[Authors/{cname_clean}|{coauth}]] ({count} közös tanulmány)")
            md.append("")

        if adata["asset_classes"]:
            md.append("## 📈 Leggyakoribb Eszközosztályok")
            for ac, count in adata["asset_classes"].most_common(8):
                md.append(f"- [[Assets/{sanitize_name(ac)}|{ac}]] ({count} tanulmány)")
            md.append("")

        if adata["keywords"]:
            md.append("## 🏷️ Fő Kutatási Témák")
            tlinks = [f"[[Topics/{sanitize_name(k)}|#{k.replace(' ', '_')}]]" for k, _ in adata["keywords"].most_common(12)]
            md.append(" ".join(tlinks))
            md.append("")

        with open(VAULT_DIR / "Authors" / auth_filename, "w", encoding="utf-8") as af:
            af.write("\n".join(md))

    # ── Stratégia Családok Mentése ──
    for family, sdata in strategies_map.items():
        fam_filename = f"{sanitize_name(family)}.md"
        fam_papers = sdata["papers"]
        sharpes = [safe_float(p.get("sharpe_ratio")) for p in fam_papers]
        sharpes = [s for s in sharpes if s is not None]
        avg_sharpe = round(sum(sharpes) / len(sharpes), 2) if sharpes else None

        md = []
        md.append("---")
        md.append("type: strategy_family")
        md.append(f'family: "{yaml_escape(family)}"')
        md.append(f"paper_count: {len(fam_papers)}")
        if avg_sharpe is not None:
            md.append(f"avg_sharpe: {avg_sharpe}")
        md.append("tags:")
        md.append("  - strategy-family")
        md.append("---")
        md.append("")
        md.append(f"# ⚡ {family} Kvant Stratégiák")
        md.append("")
        md.append(f"[[ _Home | 🏠 Főoldal ]] • **Tanulmányok száma:** {len(fam_papers)} db" + (f" • **Átlagos Sharpe:** {avg_sharpe}" if avg_sharpe else ""))
        md.append("")

        md.append(f"## 📑 Kapcsolódó Tanulmányok ({len(fam_papers)})")
        sorted_fam = sorted(fam_papers, key=lambda x: (safe_float(x.get("sharpe_ratio")) is not None, safe_float(x.get("sharpe_ratio")) or 0), reverse=True)
        for p in sorted_fam:
            sharpe_txt = f" — Sharpe: **{p['sharpe_ratio']}**" if p.get('sharpe_ratio') is not None else ""
            year_txt = f"[[Years/{p['year']}|{p['year']}]]" if p.get('year') != "Ismeretlen" else ""
            auth_txt = f"Szerzők: {', '.join(f'[[Authors/{sanitize_name(a)}|{a}]]' for a in p.get('authors', [])[:2])}" if p.get('authors') else ""
            md.append(f"- [[{p['rel_link']}|{p['title']}]] ({year_txt}) • {auth_txt}{sharpe_txt}")
        md.append("")

        with open(VAULT_DIR / "Strategies" / fam_filename, "w", encoding="utf-8") as sf:
            sf.write("\n".join(md))

    # ── Eszközosztályok Mentése ──
    for asset, adata in assets_map.items():
        asset_filename = f"{sanitize_name(asset)}.md"
        asset_papers = adata["papers"]

        md = []
        md.append("---")
        md.append("type: asset_class")
        md.append(f'asset_class: "{yaml_escape(asset)}"')
        md.append(f"paper_count: {len(asset_papers)}")
        md.append("tags:")
        md.append("  - asset-class")
        md.append("---")
        md.append("")
        md.append(f"# 📈 {asset} Eszközosztály")
        md.append("")
        md.append(f"[[ _Home | 🏠 Főoldal ]] • **Kapcsolódó Tanulmányok:** {len(asset_papers)} db")
        md.append("")
        md.append("## 📑 Tanulmányok Listája")
        for p in sorted(asset_papers, key=lambda x: (x.get("year", "0") if x.get("year", "").isdigit() else "0"), reverse=True):
            strat_pill = f"[[Strategies/{sanitize_name(p['strategy_family'])}|{p['strategy_family']}]]"
            md.append(f"- [[{p['rel_link']}|{p['title']}]] ([[Years/{p['year']}|{p['year']}]]) — {strat_pill}")
        md.append("")

        with open(VAULT_DIR / "Assets" / asset_filename, "w", encoding="utf-8") as asf:
            asf.write("\n".join(md))

    # ── Évek Mentése ──
    for y_str, ydata in years_map.items():
        if not y_str or y_str == "Ismeretlen": continue
        year_filename = f"{sanitize_name(y_str)}.md"
        y_papers = ydata["papers"]

        md = []
        md.append("---")
        md.append("type: timeline_year")
        md.append(f"year: {y_str}")
        md.append(f"paper_count: {len(y_papers)}")
        md.append("tags:")
        md.append("  - timeline")
        md.append("---")
        md.append("")
        md.append(f"# 📅 {y_str}. Évi Kutatások")
        md.append("")
        md.append(f"[[ _Home | 🏠 Főoldal ]] • **Ebben az évben megjelent tanulmányok:** {len(y_papers)} db")
        md.append("")
        md.append("## 📑 Tanulmányok")
        for p in y_papers:
            strat_pill = f"[[Strategies/{sanitize_name(p['strategy_family'])}|{p['strategy_family']}]]"
            sharpe_pill = f" — Sharpe: **{p['sharpe_ratio']}**" if p.get('sharpe_ratio') is not None else ""
            md.append(f"- [[{p['rel_link']}|{p['title']}]] — {strat_pill}{sharpe_pill}")
        md.append("")

        with open(VAULT_DIR / "Years" / year_filename, "w", encoding="utf-8") as yf:
            yf.write("\n".join(md))

    # ── Témák Mentése (>= 2 előfordulás) ──
    popular_topics = {k: v for k, v in topics_map.items() if len(v["papers"]) >= 2}
    for topic, tdata in popular_topics.items():
        topic_filename = f"{sanitize_name(topic)}.md"
        t_papers = tdata["papers"]

        md = []
        md.append("---")
        md.append("type: topic")
        md.append(f'topic: "{yaml_escape(topic)}"')
        md.append(f"paper_count: {len(t_papers)}")
        md.append("tags:")
        md.append("  - topic")
        md.append("---")
        md.append("")
        md.append(f"# 🏷️ {topic}")
        md.append("")
        md.append(f"[[ _Home | 🏠 Főoldal ]] • **Kapcsolódó kutatások:** {len(t_papers)} db")
        md.append("")
        md.append("## 📑 Kapcsolódó Tanulmányok")
        for p in t_papers:
            md.append(f"- [[{p['rel_link']}|{p['title']}]] ([[Years/{p['year']}|{p['year']}]]) — [[Strategies/{sanitize_name(p['strategy_family'])}|{p['strategy_family']}]]")
        md.append("")

        with open(VAULT_DIR / "Topics" / topic_filename, "w", encoding="utf-8") as tf:
            tf.write("\n".join(md))

    # ── Központi Kezdőlap (_Home.md) ──
    home_md = []
    home_md.append("---")
    home_md.append("type: moc")
    home_md.append("title: 'arXiv Quant Research Brain'")
    home_md.append("tags:")
    home_md.append("  - hub")
    home_md.append("  - moc")
    home_md.append("---")
    home_md.append("")
    home_md.append("# 🧠 arXiv Quant & Theoretical Research Brain")
    home_md.append("")
    home_md.append("> [!info] Üdvözlünk az Algoritmikusan Felépített Kvant Tudástárban!")
    home_md.append(f"> Ez a tudástár **{len(all_papers_list)} db kutatási tanulmányból** épül fel helt determinisztikus Python motorral.")
    home_md.append("> Kétirányú hivatkozásokkal (**backlinks**) köti össze a szerzőket, kvant stratégiákat, levezetett matematikai képleteket, piaci eszközosztályokat és tudományos megállapításokat.")
    home_md.append("")

    home_md.append("## 📊 Tudásbázis Kulcsszámai")
    home_md.append("| Kategória | Darabszám | Leírás |")
    home_md.append("| :--- | :--- | :--- |")
    home_md.append(f"| **Tanulmányok (Papers)** | `{len(all_papers_list)} db` | Kérdésekkel, hipotézisekkel, képletekkel és szabályokkal |")
    home_md.append(f"| **Kutatók & Szerzők (Authors)** | `{len(authors_map)} fő` | Kapcsolati és társszerzői hálózattal |")
    home_md.append(f"| **Képletek & Modellek (Formulas)** | `{total_formulas} db` | LaTeX levezetésekkel és változókkal |")
    home_md.append(f"| **Tudományos Megállapítások** | `{total_findings} db` | Igazolt állítások és tételek |")
    home_md.append(f"| **Kvant Stratégiák (Strategies)** | `{sum(1 for p in all_papers_list if p.get('has_strategy'))} db` | Szisztematikus kereskedési rendszerek |")
    home_md.append("")

    # Stratégia családok
    home_md.append("## ⚡ Kvant Stratégia Családok")
    sorted_strats = sorted(strategies_map.items(), key=lambda x: len(x[1]["papers"]), reverse=True)
    for fam, sdata in sorted_strats:
        if fam == "Elméleti Modell": continue
        p_count = len(sdata["papers"])
        fam_clean = sanitize_name(fam)
        home_md.append(f"- [[Strategies/{fam_clean}|{fam}]] — `{p_count} tanulmány`")
    home_md.append(f"- [[Strategies/Elméleti Modell|Elméleti Modellek & Matematika]] — `{len(strategies_map.get('Elméleti Modell', {}).get('papers', []))} tanulmány`")
    home_md.append("")

    # Top Szerzők
    home_md.append("## 👤 Legtermékenyebb Kutatók (Top Szerzők)")
    top_authors = sorted(authors_map.items(), key=lambda x: len(x[1]["papers"]), reverse=True)[:15]
    for auth, adata in top_authors:
        clean_a = sanitize_name(auth)
        home_md.append(f"- [[Authors/{clean_a}|{auth}]] — `{len(adata['papers'])} publikáció`, `{len(adata['coauthors'])} társszerző`")
    home_md.append("")

    # Fő Eszközosztályok
    home_md.append("## 📈 Eszközosztályok")
    top_assets = sorted(assets_map.items(), key=lambda x: len(x[1]["papers"]), reverse=True)[:10]
    for ac, adata in top_assets:
        clean_ac = sanitize_name(ac)
        home_md.append(f"- [[Assets/{clean_ac}|{ac}]] — `{len(adata['papers'])} tanulmány`")
    home_md.append("")

    # Idővonal
    home_md.append("## 📅 Idővonal (Évek)")
    valid_years = sorted([y for y in years_map.keys() if y.isdigit()], reverse=True)
    year_links = [f"[[Years/{y}|{y}]] ({len(years_map[y]['papers'])})" for y in valid_years]
    home_md.append(" • ".join(year_links[:15]))
    home_md.append("")

    # Top Sharpe
    home_md.append("## 🏆 Kiemelkedő Teljesítményű Stratégiák (Top Sharpe)")
    papers_with_sharpe = [p for p in all_papers_list if safe_float(p.get("sharpe_ratio")) is not None]
    top_sharpe_papers = sorted(papers_with_sharpe, key=lambda x: safe_float(x.get("sharpe_ratio")), reverse=True)[:10]
    for p in top_sharpe_papers:
        home_md.append(f"- **Sharpe: {p['sharpe_ratio']}** — [[{p['rel_link']}|{p['title']}]] ([[Years/{p['year']}|{p['year']}]]) — [[Strategies/{sanitize_name(p['strategy_family'])}|{p['strategy_family']}]]")
    home_md.append("")

    with open(VAULT_DIR / "_Home.md", "w", encoding="utf-8") as hf:
        hf.write("\n".join(home_md))

    # Manifest mentése
    new_manifest_data = {
        "version": 1,
        "last_updated": time.time(),
        "total_files": len(updated_summaries),
        "files": updated_summaries
    }
    save_manifest(new_manifest_data)

    elapsed = time.time() - start_time
    reported_new = written_new_count if not force_full else new_count
    if verbose:
        print("=" * 68)
        if reported_new > 0:
            print(f"🎉 SIKER! {reported_new} új tanulmány beépítve a tudástárba!")
        else:
            print(f"✨ Minden tanulmány indexálva! 0 db felülírás történt.")
        print(f"⏱️ Futási idő: {elapsed:.2f} másodperc | Összes tanulmány a Vaultban: {len(updated_summaries)} db")
        print(f"📂 Elérési út: {VAULT_DIR}")
        print("ℹ️ Használat: Nyisd meg az Obsidiant -> 'Open folder as vault' -> válaszd ki a 'vault' mappát (vagy obsidian/vault)!")
        print("=" * 68)

    return {
        "status": "ok",
        "new_count": reported_new,
        "total_count": len(updated_summaries),
        "elapsed_seconds": round(elapsed, 2)
    }

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Algoritmikus Obsidian Brain generátor")
    parser.add_argument("--force", "--full", action="store_true", help="Teljes újragenerálás kényszerítése (minden jegyzet felülírása)")
    args = parser.parse_args()
    build_vault(force_full=args.force)
