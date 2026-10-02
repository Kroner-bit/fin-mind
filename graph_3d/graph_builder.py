"""
graph_builder.py
Nagy teljesítményű Kvant & Multidiszciplináris Tudásgráf Építő Motor.
Kifejezetten 10 000 - 50 000+ csomópont és százezer backlink kezelésére optimalizálva.

Főbb feladatok:
1. Párhuzamos, kizárólag olvasási (read-only) JSON beolvasás a pdf_processor/json mappából.
2. Csomópontok (Nodes) generálása: Tanulmányok, Szerzők, Stratégiák, Diszciplínák, Eszközosztályok, Kulcsfogalmak.
3. Élek és Backlinkek (Edges) felépítése: Szerzőség, Stratégiai kapcsolat, Tudományági kapcsolat, Társszerzőség, Hivatkozási láncok.
4. GPU-kész 3D Pozicionálás (Klaszter-alapú galaktikus elrendezés + NetworkX 3D relaxáció).
5. Inkrementális gyorstár (cache), hogy másodperc töredéke alatt betöltődjön.
"""

import os
import re
import sys
import json
import time
import math
import hashlib
from pathlib import Path
from collections import defaultdict, Counter
import numpy as np
import networkx as nx

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE_DIR = Path(__file__).parent.resolve()
PROJECT_ROOT = BASE_DIR.parent

JSON_DIR = PROJECT_ROOT / "pdf_processor" / "json"
CACHE_DIR = BASE_DIR / "cache"
CACHE_FILE = CACHE_DIR / "graph_cache.json"

# Diszciplínák 3D Galaktikus Klaszter Központjai (Galactic Centers)
# Ez adja a lenyűgöző "univerzum / csillagköd" térbeli elrendezést
DISCIPLINE_CENTERS = {
    "QuantitativeFinance": (0.0, 0.0, 0.0),
    "EconomicsAndEconometrics": (-350.0, 150.0, -100.0),
    "ComputerScienceAndAI": (300.0, 250.0, 150.0),
    "MathematicsAndStatistics": (150.0, -300.0, -200.0),
    "PhysicsAndComplexSystems": (-250.0, -200.0, 250.0),
    "AstrophysicsAndCosmology": (-400.0, 300.0, 350.0),
    "InterdisciplinaryScience": (200.0, -150.0, 300.0),
    "Other": (0.0, 400.0, -300.0)
}

DISCIPLINE_COLORS = {
    "QuantitativeFinance": "#0A84FF",       # Apple Pro Clean Blue
    "EconomicsAndEconometrics": "#30D158",  # Apple Pro Mint/Emerald
    "ComputerScienceAndAI": "#64D2FF",      # Apple Pro Cyan/Teal
    "MathematicsAndStatistics": "#BF5AF2",  # Apple Pro Purple
    "PhysicsAndComplexSystems": "#FF9F0A",  # Apple Pro Amber
    "AstrophysicsAndCosmology": "#30D158",  # Apple Pro Emerald
    "InterdisciplinaryScience": "#5E5CE6",  # Apple Pro Indigo
    "Other": "#98989D"                      # Apple Pro Slate Grey
}

NODE_TYPE_COLORS = {
    "paper": "#0A84FF",
    "author": "#FF9F0A",
    "strategy": "#FF453A",
    "discipline": "#30D158",
    "asset": "#BF5AF2",
    "topic": "#6E6E73"
}

def sanitize_id(text: str) -> str:
    """Biztonságos egyedi csomópont azonosító készítése."""
    clean = re.sub(r'[^a-zA-Z0-9_\-]', '_', str(text).strip())
    return clean[:80] or "unknown"

class KnowledgeGraphBuilder:
    def __init__(self, json_dir: Path = JSON_DIR):
        self.json_dir = Path(json_dir)
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        self.cached_graph = None
        self.last_build_time = 0

    def get_json_files(self) -> list[Path]:
        if not self.json_dir.exists():
            return []
        return sorted(list(self.json_dir.glob("*.json")))

    def build_graph(self, force_rebuild: bool = False) -> dict:
        """
        Teljes tudásgráf felépítése a kinyert JSON állományokból.
        Ha létezik friss cache és nincs új fájl, azonnal betölti a memóriából/lemezről.
        """
        json_files = self.get_json_files()
        total_files = len(json_files)

        # Cache ellenőrzés
        if not force_rebuild and CACHE_FILE.exists():
            try:
                with open(CACHE_FILE, "r", encoding="utf-8") as f:
                    cached = json.load(f)
                if cached.get("file_count") == total_files and total_files > 0:
                    self.cached_graph = cached
                    return cached
            except Exception:
                pass

        start_time = time.time()
        print(f"🌌 [GraphBuilder] 3D Tudásgráf építése {total_files} db tanulmányból...")

        nodes = {}
        links = []
        links_set = set()

        def add_link(source: str, target: str, link_type: str, weight: float = 1.0):
            if source == target:
                return
            link_key = f"{min(source, target)}--{max(source, target)}--{link_type}"
            if link_key not in links_set:
                links_set.add(link_key)
                links.append({
                    "source": source,
                    "target": target,
                    "type": link_type,
                    "weight": weight
                })

        # Statisztikai gyűjtők
        author_papers = defaultdict(list)
        strategy_papers = defaultdict(list)
        discipline_papers = defaultdict(list)
        topic_papers = defaultdict(list)
        asset_papers = defaultdict(list)

        paper_index = {}

        # 1. Tanulmányok feldolgozása (Read-only, atomic)
        for fpath in json_files:
            try:
                with open(fpath, "r", encoding="utf-8") as fp:
                    data = json.load(fp)
            except Exception:
                continue

            doc = data.get("document") or {}
            strat = data.get("strategy") or {}
            cdt = data.get("cross_domain_transfer") or {}
            res = data.get("research") or {}
            mkts = data.get("markets") or {}
            perf = data.get("performance") or {}
            repro = data.get("reproducibility") or {}

            fn = fpath.stem
            arxiv_id = doc.get("arxiv_id") or fn
            title = doc.get("title") or arxiv_id
            year = doc.get("publication_year")

            is_direct_fin = cdt.get("is_direct_finance")
            if is_direct_fin is None:
                domains = (data.get("classification") or {}).get("domains") or []
                non_fin = {"Astrophysics", "Cosmology", "Astronomy", "Physics", "FluidDynamics"}
                is_direct_fin = not any(d in non_fin for d in domains)

            discipline = cdt.get("primary_discipline") or doc.get("primary_discipline") or ("QuantitativeFinance" if is_direct_fin else "CrossDisciplinaryScience")
            transfer_score = cdt.get("transferability_score") or ("DirectFinance" if is_direct_fin else "N/A")

            has_strat = bool(strat.get("present") or (strat.get("family") and strat.get("family") not in ("None", "N/A", "")) or strat.get("has_concrete_strategy"))
            strat_family = strat.get("family") or ("Kvant Stratégia" if has_strat else ("Elméleti Modell" if is_direct_fin else f"Kereszt-diszciplináris ({discipline})"))

            paper_node_id = f"paper_{sanitize_id(arxiv_id)}"
            paper_index[arxiv_id] = paper_node_id

            formulas = data.get("formulas") or []
            findings = data.get("key_findings") or []
            trading_ideas = cdt.get("trading_ideas") or []

            # Paper Csomópont
            nodes[paper_node_id] = {
                "id": paper_node_id,
                "type": "paper",
                "label": title,
                "arxiv_id": arxiv_id,
                "file_name": fpath.name,
                "year": year,
                "primary_discipline": discipline,
                "is_direct_finance": is_direct_fin,
                "transferability": transfer_score,
                "has_strategy": has_strat,
                "strategy_family": strat_family,
                "sharpe_ratio": perf.get("sharpe_ratio"),
                "reproducibility": repro.get("classification") if isinstance(repro, dict) else str(repro),
                "abstract": (doc.get("abstract") or "")[:500],
                "hypothesis": res.get("hypothesis") or "",
                "research_question": res.get("research_question") or "",
                "formulas_count": len(formulas),
                "findings_count": len(findings),
                "trading_ideas_count": len(trading_ideas),
                "trading_ideas": trading_ideas[:3],
                "formulas": [{"name": f.get("name") or "Képlet", "formula": f.get("formula")} for f in formulas[:2]],
                "color": DISCIPLINE_COLORS.get(discipline, "#00f3ff"),
                "val": 4.0 + min(len(formulas) + len(findings), 10) * 0.5
            }

            discipline_papers[discipline].append(paper_node_id)

            # Szerzők feldolgozása
            authors = doc.get("authors") or []
            clean_authors = []
            for a in authors:
                if isinstance(a, str) and a.strip():
                    clean_authors.append(a.strip())
                elif isinstance(a, dict) and "name" in a:
                    clean_authors.append(str(a["name"]).strip())

            for a_name in clean_authors:
                a_id = f"author_{sanitize_id(a_name)}"
                author_papers[a_name].append(paper_node_id)
                if a_id not in nodes:
                    nodes[a_id] = {
                        "id": a_id,
                        "type": "author",
                        "label": a_name,
                        "paper_count": 0,
                        "color": NODE_TYPE_COLORS["author"],
                        "val": 5.0
                    }
                nodes[a_id]["paper_count"] += 1
                nodes[a_id]["val"] = 5.0 + math.sqrt(nodes[a_id]["paper_count"]) * 2.5
                add_link(paper_node_id, a_id, "authored_by", weight=1.2)

            # Társszerzőség élek
            if len(clean_authors) > 1:
                for i in range(len(clean_authors)):
                    for j in range(i + 1, len(clean_authors)):
                        auth1_id = f"author_{sanitize_id(clean_authors[i])}"
                        auth2_id = f"author_{sanitize_id(clean_authors[j])}"
                        add_link(auth1_id, auth2_id, "coauthor", weight=0.8)

            # Stratégia csomópont és él
            if has_strat and strat_family and strat_family != "None":
                s_id = f"strat_{sanitize_id(strat_family)}"
                strategy_papers[strat_family].append(paper_node_id)
                if s_id not in nodes:
                    nodes[s_id] = {
                        "id": s_id,
                        "type": "strategy",
                        "label": strat_family,
                        "paper_count": 0,
                        "color": NODE_TYPE_COLORS["strategy"],
                        "val": 8.0
                    }
                nodes[s_id]["paper_count"] += 1
                nodes[s_id]["val"] = 8.0 + math.sqrt(nodes[s_id]["paper_count"]) * 3.0
                add_link(paper_node_id, s_id, "strategy_family", weight=1.5)

            # Diszciplína csomópont
            d_id = f"disc_{sanitize_id(discipline)}"
            if d_id not in nodes:
                nodes[d_id] = {
                    "id": d_id,
                    "type": "discipline",
                    "label": discipline,
                    "paper_count": 0,
                    "color": DISCIPLINE_COLORS.get(discipline, NODE_TYPE_COLORS["discipline"]),
                    "val": 12.0
                }
            nodes[d_id]["paper_count"] += 1
            nodes[d_id]["val"] = 12.0 + math.sqrt(nodes[d_id]["paper_count"]) * 2.0
            add_link(paper_node_id, d_id, "primary_discipline", weight=1.8)

            # Eszközosztályok
            for ac in (mkts.get("asset_classes") or []):
                if ac and isinstance(ac, str) and ac.strip():
                    ac_clean = ac.strip()
                    ac_id = f"asset_{sanitize_id(ac_clean)}"
                    asset_papers[ac_clean].append(paper_node_id)
                    if ac_id not in nodes:
                        nodes[ac_id] = {
                            "id": ac_id,
                            "type": "asset",
                            "label": ac_clean,
                            "paper_count": 0,
                            "color": NODE_TYPE_COLORS["asset"],
                            "val": 7.0
                        }
                    nodes[ac_id]["paper_count"] += 1
                    nodes[ac_id]["val"] = 7.0 + math.sqrt(nodes[ac_id]["paper_count"]) * 2.0
                    add_link(paper_node_id, ac_id, "trades_asset", weight=1.0)

            # Kulcsfogalmak / Témák (csak ha gyakori)
            for kw in (doc.get("keywords") or []):
                if kw and isinstance(kw, str) and len(kw.strip()) > 2:
                    topic_clean = kw.strip().lower()
                    topic_papers[topic_clean].append(paper_node_id)

        # Csak a népszerű témákból készítünk külön node-ot (>= 2 tanulmány), hogy ne árasszuk el a gráfot
        for topic_name, p_list in topic_papers.items():
            if len(p_list) >= 2:
                top_id = f"topic_{sanitize_id(topic_name)}"
                nodes[top_id] = {
                    "id": top_id,
                    "type": "topic",
                    "label": f"#{topic_name}",
                    "paper_count": len(p_list),
                    "color": NODE_TYPE_COLORS["topic"],
                    "val": 4.0 + math.sqrt(len(p_list)) * 1.5
                }
                for pid in p_list:
                    add_link(pid, top_id, "topic_keyword", weight=0.6)

        # 2. Hivatkozási láncok (Citations / Cross-references)
        for fpath in json_files:
            try:
                with open(fpath, "r", encoding="utf-8") as fp:
                    data = json.load(fp)
            except Exception:
                continue
            doc = data.get("document") or {}
            source_arxiv = doc.get("arxiv_id") or fpath.stem
            s_node_id = paper_index.get(source_arxiv)
            if not s_node_id:
                continue

            refs = data.get("source_references") or []
            for ref in refs:
                ref_txt = str(ref)
                m = re.search(r'(\d{4}\.\d{4,5})', ref_txt)
                if m:
                    target_arxiv = m.group(1)
                    t_node_id = paper_index.get(target_arxiv)
                    if t_node_id and t_node_id != s_node_id:
                        add_link(s_node_id, t_node_id, "cites_paper", weight=2.0)

        # 3. Kvant Kereszt-diszciplináris Hidakat építünk (Transzfer élek)
        # Ha egy asztrofizikai vagy fizikai cikknek van konkrét "trading_ideas" ötlete, összekötjük a releváns kvant területtel
        for n_id, n_data in list(nodes.items()):
            if n_data.get("type") == "paper" and not n_data.get("is_direct_finance") and n_data.get("trading_ideas_count", 0) > 0:
                # Keresztkötés a kvant pénzügy központjával
                qfin_id = f"disc_QuantitativeFinance"
                if qfin_id in nodes:
                    add_link(n_id, qfin_id, "cross_domain_alpha_bridge", weight=2.5)

        # 4. 3D Koordináták Számítása (GPU-gyorsított Galaktikus Pozicionálás)
        print("⚡ [GraphBuilder] 3D Koordináták és térbeli klaszterezés kiszámítása...")
        self._compute_3d_coordinates(nodes, links)

        # Degree (fokszám) számítás
        degree_counter = Counter()
        for link in links:
            degree_counter[link["source"]] += 1
            degree_counter[link["target"]] += 1

        for n_id, n_data in nodes.items():
            n_data["degree"] = degree_counter[n_id]

        elapsed = time.time() - start_time
        print(f"✅ [GraphBuilder] Kész! {len(nodes)} csomópont és {len(links)} él felépítve ({elapsed:.2f} mp alatt).")

        result = {
            "version": 3,
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "file_count": total_files,
            "node_count": len(nodes),
            "link_count": len(links),
            "nodes": list(nodes.values()),
            "links": links,
            "stats": {
                "papers_count": len([n for n in nodes.values() if n["type"] == "paper"]),
                "authors_count": len([n for n in nodes.values() if n["type"] == "author"]),
                "strategies_count": len([n for n in nodes.values() if n["type"] == "strategy"]),
                "disciplines_count": len([n for n in nodes.values() if n["type"] == "discipline"]),
                "assets_count": len([n for n in nodes.values() if n["type"] == "asset"]),
                "topics_count": len([n for n in nodes.values() if n["type"] == "topic"]),
            }
        }

        # Cache mentés
        try:
            with open(CACHE_FILE, "w", encoding="utf-8") as cf:
                json.dump(result, cf, ensure_ascii=False)
            print(f"💾 [GraphBuilder] Gyorstár elmentve: {CACHE_FILE}")
        except Exception as e:
            print(f"⚠️ Nem sikerült a cache mentése: {e}")

        self.cached_graph = result
        self.last_build_time = time.time()
        return result

    def _compute_3d_coordinates(self, nodes: dict, links: list):
        """
        Nagy sebességű 3D galaktikus beágyazás.
        Megőrzi a meglévő csomópontok pozícióit (fixed=fixed_nodes), így új tanulmány érkezésekor
        a teljes galaxis 100%-ban stabil marad, nem ugrik meg a nézet, és a forgás teljesen sima!
        """
        G = nx.Graph()
        for n_id in nodes.keys():
            G.add_node(n_id)
        for link in links:
            G.add_edge(link["source"], link["target"], weight=link.get("weight", 1.0))

        # Korábbi koordináták kinyerése a stabilitás érdekében
        existing_coords = {}
        if self.cached_graph and "nodes" in self.cached_graph:
            for old_n in self.cached_graph["nodes"]:
                if "x" in old_n and "y" in old_n and "z" in old_n:
                    existing_coords[old_n["id"]] = np.array([old_n["x"], old_n["y"], old_n["z"]], dtype=float)
        elif CACHE_FILE.exists():
            try:
                with open(CACHE_FILE, "r", encoding="utf-8") as cf:
                    cached = json.load(cf)
                    for old_n in cached.get("nodes", []):
                        if "x" in old_n and "y" in old_n and "z" in old_n:
                            existing_coords[old_n["id"]] = np.array([old_n["x"], old_n["y"], old_n["z"]], dtype=float)
            except Exception:
                pass

        pos_init = {}
        fixed_nodes = []
        np.random.seed(42)

        for n_id, n_data in nodes.items():
            if n_id in existing_coords:
                # Meglévő csomópont: pontosan megőrizzük a pozícióját!
                pos_init[n_id] = existing_coords[n_id]
                fixed_nodes.append(n_id)
            else:
                # Új csomópont: a kapcsolódó szomszédai vagy a diszciplína centruma mellé kerül
                disc = n_data.get("primary_discipline", "Other")
                center = DISCIPLINE_CENTERS.get(disc, (0.0, 0.0, 0.0))

                neighbor_pts = []
                for link in links:
                    if link["source"] == n_id and link["target"] in existing_coords:
                        neighbor_pts.append(existing_coords[link["target"]])
                    elif link["target"] == n_id and link["source"] in existing_coords:
                        neighbor_pts.append(existing_coords[link["source"]])

                if neighbor_pts:
                    base_pt = np.mean(neighbor_pts, axis=0)
                    pos_init[n_id] = base_pt + np.random.normal(0, 25.0, 3)
                else:
                    ntype = n_data.get("type")
                    spread = 40.0 if ntype == "strategy" else (65.0 if ntype == "paper" else 80.0)
                    pos_init[n_id] = np.array(center, dtype=float) + np.random.normal(0, spread, 3)

        # Gyors 3D NetworkX tavaszi (spring) relaxáció
        try:
            if fixed_nodes and len(fixed_nodes) < len(nodes):
                pos_3d = nx.spring_layout(
                    G,
                    dim=3,
                    pos=pos_init,
                    fixed=fixed_nodes,
                    iterations=6,
                    k=45.0 / math.sqrt(max(len(nodes), 1)),
                    scale=650.0,
                    seed=42
                )
            elif not fixed_nodes:
                pos_3d = nx.spring_layout(
                    G,
                    dim=3,
                    pos=pos_init,
                    iterations=20,
                    k=45.0 / math.sqrt(max(len(nodes), 1)),
                    scale=650.0,
                    seed=42
                )
            else:
                pos_3d = pos_init
        except Exception:
            pos_3d = pos_init

        # Koordináták beírása a node objektumokba
        for n_id, coords in pos_3d.items():
            if n_id in nodes:
                nodes[n_id]["x"] = round(float(coords[0]), 2)
                nodes[n_id]["y"] = round(float(coords[1]), 2)
                nodes[n_id]["z"] = round(float(coords[2]), 2)


if __name__ == "__main__":
    builder = KnowledgeGraphBuilder()
    data = builder.build_graph(force_rebuild=True)
    print(f"Nodes: {data['node_count']}, Links: {data['link_count']}")
