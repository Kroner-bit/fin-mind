"""
server.py
Önálló, nagy sebességű FastAPI Web Szerver a 3D Tudásgráf Megjelenítőhöz.
Kizárólag a 8050-es porton fut, teljesen független a 8000-es web apptól és a háttérben futó PDF feldolgozótól.
"""

import sys
import os
import json
import argparse
import asyncio
from pathlib import Path
from typing import Optional, List

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import uvicorn
from fastapi import FastAPI, HTTPException, Query, BackgroundTasks
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from graph_builder import KnowledgeGraphBuilder, DISCIPLINE_COLORS, NODE_TYPE_COLORS

BASE_DIR = Path(__file__).parent.resolve()
WEB_DIR = BASE_DIR / "web"

app = FastAPI(
    title="FinMind 3D Knowledge Graph Studio",
    description="GPU-gyorsított interaktív 3D tudásgráf vizualizáció",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Builder inicializálása
builder = KnowledgeGraphBuilder()

# ─── API Végpontok ──────────────────────────────────────────

@app.get("/api/status")
async def get_status():
    """Rendszerállapot és memória statisztikák."""
    g = builder.build_graph(force_rebuild=False)
    return {
        "status": "online",
        "file_count": g.get("file_count", 0),
        "node_count": g.get("node_count", 0),
        "link_count": g.get("link_count", 0),
        "generated_at": g.get("generated_at"),
        "discipline_colors": DISCIPLINE_COLORS,
        "type_colors": NODE_TYPE_COLORS
    }

@app.get("/api/stats")
async def get_stats():
    """Részletes gráfelemzési és eloszlási statisztikák a HUD kijelzőhöz."""
    g = builder.build_graph(force_rebuild=False)
    return {
        "stats": g.get("stats", {}),
        "total_nodes": g.get("node_count", 0),
        "total_links": g.get("link_count", 0),
        "file_count": g.get("file_count", 0)
    }

@app.get("/api/graph")
async def get_graph(
    types: Optional[str] = Query(None, description="Vesszővel elválasztott típusok: paper,author,strategy,discipline,topic,asset"),
    discipline: Optional[str] = Query(None, description="Szűrés elsődleges tudományágra"),
    min_degree: int = Query(0, description="Minimális kapcsolati fokszám"),
    search: Optional[str] = Query(None, description="Keresési kifejezés címre vagy névre"),
    limit: Optional[int] = Query(None, description="Maximális csomópontszám")
):
    """
    3D Csomópontok és élek lekérdezése szűréssel és koordinátákkal.
    A böngésző Three.js motorja közvetlenül a GPU-ba tölti ezeket a pontokat.
    """
    g = builder.build_graph(force_rebuild=False)
    all_nodes = g.get("nodes", [])
    all_links = g.get("links", [])

    # Típus szűrés
    allowed_types = set(types.split(",")) if types else None

    # Keresési minta
    search_lower = search.strip().lower() if search else None

    filtered_nodes = []
    filtered_node_ids = set()

    for node in all_nodes:
        # Típus szűrés
        if allowed_types and node.get("type") not in allowed_types:
            continue

        # Diszciplína szűrés (főleg paper típusra)
        if discipline and node.get("primary_discipline") != discipline and node.get("type") == "paper":
            continue

        # Fokszám szűrés
        if min_degree > 0 and node.get("degree", 0) < min_degree:
            # A diszciplína és stratégia hub-okat mindig megtartjuk viszonyítási pontként
            if node.get("type") not in ("discipline", "strategy"):
                continue

        # Szöveges keresés
        if search_lower:
            label = str(node.get("label", "")).lower()
            arxiv_id = str(node.get("arxiv_id", "")).lower()
            if search_lower not in label and search_lower not in arxiv_id:
                continue

        filtered_nodes.append(node)
        filtered_node_ids.add(node["id"])

        if limit and len(filtered_nodes) >= limit:
            break

    # Élek szűrése: csak azok az élek kellenek, amelyeknek mindkét végpontja a megjelenítendő csomópontok között van
    filtered_links = []
    for link in all_links:
        src = link["source"]
        tgt = link["target"]
        if src in filtered_node_ids and tgt in filtered_node_ids:
            filtered_links.append(link)

    return {
        "nodes": filtered_nodes,
        "links": filtered_links,
        "total_nodes": len(filtered_nodes),
        "total_links": len(filtered_links)
    }

@app.get("/api/node/{node_id}")
async def get_node_details(node_id: str):
    """Kiválasztott csomópont mély dossziéja (backlinkekkel és képletekkel)."""
    g = builder.build_graph(force_rebuild=False)
    nodes_by_id = {n["id"]: n for n in g.get("nodes", [])}
    node = nodes_by_id.get(node_id)
    if not node:
        raise HTTPException(status_code=404, detail="Csomópont nem található")

    # Kapcsolódó szomszédok (Backlinks) felderítése
    connected_neighbors = []
    for link in g.get("links", []):
        other_id = None
        role = link.get("type", "connected")
        if link["source"] == node_id:
            other_id = link["target"]
        elif link["target"] == node_id:
            other_id = link["source"]

        if other_id and other_id in nodes_by_id:
            other_node = nodes_by_id[other_id]
            connected_neighbors.append({
                "id": other_id,
                "label": other_node.get("label"),
                "type": other_node.get("type"),
                "color": other_node.get("color"),
                "link_type": role
            })

    return {
        "node": node,
        "backlinks": connected_neighbors,
        "backlink_count": len(connected_neighbors)
    }

@app.post("/api/sync")
async def sync_graph(background_tasks: BackgroundTasks):
    """Újraolvassa a legújabb JSON-öket és frissíti a 3D gráfot a háttérben."""
    def run_rebuild():
        builder.build_graph(force_rebuild=True)

    background_tasks.add_task(run_rebuild)
    return {"status": "sync_started", "message": "3D gráf újraszámítása elindult a háttérben..."}

# Statikus fájlok kiszolgálása a web/ mappából
if WEB_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")

@app.get("/", response_class=FileResponse)
async def serve_index():
    index_file = WEB_DIR / "index.html"
    if index_file.exists():
        return FileResponse(index_file)
    return HTMLResponse("<h1>3D Graph Viewer Frontend betöltés alatt...</h1>")

# ─── Szerver indító ──────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="FinMind 3D Knowledge Graph Server")
    parser.add_argument("--host", default="0.0.0.0", help="Hálózati cím (alapértelmezett: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8050, help="Port (alapértelmezett: 8050, hogy soha ne ütközzön a 8000-rel)")
    args = parser.parse_args()

    print("=" * 68)
    print("🌌 FINMIND - 3D GPU KNOWLEDGE GRAPH STUDIO")
    print("=" * 68)
    print(f"🚀 Szerver fut: http://localhost:{args.port}")
    print(f"📁 Forrás JSON könyvtár: {builder.json_dir}")
    print(f"🎮 3D WebGL Frontend elérhető a böngészőben!")
    print(f"⚡ Párhuzamosan futhat a háttérben dolgozó fő PDF processzorral.")
    print("=" * 68)

    # Előzetes gyors gráfbetöltés indításkor
    builder.build_graph(force_rebuild=False)

    uvicorn.run(app, host=args.host, port=args.port, log_level="info")

if __name__ == "__main__":
    main()
