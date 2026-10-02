/**
 * app.js
 * FinMind 3D Knowledge Universe - Apple Pro Matte Live Controller
 * Letisztult lebegő üvegmenü, 60 FPS kijelző, automatikus háttérszinkronizáció,
 * zenei kozmikus hang-effekt (Web Audio API) és sima, ugrásmentes galaxis-forgás.
 */

document.addEventListener('DOMContentLoaded', () => {
  // DOM Hivatkozások
  const el = {
    dispFps: document.getElementById('disp-fps'),
    dispNodes: document.getElementById('disp-nodes'),
    liveDot: document.getElementById('live-dot'),

    btnToggleSync: document.getElementById('btn-toggle-sync'),
    labelSync: document.getElementById('label-sync'),

    btnToggleRotate: document.getElementById('btn-toggle-rotate'),
    labelRotate: document.getElementById('label-rotate'),

    btnToggleSound: document.getElementById('btn-toggle-sound'),
    soundIcon: document.getElementById('sound-icon'),

    btnResetView: document.getElementById('btn-reset-view'),

    // Hover Tooltip
    hoverTooltip: document.getElementById('hover-tooltip'),
    tooltipBadge: document.getElementById('tooltip-badge'),
    tooltipTitle: document.getElementById('tooltip-title'),
    tooltipSub: document.getElementById('tooltip-sub'),

    // Arrival Toast
    arrivalToast: document.getElementById('arrival-toast'),
    toastTitle: document.getElementById('toast-title')
  };

  // Állapot
  let currentFileCount = 0;
  let knownNodeIds = new Set();
  let isAutoSyncEnabled = true;
  let isRotating = true;
  let isSoundEnabled = true;
  let isInitialLoad = true;
  let toastTimer = null;

  // 3D Motor Inicializálása (Apple Pro Matte háttér és sima folyamatos forgás)
  const engine = new GraphEngine3D('canvas-container', {
    autoRotate: true,
    autoRotateSpeed: 0.35,
    linkOpacity: 0.18,
    backgroundColor: 0x121214
  });

  // ─── Web Audio API Hangszintetizátor (Ethereal Cosmic Chime) ──
  let audioCtx = null;

  function getAudioContext() {
    if (!audioCtx) {
      const AudioContextClass = window.AudioContext || window.webkitAudioContext;
      if (AudioContextClass) {
        audioCtx = new AudioContextClass();
      }
    }
    if (audioCtx && audioCtx.state === 'suspended') {
      audioCtx.resume();
    }
    return audioCtx;
  }

  // Felhasználói kattintásra / billentyűleütésre azonnal feloldjuk az AudioContext-et
  window.addEventListener('pointerdown', () => getAudioContext(), { once: true });
  window.addEventListener('keydown', () => getAudioContext(), { once: true });

  function playCosmicChime() {
    if (!isSoundEnabled) return;
    try {
      const ctx = getAudioContext();
      if (!ctx) return;

      const now = ctx.currentTime;

      // Master gain: lágy, prémium, nem tolakodó hangerő
      const master = ctx.createGain();
      master.gain.setValueAtTime(0.12, now);
      master.gain.exponentialRampToValueAtTime(0.0001, now + 2.5);
      master.connect(ctx.destination);

      // Ethereal lebegő felhangok (D-dúr pentaton csillag-akkord: 587Hz D5, 740Hz F#5, 880Hz A5, 1175Hz D6)
      const harmonics = [587.33, 739.99, 880.00, 1174.66];
      harmonics.forEach((freq, idx) => {
        const osc = ctx.createOscillator();
        const gain = ctx.createGain();

        osc.type = idx === 0 ? 'sine' : 'triangle';
        const startTime = now + idx * 0.045; // Finom arpeggio késleltetés
        osc.frequency.setValueAtTime(freq, startTime);

        gain.gain.setValueAtTime(0.0001, startTime);
        gain.gain.exponentialRampToValueAtTime(0.28 / (idx + 1), startTime + 0.035);
        gain.gain.exponentialRampToValueAtTime(0.0001, startTime + 1.8 + idx * 0.12);

        osc.connect(gain);
        gain.connect(master);

        osc.start(startTime);
        osc.stop(startTime + 2.1);
      });

      // Magas csillogó fénycsengő (Shimmer Sparkle: 1760Hz A6)
      const sparkle = ctx.createOscillator();
      const sparkleGain = ctx.createGain();
      sparkle.type = 'sine';
      sparkle.frequency.setValueAtTime(1760.0, now + 0.14);

      sparkleGain.gain.setValueAtTime(0.0001, now + 0.14);
      sparkleGain.gain.exponentialRampToValueAtTime(0.08, now + 0.18);
      sparkleGain.gain.exponentialRampToValueAtTime(0.0001, now + 1.3);

      sparkle.connect(sparkleGain);
      sparkleGain.connect(master);

      sparkle.start(now + 0.14);
      sparkle.stop(now + 1.4);

    } catch (e) {
      console.warn("AudioContext hanghiba:", e);
    }
  }

  // ─── FPS Kijelző Callback ────────────────────────────────────
  engine.onFpsUpdate = (fps) => {
    if (!el.dispFps) return;
    el.dispFps.textContent = `${fps} FPS`;
    if (fps >= 50) {
      el.dispFps.style.color = 'var(--apple-green, #30D158)';
    } else if (fps >= 30) {
      el.dispFps.style.color = 'var(--apple-amber, #FF9F0A)';
    } else {
      el.dispFps.style.color = 'var(--apple-red, #FF453A)';
    }
  };

  // ─── Minimalista Lebegő Hover Tooltip ─────────────────────────
  engine.onNodeHover = (node, intersect) => {
    if (!el.hoverTooltip) return;

    if (!node) {
      el.hoverTooltip.style.display = 'none';
      return;
    }

    const typeName = (node.type || 'csomópont').toUpperCase();
    el.tooltipBadge.textContent = typeName;
    el.tooltipBadge.style.color = node.color || '#0A84FF';

    el.tooltipTitle.textContent = node.label || node.id;

    const metaParts = [];
    if (node.type === 'paper') {
      if (node.year) metaParts.push(node.year);
      if (node.primary_discipline) metaParts.push(node.primary_discipline);
      if (node.strategy_family && node.strategy_family !== 'None') {
        metaParts.push(`⚡ ${node.strategy_family}`);
      }
    } else if (node.type === 'author') {
      metaParts.push(`${node.paper_count || 1} publikáció`);
    } else if (node.type === 'strategy') {
      metaParts.push(`Kvant Stratégia`);
    } else if (node.type === 'discipline') {
      metaParts.push('Fő Tudományág');
    }
    if (node.degree) {
      metaParts.push(`${node.degree} kapcsolat`);
    }

    el.tooltipSub.textContent = metaParts.join(' • ');

    if (intersect && intersect.point) {
      const pos = intersect.point.clone();
      pos.project(engine.camera);

      const x = (pos.x * 0.5 + 0.5) * window.innerWidth;
      const y = (-(pos.y * 0.5) + 0.5) * window.innerHeight;

      el.hoverTooltip.style.left = `${Math.min(x + 14, window.innerWidth - 340)}px`;
      el.hoverTooltip.style.top = `${Math.min(y + 14, window.innerHeight - 120)}px`;
      el.hoverTooltip.style.display = 'block';
    }
  };

  // ─── Érkezési Értesítés (Toast + Hang) Megjelenítése ──────────
  function showArrivalToast(title, extraCount = 0) {
    // Megszólaltatjuk az éteri kozmikus hang-effektet
    playCosmicChime();

    if (!el.arrivalToast || !el.toastTitle) return;

    clearTimeout(toastTimer);

    let displayTitle = title || 'Új tudományos bejegyzés';
    if (extraCount > 0) {
      displayTitle += ` (+${extraCount} kapcsolódó entitás)`;
    }

    el.toastTitle.textContent = displayTitle;
    el.arrivalToast.style.display = 'flex';

    // 4 másodperc múlva automatikusan elhalványul
    toastTimer = setTimeout(() => {
      el.arrivalToast.style.display = 'none';
    }, 4200);
  }

  // ─── Automatikus Szinkronizáció & Frissítés Ciklus ────────────
  async function pollUpdates() {
    if (!isAutoSyncEnabled && !isInitialLoad) return;

    try {
      const res = await fetch(`/api/check-updates?since_count=${currentFileCount}`);
      if (!res.ok) return;

      const data = await res.json();

      if (isInitialLoad) {
        // Első betöltés: ha van gráf adat a válaszban
        if (data.graph) {
          const g = data.graph;
          currentFileCount = data.file_count || 0;
          knownNodeIds = new Set((g.nodes || []).map(n => n.id));

          engine.setGraphData(g, []); // Nem animáljuk a meglévő több ezer pontot induláskor
          if (el.dispNodes) {
            el.dispNodes.textContent = Number(g.total_nodes || g.nodes.length || 0).toLocaleString();
          }
        }
        isInitialLoad = false;
        return;
      }

      // Későbbi ciklusok: ha érkezett új feldolgozott JSON
      if (data.has_new && data.graph) {
        const newGraph = data.graph;
        currentFileCount = data.file_count;

        // Kikeressük a vadonatúj csomópontokat
        const incomingNodes = [];
        const incomingIds = [];

        for (let n of (newGraph.nodes || [])) {
          if (!knownNodeIds.has(n.id)) {
            incomingNodes.push(n);
            incomingIds.push(n.id);
            knownNodeIds.add(n.id);
          }
        }

        // Átadjuk az új gráfot a 3D motornak az új azonosítókkal
        // Mivel a backend megőrzi a meglévő koordinátákat (fixed), a nézet nem ugrik meg,
        // a forgás sima marad, és csak az új csomópont repül be látványosan a helyére!
        engine.setGraphData(newGraph, incomingIds);

        if (el.dispNodes) {
          el.dispNodes.textContent = Number(newGraph.total_nodes || newGraph.nodes.length || 0).toLocaleString();
        }

        // Ha van köztük új tanulmány, kiírjuk az elegáns toastban és megszólal a hang
        const newPapers = incomingNodes.filter(n => n.type === 'paper');
        if (newPapers.length > 0) {
          const firstPaperTitle = newPapers[0].label || newPapers[0].id;
          const others = incomingNodes.length - 1;
          showArrivalToast(firstPaperTitle, others);
        } else if (incomingNodes.length > 0) {
          const firstTitle = incomingNodes[0].label || incomingNodes[0].id;
          showArrivalToast(firstTitle, incomingNodes.length - 1);
        }
      }
    } catch (err) {
      console.warn("Szinkronizációs hiba (újrapróbálkozás a következő ciklusban):", err);
    }
  }

  // ─── Vezérlő Gombok Eseményei ─────────────────────────────────

  // 1. Auto-Sync ki/be kapcsolása
  if (el.btnToggleSync) {
    el.btnToggleSync.addEventListener('click', () => {
      isAutoSyncEnabled = !isAutoSyncEnabled;
      el.btnToggleSync.classList.toggle('active', isAutoSyncEnabled);
      if (el.labelSync) {
        el.labelSync.textContent = isAutoSyncEnabled ? 'Auto-Sync ON' : 'Auto-Sync OFF';
      }
    });
  }

  // 2. Galaktikus forgás ki/be kapcsolása
  if (el.btnToggleRotate) {
    el.btnToggleRotate.addEventListener('click', () => {
      isRotating = !isRotating;
      engine.toggleAutoRotate(isRotating);
      el.btnToggleRotate.classList.toggle('active', isRotating);
      if (el.labelRotate) {
        el.labelRotate.textContent = isRotating ? 'Forgás' : 'Megállítva';
      }
    });
  }

  // 3. Hangjelzés ki/be kapcsolása
  if (el.btnToggleSound) {
    el.btnToggleSound.addEventListener('click', () => {
      isSoundEnabled = !isSoundEnabled;
      el.btnToggleSound.classList.toggle('active', isSoundEnabled);
      if (el.soundIcon) {
        el.soundIcon.textContent = isSoundEnabled ? '🔔' : '🔕';
      }
      if (isSoundEnabled) {
        playCosmicChime(); // Rövid visszajelző hang bekapcsoláskor
      }
    });
  }

  // 4. Kamera alaphelyzetbe állítása
  if (el.btnResetView) {
    el.btnResetView.addEventListener('click', () => {
      engine.resetCamera();
    });
  }

  // Billentyűparancsok (R: reset camera, Space: forgás megállítása/indítása, M: hang némítása)
  window.addEventListener('keydown', (e) => {
    if (e.code === 'KeyR') {
      engine.resetCamera();
    } else if (e.code === 'Space') {
      e.preventDefault();
      if (el.btnToggleRotate) el.btnToggleRotate.click();
    } else if (e.code === 'KeyM') {
      if (el.btnToggleSound) el.btnToggleSound.click();
    }
  });

  // ─── Indítás ─────────────────────────────────────────────────
  // Első betöltés azonnal
  pollUpdates();

  // Majd 3 másodpercenként csendes háttér lekérdezés
  setInterval(pollUpdates, 3200);
});
