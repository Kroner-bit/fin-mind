/**
 * app.js
 * FinMind 3D Knowledge Graph Studio - Fő Alkalmazásvezérlő
 * Összeköti a Three.js GPU Motort a Cyberpunk HUD felülettel és a FastAPI backenddel.
 */

document.addEventListener('DOMContentLoaded', () => {
  // DOM Referenciák
  const el = {
    dispFps: document.getElementById('disp-fps'),
    dispNodes: document.getElementById('disp-nodes'),
    dispLinks: document.getElementById('disp-links'),
    dispCluster: document.getElementById('disp-cluster'),
    chipCluster: document.getElementById('chip-cluster'),
    
    inputSearch: document.getElementById('input-search'),
    btnClearSearch: document.getElementById('btn-clear-search'),
    searchDropdown: document.getElementById('search-autocomplete-dropdown'),
    
    btnSyncGraph: document.getElementById('btn-sync-graph'),
    btnToggleHud: document.getElementById('btn-toggle-hud'),
    
    controlsPanel: document.getElementById('controls-panel'),
    btnCollapseControls: document.getElementById('btn-collapse-controls'),
    
    modeButtons: document.querySelectorAll('.btn-mode'),
    filterChips: document.querySelectorAll('.filter-chip'),
    selDiscipline: document.getElementById('sel-discipline'),
    
    sliderMinDegree: document.getElementById('slider-min-degree'),
    valMinDegree: document.getElementById('val-min-degree'),
    
    sliderLinkOpacity: document.getElementById('slider-link-opacity'),
    valLinkOpacity: document.getElementById('val-link-opacity'),
    
    toggleBloom: document.getElementById('toggle-bloom'),
    toggleAutoRotate: document.getElementById('toggle-autorotate'),
    toggleStarfield: document.getElementById('toggle-starfield'),
    
    btnResetCamera: document.getElementById('btn-reset-camera'),
    btnIsolateSelection: document.getElementById('btn-isolate-selection'),
    
    inspectorDrawer: document.getElementById('inspector-drawer'),
    btnCloseInspector: document.getElementById('btn-close-inspector'),
    inspectorBadge: document.getElementById('inspector-badge'),
    inspectorTitle: document.getElementById('inspector-title'),
    inspectorMeta: document.getElementById('inspector-meta'),
    
    inspectorTransferCard: document.getElementById('inspector-transfer-card'),
    inspectorTransferScore: document.getElementById('inspector-transfer-score'),
    inspectorTransferBody: document.getElementById('inspector-transfer-body'),
    
    inspectorBacklinkCount: document.getElementById('inspector-backlink-count'),
    inspectorBacklinksChips: document.getElementById('inspector-backlinks-chips'),
    
    inspectorFormulasSection: document.getElementById('inspector-formulas-section'),
    inspectorFormulasWrap: document.getElementById('inspector-formulas-wrap'),
    
    inspectorAbstractSection: document.getElementById('inspector-abstract-section'),
    inspectorAbstract: document.getElementById('inspector-abstract'),
    
    btnFlyToSelected: document.getElementById('btn-flyto-selected'),
    btnOpenArxiv: document.getElementById('btn-open-arxiv'),
    
    hoverTooltip: document.getElementById('hover-tooltip'),
    tooltipType: document.getElementById('tooltip-type'),
    tooltipTitle: document.getElementById('tooltip-title'),
    tooltipMeta: document.getElementById('tooltip-meta')
  };

  // Állapotkezelés
  const state = {
    colorMode: 'discipline',
    activeTypes: new Set(['paper', 'author', 'strategy', 'discipline', 'topic', 'asset']),
    selectedDiscipline: '',
    minDegree: 0,
    linkOpacity: 0.4,
    allNodesCache: [],
    selectedNode: null
  };

  // 3D Motor Inicializálása
  const engine = new GraphEngine3D('canvas-container', {
    bloomEnabled: true,
    starfieldEnabled: true,
    autoRotate: false,
    linkOpacity: state.linkOpacity,
    colorMode: state.colorMode
  });

  // FPS Frissítés
  engine.onFpsUpdate = (fps) => {
    el.dispFps.textContent = fps;
    if (fps >= 50) {
      el.dispFps.className = 'metric-value fps-good';
    } else if (fps >= 30) {
      el.dispFps.className = 'metric-value';
      el.dispFps.style.color = '#fbbf24';
    } else {
      el.dispFps.className = 'metric-value';
      el.dispFps.style.color = '#f43f5e';
    }
  };

  // Hover Eseménykezelő
  engine.onNodeHover = (node, intersect) => {
    if (!node) {
      el.hoverTooltip.style.display = 'none';
      return;
    }

    el.tooltipType.textContent = node.type.toUpperCase();
    el.tooltipTitle.textContent = node.label || node.id;

    let metaParts = [];
    if (node.type === 'paper') {
      if (node.year) metaParts.push(`Év: ${node.year}`);
      if (node.primary_discipline) metaParts.push(node.primary_discipline);
      if (node.has_strategy) metaParts.push(`⚡ ${node.strategy_family}`);
    } else if (node.type === 'author') {
      metaParts.push(`${node.paper_count || 1} publikáció`);
    } else if (node.type === 'strategy') {
      metaParts.push(`${node.paper_count || 1} tanulmány`);
    }
    metaParts.push(`Kapcsolatok: ${node.degree || 0}`);

    el.tooltipMeta.textContent = metaParts.join(' • ');

    if (intersect && intersect.point) {
      // Vetítsük a 3D pozíciót 2D képernyő koordinátákra
      const pos = intersect.point.clone();
      pos.project(engine.camera);

      const x = (pos.x * 0.5 + 0.5) * window.innerWidth;
      const y = (-(pos.y * 0.5) + 0.5) * window.innerHeight;

      el.hoverTooltip.style.left = `${Math.min(x + 15, window.innerWidth - 300)}px`;
      el.hoverTooltip.style.top = `${Math.min(y + 15, window.innerHeight - 150)}px`;
      el.hoverTooltip.style.display = 'block';
    }
  };

  // Kattintás Csomópontra (Inspector Megnyitása)
  engine.onNodeClick = (node) => {
    openInspector(node.id);
  };

  // ─── API Lekérdezések ────────────────────────────────────────

  async function fetchGraph() {
    try {
      const typesParam = Array.from(state.activeTypes).join(',');
      const params = new URLSearchParams({
        types: typesParam,
        min_degree: state.minDegree
      });

      if (state.selectedDiscipline) {
        params.append('discipline', state.selectedDiscipline);
      }

      const res = await fetch(`/api/graph?${params.toString()}`);
      if (!res.ok) throw new Error("Hiba a gráf lekérésekor");

      const data = await res.json();
      state.allNodesCache = data.nodes || [];

      el.dispNodes.textContent = Number(data.total_nodes || 0).toLocaleString();
      el.dispLinks.textContent = Number(data.total_links || 0).toLocaleString();

      engine.setGraphData(data);
    } catch (e) {
      console.error("Gráf lekérdezési hiba:", e);
    }
  }

  async function openInspector(nodeId) {
    try {
      const res = await fetch(`/api/node/${encodeURIComponent(nodeId)}`);
      if (!res.ok) throw new Error("Csomópont nem található");

      const data = await res.json();
      const node = data.node;
      state.selectedNode = node;

      el.inspectorBadge.textContent = node.type.toUpperCase();
      el.inspectorBadge.style.color = engine.getNodeColor(node);
      el.inspectorBadge.style.borderColor = engine.getNodeColor(node);

      el.inspectorTitle.textContent = node.label || node.id;

      // Meta adatok összeállítása
      let metaHtml = '';
      if (node.arxiv_id) metaHtml += `<span class="meta-pill">arXiv: ${escapeHtml(node.arxiv_id)}</span>`;
      if (node.year) metaHtml += `<span class="meta-pill">Év: ${node.year}</span>`;
      if (node.primary_discipline) metaHtml += `<span class="meta-pill" style="color: #00f3ff;">${escapeHtml(node.primary_discipline)}</span>`;
      if (node.strategy_family && node.strategy_family !== 'None') {
        metaHtml += `<span class="meta-pill" style="color: #f43f5e;">⚡ ${escapeHtml(node.strategy_family)}</span>`;
      }
      if (node.paper_count) metaHtml += `<span class="meta-pill">📚 ${node.paper_count} tanulmány</span>`;
      el.inspectorMeta.innerHTML = metaHtml;

      // Kereszt-diszciplináris transzfer ötletek (ha léteznek)
      const ideas = node.trading_ideas || [];
      if (ideas.length > 0 || (node.type === 'paper' && !node.is_direct_finance)) {
        el.inspectorTransferScore.textContent = node.transferability || 'HIGH';
        let bodyHtml = '';
        if (ideas.length > 0) {
          bodyHtml += `<div style="font-weight: 600; color: #10b981; margin-bottom: 6px;">Átvehető Piaci Alfa Hipotézisek:</div>`;
          for (let idea of ideas) {
            const title = typeof idea === 'object' ? (idea.title || idea.idea_name || 'Ötlet') : idea;
            const hyp = typeof idea === 'object' ? (idea.hypothesis || '') : '';
            const impl = typeof idea === 'object' ? (idea.suggested_implementation || idea.implementation_sketch || '') : '';
            bodyHtml += `
              <div style="background: rgba(0,0,0,0.3); padding: 8px 10px; border-radius: 6px; margin-bottom: 6px; border-left: 2px solid #10b981;">
                <strong style="color: #fff;">${escapeHtml(title)}</strong>
                ${hyp ? `<div style="color: #ccc; font-size: 0.75rem; margin-top: 2px;">${escapeHtml(hyp)}</div>` : ''}
                ${impl ? `<div style="color: #94a3b8; font-size: 0.7rem; margin-top: 4px; font-style: italic;">Megvalósítás: ${escapeHtml(impl)}</div>` : ''}
              </div>
            `;
          }
        } else {
          bodyHtml += `<div>Ez egy kereszt-diszciplináris természettudományos tanulmány (${escapeHtml(node.primary_discipline || '')}), amely analógiákat és matematikai eszközöket biztosít a kvant kutatásokhoz.</div>`;
        }
        el.inspectorTransferBody.innerHTML = bodyHtml;
        el.inspectorTransferCard.style.display = 'block';
      } else {
        el.inspectorTransferCard.style.display = 'none';
      }

      // Backlinkek megjelenítése
      const backlinks = data.backlinks || [];
      el.inspectorBacklinkCount.textContent = backlinks.length;
      let chipsHtml = '';
      for (let bl of backlinks) {
        chipsHtml += `
          <div class="backlink-chip" data-node-id="${escapeHtml(bl.id)}" title="${escapeHtml(bl.label || bl.id)}">
            <span class="chip-color" style="background: ${bl.color || '#00f3ff'};"></span>
            <span>${escapeHtml(bl.label || bl.id)}</span>
          </div>
        `;
      }
      el.inspectorBacklinksChips.innerHTML = chipsHtml || '<span style="color: #64748b; font-size: 0.75rem;">Nincsenek közvetlen kapcsolatok.</span>';

      // Backlink kattintás esemény
      el.inspectorBacklinksChips.querySelectorAll('.backlink-chip').forEach(chip => {
        chip.addEventListener('click', () => {
          const targetId = chip.getAttribute('data-node-id');
          if (targetId) {
            engine.flyToNode(targetId);
            openInspector(targetId);
          }
        });
      });

      // Képletek
      const formulas = node.formulas || [];
      if (formulas.length > 0) {
        let fHtml = '';
        for (let f of formulas) {
          fHtml += `
            <div style="background: rgba(0,0,0,0.3); padding: 8px 10px; border-radius: 6px; margin-bottom: 6px;">
              <div style="font-weight: 600; color: #38bdf8; font-size: 0.75rem;">${escapeHtml(f.name || 'Képlet')}</div>
              <div style="font-family: monospace; color: #fff; margin-top: 4px; overflow-x: auto;">${escapeHtml(f.formula || '')}</div>
            </div>
          `;
        }
        el.inspectorFormulasWrap.innerHTML = fHtml;
        el.inspectorFormulasSection.style.display = 'block';
      } else {
        el.inspectorFormulasSection.style.display = 'none';
      }

      // Kivonat / Abstract
      if (node.abstract) {
        el.inspectorAbstract.textContent = node.abstract;
        el.inspectorAbstractSection.style.display = 'block';
      } else {
        el.inspectorAbstractSection.style.display = 'none';
      }

      // arXiv Gomb
      if (node.arxiv_id && node.type === 'paper') {
        el.btnOpenArxiv.href = `https://arxiv.org/abs/${encodeURIComponent(node.arxiv_id)}`;
        el.btnOpenArxiv.style.display = 'inline-flex';
      } else {
        el.btnOpenArxiv.style.display = 'none';
      }

      el.inspectorDrawer.classList.add('open');
    } catch (e) {
      console.error("Inspector betöltési hiba:", e);
    }
  }

  // ─── Keresés & Autocomplete ──────────────────────────────────

  let searchDebounceTimer = null;
  el.inputSearch.addEventListener('input', () => {
    clearTimeout(searchDebounceTimer);
    const query = el.inputSearch.value.trim().toLowerCase();
    el.btnClearSearch.style.display = query ? 'block' : 'none';

    if (!query) {
      el.searchDropdown.classList.remove('open');
      return;
    }

    searchDebounceTimer = setTimeout(() => {
      // Helyi gyors szűrés a memóriában lévő csomópontokból
      const matches = state.allNodesCache.filter(n => {
        const lbl = (n.label || '').toLowerCase();
        const ax = (n.arxiv_id || '').toLowerCase();
        return lbl.includes(query) || ax.includes(query);
      }).slice(0, 12);

      if (matches.length === 0) {
        el.searchDropdown.innerHTML = '<div style="padding: 0.75rem; color: #64748b; font-size: 0.8rem;">Nincs találat.</div>';
        el.searchDropdown.classList.add('open');
        return;
      }

      let dropdownHtml = '';
      for (let m of matches) {
        const typeCol = engine.getNodeColor(m);
        dropdownHtml += `
          <div class="autocomplete-item" data-node-id="${escapeHtml(m.id)}">
            <div class="item-left">
              <span class="item-type-badge" style="background: rgba(255,255,255,0.1); color: ${typeCol};">${escapeHtml(m.type)}</span>
              <span class="item-label">${escapeHtml(m.label || m.id)}</span>
            </div>
            <div class="item-right">${m.year || (m.paper_count ? `${m.paper_count} cikk` : '')}</div>
          </div>
        `;
      }
      el.searchDropdown.innerHTML = dropdownHtml;
      el.searchDropdown.classList.add('open');

      el.searchDropdown.querySelectorAll('.autocomplete-item').forEach(item => {
        item.addEventListener('click', () => {
          const targetId = item.getAttribute('data-node-id');
          if (targetId) {
            engine.flyToNode(targetId);
            openInspector(targetId);
            el.searchDropdown.classList.remove('open');
          }
        });
      });
    }, 150);
  });

  el.btnClearSearch.addEventListener('click', () => {
    el.inputSearch.value = '';
    el.btnClearSearch.style.display = 'none';
    el.searchDropdown.classList.remove('open');
  });

  window.addEventListener('keydown', (e) => {
    if (e.key === '/' && document.activeElement !== el.inputSearch) {
      e.preventDefault();
      el.inputSearch.focus();
      el.inputSearch.select();
    }
    if (e.key === 'Escape') {
      el.searchDropdown.classList.remove('open');
      el.inspectorDrawer.classList.remove('open');
      engine.highlightNeighborhood(null);
    }
  });

  // ─── UI Vezérlők Eseménykezelése ─────────────────────────────

  // Színezési mód váltás
  el.modeButtons.forEach(btn => {
    btn.addEventListener('click', () => {
      el.modeButtons.forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      state.colorMode = btn.getAttribute('data-mode') || 'discipline';
      engine.options.colorMode = state.colorMode;
      engine.rebuildNodeMesh();
      engine.rebuildLinkMesh();
    });
  });

  // Típus szűrők (checkbox)
  el.filterChips.forEach(chip => {
    const cb = chip.querySelector('input');
    chip.addEventListener('click', (e) => {
      if (e.target !== cb) {
        cb.checked = !cb.checked;
      }
      chip.classList.toggle('active', cb.checked);
      
      const typeVal = chip.getAttribute('data-type');
      if (cb.checked) {
        state.activeTypes.add(typeVal);
      } else {
        state.activeTypes.delete(typeVal);
      }
      fetchGraph();
    });
  });

  // Diszciplína szűrés
  el.selDiscipline.addEventListener('change', () => {
    state.selectedDiscipline = el.selDiscipline.value;
    fetchGraph();
  });

  // Minimális fokszám csúszka
  el.sliderMinDegree.addEventListener('input', () => {
    state.minDegree = parseInt(el.sliderMinDegree.value, 10);
    el.valMinDegree.textContent = state.minDegree;
  });
  el.sliderMinDegree.addEventListener('change', () => {
    fetchGraph();
  });

  // Élek átlátszósága
  el.sliderLinkOpacity.addEventListener('input', () => {
    state.linkOpacity = parseInt(el.sliderLinkOpacity.value, 10) / 100.0;
    el.valLinkOpacity.textContent = `${Math.round(state.linkOpacity * 100)}%`;
    engine.options.linkOpacity = state.linkOpacity;
    if (engine.linkSegments) {
      engine.linkSegments.material.opacity = state.linkOpacity;
    }
  });

  // Bloom Toggle
  el.toggleBloom.addEventListener('change', () => {
    engine.options.bloomEnabled = el.toggleBloom.checked;
  });

  // Auto-rotate Toggle
  el.toggleAutoRotate.addEventListener('change', () => {
    engine.controls.autoRotate = el.toggleAutoRotate.checked;
  });

  // Starfield Toggle
  el.toggleStarfield.addEventListener('change', () => {
    if (engine.starfield) {
      engine.starfield.visible = el.toggleStarfield.checked;
    }
  });

  // Kamera Reset
  el.btnResetCamera.addEventListener('click', () => {
    engine.resetCamera();
  });

  // Izolálás gomb
  el.btnIsolateSelection.addEventListener('click', () => {
    if (state.selectedNode) {
      engine.flyToNode(state.selectedNode.id);
    }
  });

  // Inspector Bezárás
  el.btnCloseInspector.addEventListener('click', () => {
    el.inspectorDrawer.classList.remove('open');
    engine.highlightNeighborhood(null);
  });

  // Odarepülés Gomb az Inspectorban
  el.btnFlyToSelected.addEventListener('click', () => {
    if (state.selectedNode) {
      engine.flyToNode(state.selectedNode.id);
    }
  });

  // Vezérlőpanel összecsukása
  el.btnCollapseControls.addEventListener('click', () => {
    el.controlsPanel.classList.toggle('collapsed');
    el.btnCollapseControls.textContent = el.controlsPanel.classList.contains('collapsed') ? '▶' : '◀';
  });

  // HUD Elrejtése
  let hudVisible = true;
  el.btnToggleHud.addEventListener('click', () => {
    hudVisible = !hudVisible;
    el.controlsPanel.style.display = hudVisible ? 'flex' : 'none';
    el.inspectorDrawer.style.display = hudVisible ? 'flex' : 'none';
  });

  // Sync gomb (háttérbeli frissítés)
  el.btnSyncGraph.addEventListener('click', async () => {
    el.btnSyncGraph.disabled = true;
    el.btnSyncGraph.querySelector('span:last-child').textContent = 'Szinkronizálás...';
    try {
      await fetch('/api/sync', { method: 'POST' });
      setTimeout(async () => {
        await fetchGraph();
        el.btnSyncGraph.disabled = false;
        el.btnSyncGraph.querySelector('span:last-child').textContent = 'Sync Új JSON-ök';
      }, 1500);
    } catch (e) {
      el.btnSyncGraph.disabled = false;
      el.btnSyncGraph.querySelector('span:last-child').textContent = 'Sync Új JSON-ök';
    }
  });

  // Segédfüggvény: Biztonságos HTML escaping
  function escapeHtml(str) {
    if (!str) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  }

  // Kezdeti adatbetöltés
  fetchGraph();
});
