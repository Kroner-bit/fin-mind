/**
 * arXiv PDF Research Studio - Client JavaScript
 * Real-time WebSocket streaming, 60 FPS gliding animations,
 * zero-jitter fixed worker slots, multi-API-key management,
 * per-key RPD quota tracking, and Apple matte aesthetic.
 */

// Application State
const state = {
  ws: null,
  reconnectTimer: null,
  config: {
    model: "gemini-3.5-flash-lite",
    processing: { concurrent_workers: 2, max_utilization_pct: 80 },
    api_keys: [],
    active_key_mode: "auto",
    active_key_id: null
  },
  rpdResetTs: null,
  rpdResetSeconds: 0,
  isProcessing: false,
  workersCount: 2,
  workerSlots: {},
  workerBuffers: {},
  pdfs: [],
  currentFilter: "all",
  searchQuery: "",
  autoScroll: true,
  perKeyUsage: [],
  activeKeyId: null,
  activeKeyMode: "auto",
  keysCollapsed: localStorage.getItem("keys_dashboard_collapsed") === "true"
};

// Continuous 60 FPS Animation State (Lerp gliding engine)
const anim = {
  rpm: 0, rpmTarget: 0, rpmPct: 0, rpmPctTarget: 0, rpmMax: 15,
  tpm: 0, tpmTarget: 0, tpmPct: 0, tpmPctTarget: 0, tpmMax: 250000,
  rpd: 0, rpdTarget: 0, rpdPct: 0, rpdPctTarget: 0, rpdMax: 500,
  tokensToday: 0, tokensTodayTarget: 0,
  tokensTotal: 0, tokensTotalTarget: 0,
  reqTotal: 0, reqTotalTarget: 0,
  progressPct: 0, progressPctTarget: 0,
  cap: 80
};

// DOM References
const el = {
  connectionPill: document.getElementById("connection-pill"),
  connectionText: document.getElementById("connection-text"),
  globalStatusBox: document.getElementById("global-status-box"),
  statusText: document.getElementById("status-text"),
  statusPulse: document.getElementById("status-pulse"),
  btnStart: document.getElementById("btn-start"),
  btnStop: document.getElementById("btn-stop"),
  btnScan: document.getElementById("btn-scan"),
  btnRetry: document.getElementById("btn-retry"),
  btnOpenPdf: document.getElementById("btn-open-pdf"),
  btnOpenJson: document.getElementById("btn-open-json"),
  btnGenObsidian: document.getElementById("btn-gen-obsidian"),
  btnObsidianText: document.getElementById("btn-obsidian-text"),
  btnOpenObsidian: document.getElementById("btn-open-obsidian"),
  btnSettingsToggle: document.getElementById("btn-settings-toggle"),
  dispModel: document.getElementById("disp-model"),
  dispWorkers: document.getElementById("disp-workers"),
  dispCap: document.getElementById("disp-cap"),
  dispActiveKey: document.getElementById("disp-active-key"),
  cardRpm: document.getElementById("card-rpm"),
  badgeRpm: document.getElementById("badge-rpm"),
  fillRpm: document.getElementById("fill-rpm"),
  valRpmCur: document.getElementById("val-rpm-cur"),
  valRpmMax: document.getElementById("val-rpm-max"),
  subRpm: document.getElementById("sub-rpm"),
  markerRpm: document.getElementById("marker-rpm"),
  cardTpm: document.getElementById("card-tpm"),
  badgeTpm: document.getElementById("badge-tpm"),
  fillTpm: document.getElementById("fill-tpm"),
  valTpmCur: document.getElementById("val-tpm-cur"),
  valTpmMax: document.getElementById("val-tpm-max"),
  subTpm: document.getElementById("sub-tpm"),
  markerTpm: document.getElementById("marker-tpm"),
  cardRpd: document.getElementById("card-rpd"),
  badgeRpd: document.getElementById("badge-rpd"),
  fillRpd: document.getElementById("fill-rpd"),
  valRpdCur: document.getElementById("val-rpd-cur"),
  valRpdMax: document.getElementById("val-rpd-max"),
  subRpd: document.getElementById("sub-rpd"),
  markerRpd: document.getElementById("marker-rpd"),
  titleRpd: document.getElementById("title-rpd"),
  tagRpd: document.getElementById("tag-rpd"),
  valTokensToday: document.getElementById("val-tokens-today"),
  valCostToday: document.getElementById("val-cost-today"),
  valTokensTotal: document.getElementById("val-tokens-total"),
  valCostTotal: document.getElementById("val-cost-total"),
  valReqTotal: document.getElementById("val-req-total"),
  rpdCountdown: document.getElementById("rpd-countdown"),
  countCompleted: document.getElementById("count-completed"),
  countPending: document.getElementById("count-pending"),
  countError: document.getElementById("count-error"),
  countTotal: document.getElementById("count-total"),
  globalProgressPct: document.getElementById("global-progress-pct"),
  globalProgressBar: document.getElementById("global-progress-bar"),
  tableTitle: document.getElementById("table-title"),
  tableRowCount: document.getElementById("table-row-count"),
  pdfSearchInput: document.getElementById("pdf-search-input"),
  filterPills: document.querySelectorAll(".filter-pill"),
  pdfTableBody: document.getElementById("pdf-table-body"),
  activeWorkerBadge: document.getElementById("active-worker-badge"),
  autoscrollToggle: document.getElementById("autoscroll-toggle"),
  btnClearLogs: document.getElementById("btn-clear-logs"),
  workerTerminalsGrid: document.getElementById("worker-terminals-grid"),
  systemTerminalBody: document.getElementById("system-terminal-body"),
  settingsModal: document.getElementById("settings-modal"),
  btnSettingsClose: document.getElementById("btn-settings-close"),
  btnSaveSettings: document.getElementById("btn-save-settings"),
  cfgModel: document.getElementById("cfg-model"),
  cfgWorkers: document.getElementById("cfg-workers"),
  valCfgWorkers: document.getElementById("val-cfg-workers"),
  cfgCap: document.getElementById("cfg-cap"),
  valCfgCap: document.getElementById("val-cfg-cap"),
  jsonModal: document.getElementById("json-modal"),
  jsonModalTitle: document.getElementById("json-modal-title"),
  jsonModalPre: document.getElementById("json-modal-pre"),
  btnJsonClose: document.getElementById("btn-json-close"),
  // Multi-key elements
  keyCardsGrid: document.getElementById("key-cards-grid"),
  keyCardsCompact: document.getElementById("key-cards-compact"),
  btnToggleKeysCollapse: document.getElementById("btn-toggle-keys-collapse"),
  keysCollapseText: document.getElementById("keys-collapse-text"),
  modalKeyList: document.getElementById("modal-key-list"),
  btnAddKey: document.getElementById("btn-add-key"),
  btnKeyModeAuto: document.getElementById("btn-key-mode-auto"),
  btnKeyModeManual: document.getElementById("btn-key-mode-manual"),
  radioModeAuto: document.getElementById("radio-mode-auto"),
  radioModeManual: document.getElementById("radio-mode-manual"),
  manualKeySelect: document.getElementById("manual-key-select"),
  selectManualKey: document.getElementById("select-manual-key")
};

// ─── Number Helpers ─────────────────────────────────────────────────────────

function formatNumber(num) {
  if (num === null || num === undefined) return "0";
  return Number(num).toLocaleString("hu-HU");
}

function formatCompact(num) {
  if (num >= 1_000_000) return (num / 1_000_000).toFixed(2) + "M";
  if (num >= 1_000) return (num / 1_000).toFixed(1) + "k";
  return String(Math.round(num));
}

function calculateEstimatedCost(tokens) {
  if (!tokens || tokens <= 0) return "$0.00";
  const cost = (tokens / 1_000_000) * 0.105;
  if (cost < 0.01) return "<$0.01";
  return "$" + cost.toFixed(2);
}

function formatClockTime(isoStr) {
  if (!isoStr) return "";
  try {
    const d = new Date(isoStr);
    const h = String(d.getHours()).padStart(2, "0");
    const m = String(d.getMinutes()).padStart(2, "0");
    return `${h}:${m}`;
  } catch (e) {
    return "";
  }
}

function updateRpdCountdown() {
  if (el.rpdCountdown) {
    let diffSec = 0;
    if (state.rpdResetTs) {
      const targetMs = new Date(state.rpdResetTs).getTime();
      diffSec = Math.max(0, Math.floor((targetMs - Date.now()) / 1000));
    } else if (state.rpdResetSeconds > 0) {
      diffSec = Math.max(0, Math.floor(state.rpdResetSeconds));
    }

    if (anim.rpdTarget === 0 || diffSec <= 0) {
      el.rpdCountdown.textContent = "00:00:00 (Szabad)";
    } else {
      const h = String(Math.floor(diffSec / 3600)).padStart(2, "0");
      const m = String(Math.floor((diffSec % 3600) / 60)).padStart(2, "0");
      const s = String(diffSec % 60).padStart(2, "0");
      const clockStr = formatClockTime(state.rpdResetTs);
      el.rpdCountdown.textContent = clockStr ? `${h}:${m}:${s} (${clockStr})` : `${h}:${m}:${s}`;
      el.rpdCountdown.title = `Teljes 0/500 reset időpontja: ${clockStr || ''}`;
    }
  }

  // Update per-key countdowns on individual key cards
  const keys = state.config?.api_keys || [];
  const usage = state.perKeyUsage || [];
  keys.forEach(k => {
    const countdownEl = document.getElementById(`key-reset-val-${k.id}`);
    if (!countdownEl) return;
    const u = usage.find(uu => uu.id === k.id);
    if (!u) return;

    if (u.rpd_used === 0) {
      countdownEl.textContent = `Szabad (0 / ${u.rpd_limit || 500})`;
      countdownEl.classList.remove("key-reset-exhausted");
      return;
    }

    let kFullSec = 0;
    if (u.rpd_reset_ts) {
      kFullSec = Math.max(0, Math.floor((new Date(u.rpd_reset_ts).getTime() - Date.now()) / 1000));
    } else if (u.rpd_reset_seconds > 0) {
      kFullSec = Math.max(0, Math.floor(u.rpd_reset_seconds));
    }

    const fullClock = formatClockTime(u.rpd_reset_ts);
    const kh = String(Math.floor(kFullSec / 3600)).padStart(2, "0");
    const km = String(Math.floor((kFullSec % 3600) / 60)).padStart(2, "0");
    const ks = String(kFullSec % 60).padStart(2, "0");

    if (u.rpd_remaining <= 0) {
      let kNextSec = 0;
      if (u.rpd_next_available_ts) {
        kNextSec = Math.max(0, Math.floor((new Date(u.rpd_next_available_ts).getTime() - Date.now()) / 1000));
      } else if (u.rpd_next_available_seconds > 0) {
        kNextSec = Math.max(0, Math.floor(u.rpd_next_available_seconds));
      }
      const nextClock = formatClockTime(u.rpd_next_available_ts);
      const nh = String(Math.floor(kNextSec / 3600)).padStart(2, "0");
      const nm = String(Math.floor((kNextSec % 3600) / 60)).padStart(2, "0");
      const ns = String(kNextSec % 60).padStart(2, "0");

      countdownEl.classList.add("key-reset-exhausted");
      countdownEl.innerHTML = `<span title="Következő 1 szabad kérés ideje">${nh}:${nm}:${ns} (${nextClock})</span> <span style="font-size:0.75rem;opacity:0.8;" title="Teljes 0/500 reset ideje">| 0/500: ${kh}:${km}:${ks} (${fullClock})</span>`;
    } else if (kFullSec <= 0) {
      countdownEl.textContent = "Resetelve (Szabad)";
      countdownEl.classList.remove("key-reset-exhausted");
    } else {
      countdownEl.classList.remove("key-reset-exhausted");
      countdownEl.innerHTML = `${kh}:${km}:${ks} (${fullClock}) <span style="font-size:0.75rem;opacity:0.85;color:#30D158;">(${u.rpd_remaining} szabad)</span>`;
    }
  });
}

function getCurrentTime() {
  return new Date().toTimeString().split(" ")[0];
}

function escapeHtml(str) {
  if (!str) return "";
  return String(str).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

// ─── 60 FPS Dynamic Glide & Rolling Counter Engine ───────────────────────────

function smoothGlide(current, target, factor = 0.095, minStep = 0.01) {
  const diff = target - current;
  if (Math.abs(diff) <= minStep) return target;
  let step = diff * factor;
  if (Math.abs(step) < minStep) step = Math.sign(diff) * minStep;
  const next = current + step;
  if ((diff > 0 && next > target) || (diff < 0 && next < target)) return target;
  return next;
}

function startAnimationEngine() {
  function frame() {
    const f = 0.095;
    anim.rpm = smoothGlide(anim.rpm, anim.rpmTarget, f, 0.01);
    anim.rpmPct = smoothGlide(anim.rpmPct, anim.rpmPctTarget, f, 0.05);
    anim.tpm = smoothGlide(anim.tpm, anim.tpmTarget, f, 15);
    anim.tpmPct = smoothGlide(anim.tpmPct, anim.tpmPctTarget, f, 0.05);
    anim.rpd = smoothGlide(anim.rpd, anim.rpdTarget, f, 0.2);
    anim.rpdPct = smoothGlide(anim.rpdPct, anim.rpdPctTarget, f, 0.05);
    anim.tokensToday = smoothGlide(anim.tokensToday, anim.tokensTodayTarget, f, 15);
    anim.tokensTotal = smoothGlide(anim.tokensTotal, anim.tokensTotalTarget, f, 15);
    anim.reqTotal = smoothGlide(anim.reqTotal, anim.reqTotalTarget, f, 0.2);
    anim.progressPct = smoothGlide(anim.progressPct, anim.progressPctTarget, f, 0.05);

    if (el.valRpmCur) el.valRpmCur.textContent = anim.rpm >= 10 ? Math.round(anim.rpm) : anim.rpm.toFixed(1);
    if (el.badgeRpm) el.badgeRpm.textContent = `${anim.rpmPct.toFixed(1)}%`;
    if (el.fillRpm) el.fillRpm.style.width = `${Math.min(100, Math.max(0, anim.rpmPct))}%`;
    setGaugeColor(el.cardRpm, anim.rpmPct, anim.cap);

    if (el.valTpmCur) el.valTpmCur.textContent = formatNumber(Math.round(anim.tpm));
    if (el.badgeTpm) el.badgeTpm.textContent = `${anim.tpmPct.toFixed(1)}%`;
    if (el.fillTpm) el.fillTpm.style.width = `${Math.min(100, Math.max(0, anim.tpmPct))}%`;
    setGaugeColor(el.cardTpm, anim.tpmPct, anim.cap);

    if (el.valRpdCur) el.valRpdCur.textContent = formatNumber(Math.round(anim.rpd));
    if (el.badgeRpd) el.badgeRpd.textContent = `${anim.rpdPct.toFixed(1)}%`;
    if (el.fillRpd) el.fillRpd.style.width = `${Math.min(100, Math.max(0, anim.rpdPct))}%`;
    setGaugeColor(el.cardRpd, anim.rpdPct, 100);

    if (el.valTokensToday) el.valTokensToday.textContent = formatNumber(Math.round(anim.tokensToday));
    if (el.valCostToday) el.valCostToday.textContent = `~${calculateEstimatedCost(anim.tokensToday)}`;
    if (el.valTokensTotal) el.valTokensTotal.textContent = formatNumber(Math.round(anim.tokensTotal));
    if (el.valCostTotal) el.valCostTotal.textContent = `~${calculateEstimatedCost(anim.tokensTotal)}`;
    if (el.valReqTotal) el.valReqTotal.textContent = formatNumber(Math.round(anim.reqTotal));

    if (el.globalProgressBar) el.globalProgressBar.style.width = `${Math.min(100, Math.max(0, anim.progressPct))}%`;
    if (el.globalProgressPct) el.globalProgressPct.textContent = `${anim.progressPct.toFixed(1)}% Kész`;

    requestAnimationFrame(frame);
  }
  requestAnimationFrame(frame);
}

function setGaugeColor(card, pct, cap) {
  if (!card) return;
  card.classList.remove("warning", "danger");
  if (pct >= cap) card.classList.add("danger");
  else if (pct >= cap * 0.75) card.classList.add("warning");
}

// ─── Dynamic Multi-Worker Terminal Generator ────────────────────────────────

function setupWorkerTerminals(count) {
  state.workersCount = Math.max(1, count);
  el.workerTerminalsGrid.innerHTML = "";
  el.activeWorkerBadge.textContent = `${state.workersCount} Aktív Worker Ablak`;
  state.workerSlots = {};
  for (let i = 1; i <= state.workersCount; i++) {
    state.workerSlots[i] = { workerId: i, status: "idle", fileName: "-", tokens: "-", jsonPath: null, errorMessage: null };
    const panel = document.createElement("div");
    panel.className = "worker-terminal-panel";
    panel.id = `worker-panel-${i}`;
    panel.innerHTML = `
      <div class="terminal-header">
        <div class="worker-title-wrap">
          <span class="worker-id-badge">Worker #${i}</span>
          <span class="worker-job-badge" id="worker-job-${i}">Készenlét (Idle)</span>
        </div>
        <div class="terminal-actions">
          <button class="btn btn-ghost btn-sm" onclick="clearWorkerLog(${i})" title="Törlés">Törlés</button>
        </div>
      </div>
      <div class="worker-buffer-panel" id="worker-buffer-panel-${i}">
        <div class="buffer-panel-header">
          <div class="buffer-panel-meta">
            <span class="buffer-title">Előkészített Buffer (3 Párhuzamos Szál)</span>
            <span class="buffer-badge buffer-empty" id="worker-buffer-count-${i}">0 / 3 Kész</span>
          </div>
        </div>
        <div class="buffer-slots-container" id="worker-buffer-slots-${i}">
          <div class="buffer-slot-row slot-idle" id="buffer-slot-${i}-1">
            <span class="slot-badge">Szál #1</span>
            <span class="slot-status-dot"></span>
            <span class="slot-status-label">Üres</span>
            <span class="slot-detail">Készenlét (Várakozás új feladatra)</span>
            <span class="slot-tokens" style="display: none;"></span>
          </div>
          <div class="buffer-slot-row slot-idle" id="buffer-slot-${i}-2">
            <span class="slot-badge">Szál #2</span>
            <span class="slot-status-dot"></span>
            <span class="slot-status-label">Üres</span>
            <span class="slot-detail">Készenlét (Várakozás új feladatra)</span>
            <span class="slot-tokens" style="display: none;"></span>
          </div>
          <div class="buffer-slot-row slot-idle" id="buffer-slot-${i}-3">
            <span class="slot-badge">Szál #3</span>
            <span class="slot-status-dot"></span>
            <span class="slot-status-label">Üres</span>
            <span class="slot-detail">Készenlét (Várakozás új feladatra)</span>
            <span class="slot-tokens" style="display: none;"></span>
          </div>
        </div>
      </div>
      <div class="terminal-body" id="worker-terminal-body-${i}">
        <div class="log-line log-info">
          <span class="log-ts">[${getCurrentTime()}]</span>
          <span class="log-msg">Worker #${i} terminál online.</span>
        </div>
      </div>
    `;
    el.workerTerminalsGrid.appendChild(panel);
  }
  renderPdfTable();
  if (state.workerBuffers) {
    renderWorkerBuffers(state.workerBuffers);
  }
}

function renderWorkerBuffers(workerBuffers) {
  if (!workerBuffers) return;
  state.workerBuffers = workerBuffers;

  for (let i = 1; i <= state.workersCount; i++) {
    const countEl = document.getElementById(`worker-buffer-count-${i}`);
    const items = workerBuffers[String(i)] || workerBuffers[i] || [];

    let readyCount = 0;
    for (let sid = 1; sid <= 3; sid++) {
      const slotData = items.find(s => s.slot === sid) || {
        slot: sid,
        status: "idle",
        file_name: null,
        estimated_tokens: 0,
        detail: "Üres"
      };

      if (slotData.status === "ready") readyCount++;

      const rowEl = document.getElementById(`buffer-slot-${i}-${sid}`);
      if (!rowEl) continue;

      const status = slotData.status || "idle";
      rowEl.className = `buffer-slot-row slot-${status}`;

      const labelEl = rowEl.querySelector(".slot-status-label");
      const detailEl = rowEl.querySelector(".slot-detail");
      const tokensEl = rowEl.querySelector(".slot-tokens");

      if (status === "ready") {
        if (labelEl) labelEl.textContent = "Kész";
        if (detailEl) {
          detailEl.textContent = slotData.file_name || "Előkészítve";
          detailEl.title = `${slotData.file_name || ''} (~${formatNumber(slotData.estimated_tokens)} token memóriában)`;
        }
        if (tokensEl) {
          tokensEl.textContent = slotData.estimated_tokens ? `~${formatCompact(slotData.estimated_tokens)} tok` : "";
          tokensEl.style.display = slotData.estimated_tokens ? "inline-block" : "none";
        }
      } else if (status === "extracting") {
        if (labelEl) labelEl.textContent = "Kinyerés...";
        if (detailEl) {
          const fn = slotData.file_name ? `${slotData.file_name} (PDF feldolgozás)` : "PDF kinyerése folyamatban...";
          detailEl.textContent = fn;
          detailEl.title = fn;
        }
        if (tokensEl) {
          tokensEl.textContent = "Aktív";
          tokensEl.style.display = "inline-block";
        }
      } else {
        if (labelEl) labelEl.textContent = "Üres";
        if (detailEl) {
          detailEl.textContent = "Készenlét (Várakozás új feladatra)";
          detailEl.title = "";
        }
        if (tokensEl) {
          tokensEl.textContent = "";
          tokensEl.style.display = "none";
        }
      }

      if (slotData.is_last_dispatched) {
        rowEl.classList.add("slot-last-dispatched");
        let lastBadge = rowEl.querySelector(".slot-last-badge");
        if (!lastBadge) {
          lastBadge = document.createElement("span");
          lastBadge.className = "slot-last-badge";
          lastBadge.textContent = "Legutóbb Küldve";
          rowEl.appendChild(lastBadge);
        }
      } else {
        rowEl.classList.remove("slot-last-dispatched");
        const lastBadge = rowEl.querySelector(".slot-last-badge");
        if (lastBadge) lastBadge.remove();
      }
    }

    if (countEl) {
      countEl.textContent = `${readyCount} / 3 Kész`;
      countEl.classList.remove("buffer-full", "buffer-partial", "buffer-empty");
      if (readyCount >= 3) countEl.classList.add("buffer-full");
      else if (readyCount > 0) countEl.classList.add("buffer-partial");
      else countEl.classList.add("buffer-empty");
    }
  }
}

window.clearWorkerLog = function(workerId) {
  const terminal = document.getElementById(`worker-terminal-body-${workerId}`);
  if (terminal) terminal.innerHTML = "";
};

function stripEmojis(str) {
  if (!str) return "";
  return String(str).replace(/[\u{1F000}-\u{1FFFF}\u{2600}-\u{27BF}\u{2300}-\u{23FF}\u{2B50}-\u{2B55}\u{203C}\u{2049}\u{25B6}\u{25C0}]/gu, "").trim();
}

function appendLogLine(targetBody, message, level = "info", timestamp = null) {
  if (!targetBody) return;
  const ts = timestamp || getCurrentTime();
  const line = document.createElement("div");
  line.className = `log-line log-${level}`;
  line.innerHTML = `<span class="log-ts">[${ts}]</span> <span class="log-msg">${escapeHtml(stripEmojis(message))}</span>`;
  targetBody.appendChild(line);
  if (targetBody.childNodes.length > 300) targetBody.removeChild(targetBody.firstChild);
  if (state.autoScroll) targetBody.scrollTop = targetBody.scrollHeight;
}

// ─── Per-Key Dashboard Cards ────────────────────────────────────────────────

function renderKeyCards() {
  const grid = el.keyCardsGrid;
  if (!grid) return;

  // Remove old key cards (keep the add button)
  const addCard = document.getElementById("key-card-add");
  grid.innerHTML = "";

  let keys = (state.config && state.config.api_keys && state.config.api_keys.length > 0) ? state.config.api_keys : [];
  const usage = state.perKeyUsage || [];
  if (keys.length === 0 && usage.length > 0) {
    keys = usage.map((u, i) => ({ id: u.id, label: u.label || `Kulcs #${i + 1}`, rpd: u.rpd_limit || 500 }));
  }

  keys.forEach((keyCfg, idx) => {
    const keyUsage = usage.find(u => u.id === keyCfg.id) || {
      rpd_used: 0, rpd_limit: keyCfg.rpd || 500, rpd_remaining: keyCfg.rpd || 500, rpd_pct: 0,
      rpd_reset_ts: null, rpd_reset_seconds: 0,
    };

    const isActive = state.activeKeyId === keyCfg.id;
    const isExhausted = keyUsage.rpd_remaining <= 0;
    const pct = keyUsage.rpd_pct || 0;

    let statusClass = "key-card-ok";
    if (isExhausted) statusClass = "key-card-exhausted";
    else if (pct >= 80) statusClass = "key-card-warning";

    let resetStr = `Szabad (0 / ${keyUsage.rpd_limit || 500})`;
    if (keyUsage.rpd_used > 0) {
      const fullClock = formatClockTime(keyUsage.rpd_reset_ts);
      const h = String(Math.floor(keyUsage.rpd_reset_seconds / 3600)).padStart(2, "0");
      const m = String(Math.floor((keyUsage.rpd_reset_seconds % 3600) / 60)).padStart(2, "0");
      const s = String(Math.floor(keyUsage.rpd_reset_seconds % 60)).padStart(2, "0");

      if (isExhausted) {
        const nextClock = formatClockTime(keyUsage.rpd_next_available_ts);
        const nextSec = keyUsage.rpd_next_available_seconds || 0;
        const nh = String(Math.floor(nextSec / 3600)).padStart(2, "0");
        const nm = String(Math.floor((nextSec % 3600) / 60)).padStart(2, "0");
        const ns = String(Math.floor(nextSec % 60)).padStart(2, "0");
        resetStr = `<span title="Következő 1 szabad kérés ideje">${nh}:${nm}:${ns} (${nextClock})</span> <span style="font-size:0.75rem;opacity:0.8;" title="Teljes 0/500 reset ideje">| 0/500: ${h}:${m}:${s} (${fullClock})</span>`;
      } else {
        resetStr = `${h}:${m}:${s} (${fullClock}) <span style="font-size:0.75rem;opacity:0.85;color:#30D158;">(${keyUsage.rpd_remaining} szabad)</span>`;
      }
    }

    const card = document.createElement("div");
    card.className = `key-card ${statusClass} ${isActive ? "key-card-active" : ""}`;
    card.id = `key-card-${keyCfg.id}`;

    card.innerHTML = `
      <div class="key-card-header">
        <div class="key-card-label" title="${escapeHtml(keyCfg.label || keyCfg.id)}">${escapeHtml(keyCfg.label || `Kulcs #${idx + 1}`)}</div>
        ${isActive ? '<span class="key-active-badge">● AKTÍV</span>' : ''}
      </div>
      <div class="key-card-rpd-bar">
        <div class="key-rpd-fill" style="width: ${Math.min(100, pct)}%"></div>
      </div>
      <div class="key-card-stats">
        <div class="key-stat">
          <span class="key-stat-val">${formatNumber(keyUsage.rpd_used)}</span>
          <span class="key-stat-label">/ ${formatNumber(keyUsage.rpd_limit)} RPD</span>
        </div>
        <div class="key-stat">
          <span class="key-stat-val key-stat-remaining">${formatNumber(keyUsage.rpd_remaining)}</span>
          <span class="key-stat-label">szabad</span>
        </div>
      </div>
      <div class="key-card-reset-row">
        <span class="key-reset-label">24h Reset:</span>
        <span class="key-reset-val ${isExhausted ? 'key-reset-exhausted' : ''}" id="key-reset-val-${keyCfg.id}">${resetStr}</span>
        <button class="btn-key-quota-reset" title="Kulcs kvóta számláló nullázása" onclick="resetQuotaCounter('${keyCfg.id}')">🔄</button>
      </div>
      ${state.activeKeyMode === "manual" && !isActive ? 
        `<button class="btn btn-ghost btn-sm key-select-btn" onclick="selectManualKey('${keyCfg.id}')">Kiválasztás</button>` : ''}
    `;

    grid.appendChild(card);
  });

  // Re-add the add button
  if (addCard) {
    grid.appendChild(addCard);
  } else {
    const addEl = document.createElement("div");
    addEl.className = "key-card key-card-empty";
    addEl.id = "key-card-add";
    addEl.innerHTML = `<div class="key-card-add-inner" onclick="document.getElementById('settings-modal').classList.add('open')">
      <span class="key-add-icon">+</span><span>Kulcs Hozzáadása</span>
    </div>`;
    grid.appendChild(addEl);
  }

  // Update active key display chip
  if (el.dispActiveKey) {
    const activeLabel = keys.find(k => k.id === state.activeKeyId);
    if (state.activeKeyMode === "auto") {
      el.dispActiveKey.textContent = `Auto → ${activeLabel ? activeLabel.label : '—'}`;
    } else {
      el.dispActiveKey.textContent = `Kézi: ${activeLabel ? activeLabel.label : '—'}`;
    }
  }

  // Update key mode buttons
  if (el.btnKeyModeAuto) {
    el.btnKeyModeAuto.classList.toggle("btn-primary-ghost", state.activeKeyMode === "auto");
    el.btnKeyModeManual.classList.toggle("btn-primary-ghost", state.activeKeyMode === "manual");
  }

  // Render compact view as well and apply collapse display state
  renderCompactKeyChips();
  updateKeysCollapseView();
}

function renderCompactKeyChips() {
  const container = el.keyCardsCompact;
  if (!container) return;

  let keys = (state.config && state.config.api_keys && state.config.api_keys.length > 0) ? state.config.api_keys : [];
  const usage = state.perKeyUsage || [];
  if (keys.length === 0 && usage.length > 0) {
    keys = usage.map((u, i) => ({ id: u.id, label: u.label || `Kulcs #${i + 1}`, rpd: u.rpd_limit || 500 }));
  }

  if (keys.length === 0) {
    container.innerHTML = `<div style="font-size: 0.8rem; color: var(--text-muted); padding: 0.5rem 0;">Még nincs API kulcs konfigurálva.</div>`;
    return;
  }

  let html = keys.map((keyCfg, idx) => {
    const keyUsage = usage.find(u => u.id === keyCfg.id) || {
      rpd_used: 0, rpd_limit: keyCfg.rpd || 500, rpd_remaining: keyCfg.rpd || 500, rpd_pct: 0
    };
    const isActive = state.activeKeyId === keyCfg.id;
    const isExhausted = keyUsage.rpd_remaining <= 0;
    const label = keyCfg.label || `Kulcs #${idx + 1}`;

    return `
      <div class="compact-key-chip ${isActive ? 'compact-key-active' : ''} ${isExhausted ? 'compact-key-exhausted' : ''}"
           onclick="selectManualKey('${keyCfg.id}')"
           title="Kattints a kiválasztáshoz: ${escapeHtml(label)}">
        <span class="compact-key-status-dot"></span>
        <span class="compact-key-name">${escapeHtml(label)}</span>
        <span class="compact-key-rpd">${formatNumber(keyUsage.rpd_used)} / ${formatNumber(keyUsage.rpd_limit)} RPD</span>
        <span class="compact-key-rem">(${formatNumber(keyUsage.rpd_remaining)} szabad)</span>
        ${isActive ? '<span class="compact-key-badge">AKTÍV</span>' : ''}
      </div>
    `;
  }).join("");

  html += `
    <div class="compact-key-add" onclick="document.getElementById('settings-modal').classList.add('open')" title="Új kulcs felvétele">
      <span>+ Kulcs</span>
    </div>
  `;

  container.innerHTML = html;
}

function updateKeysCollapseView() {
  const isCollapsed = Boolean(state.keysCollapsed);
  if (el.keyCardsGrid) {
    el.keyCardsGrid.style.display = isCollapsed ? "none" : "grid";
  }
  if (el.keyCardsCompact) {
    el.keyCardsCompact.style.display = isCollapsed ? "flex" : "none";
  }
  if (el.keysCollapseText) {
    el.keysCollapseText.textContent = isCollapsed ? "Kibontás" : "Összecsukás";
  }
  if (el.btnToggleKeysCollapse) {
    el.btnToggleKeysCollapse.classList.toggle("collapsed", isCollapsed);
  }
}

function toggleKeysCollapse() {
  state.keysCollapsed = !state.keysCollapsed;
  localStorage.setItem("keys_dashboard_collapsed", state.keysCollapsed ? "true" : "false");
  updateKeysCollapseView();
  if (state.keysCollapsed) {
    renderCompactKeyChips();
  }
}

function renderModalKeyList() {
  const container = el.modalKeyList;
  if (!container) return;

  const keys = state.config?.api_keys || [];
  const usage = state.perKeyUsage || [];

  if (keys.length === 0) {
    container.innerHTML = `<div class="key-list-empty">Még nincs API kulcs konfigurálva. Adj hozzá egyet alul!</div>`;
    return;
  }

  container.innerHTML = keys.map((k, idx) => {
    const u = usage.find(uu => uu.id === k.id) || { rpd_used: 0, rpd_remaining: k.rpd || 500, rpd_pct: 0, rpd_reset_seconds: 0 };
    const maskedKey = k.key ? (k.key.substring(0, 6) + "..." + k.key.substring(k.key.length - 4)) : "***";
    const isActive = state.activeKeyId === k.id;
    let resetStr = "Nem használt";
    if (u.rpd_used > 0) {
      if (u.rpd_reset_seconds > 0) {
        const h = String(Math.floor(u.rpd_reset_seconds / 3600)).padStart(2, "0");
        const m = String(Math.floor((u.rpd_reset_seconds % 3600) / 60)).padStart(2, "0");
        resetStr = `${h}ó ${m}p`;
      } else {
        resetStr = "Resetelve (Szabad)";
      }
    }

    return `
      <div class="key-list-item ${isActive ? 'key-list-item-active' : ''}">
        <div class="key-list-info">
          <div class="key-list-label">
            ${isActive ? '●' : '○'} <strong>${escapeHtml(k.label || `Kulcs #${idx + 1}`)}</strong>
            <span class="key-list-id">${maskedKey}</span>
          </div>
          <div class="key-list-quotas">
            RPD: <strong>${k.rpd || 500}</strong> / nap
            <span class="key-list-usage">(${u.rpd_used} használt, ${u.rpd_remaining} szabad | Reset: ${resetStr})</span>
          </div>
        </div>
        <button class="btn btn-ghost btn-sm btn-danger-text" onclick="removeApiKey('${k.id}')" title="Kulcs eltávolítása">&times;</button>
      </div>
    `;
  }).join("");

  // Update manual key select dropdown
  if (el.selectManualKey) {
    el.selectManualKey.innerHTML = keys.map(k =>
      `<option value="${k.id}" ${state.activeKeyId === k.id ? 'selected' : ''}>${escapeHtml(k.label || k.id)}</option>`
    ).join("");
  }
}

window.selectManualKey = async function(keyId) {
  try {
    await fetch("/api/keys/active", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mode: "manual", key_id: keyId })
    });
    state.activeKeyMode = "manual";
    state.activeKeyId = keyId;
    renderKeyCards();
    renderModalKeyList();
  } catch (e) {
    alert("Hiba: " + e);
  }
};

window.removeApiKey = async function(keyId) {
  if (!confirm("Biztosan eltávolítod ezt az API kulcsot?")) return;
  try {
    const res = await fetch("/api/keys/remove", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ key_id: keyId })
    });
    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || "Hiba");
    }
    // Remove from local state
    state.config.api_keys = (state.config.api_keys || []).filter(k => k.id !== keyId);
    renderKeyCards();
    renderModalKeyList();
    appendLogLine(el.systemTerminalBody, `API kulcs eltávolítva: ${keyId}`, "info");
  } catch (e) {
    alert("Hiba: " + e.message);
  }
};

// ─── WebSocket Connection ───────────────────────────────────────────────────

function initWebSocket() {
  if (state.pingInterval) {
    clearInterval(state.pingInterval);
    state.pingInterval = null;
  }
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  const wsUrl = `${protocol}//${window.location.host}/ws`;
  state.ws = new WebSocket(wsUrl);

  state.ws.onopen = () => {
    el.connectionPill.style.display = "flex";
    el.connectionText.textContent = "Kapcsolódva";
    el.connectionPill.className = "live-pill";
    if (state.reconnectTimer) { clearTimeout(state.reconnectTimer); state.reconnectTimer = null; }

    state.pingInterval = setInterval(() => {
      if (state.ws && state.ws.readyState === WebSocket.OPEN) {
        try { state.ws.send("ping"); } catch (e) {}
      }
    }, 10000);
  };

  state.ws.onmessage = (event) => {
    try {
      if (event.data === "pong") return;
      handleWebSocketMessage(JSON.parse(event.data));
    }
    catch (e) { console.error("WS Parse error", e); }
  };

  state.ws.onclose = () => {
    if (state.pingInterval) { clearInterval(state.pingInterval); state.pingInterval = null; }
    el.connectionText.textContent = "Újrakapcsolódás...";
    el.connectionPill.className = "live-pill warning";
    if (!state.reconnectTimer) state.reconnectTimer = setTimeout(initWebSocket, 2000);
  };

  state.ws.onerror = () => {
    if (state.pingInterval) { clearInterval(state.pingInterval); state.pingInterval = null; }
    try { state.ws.close(); } catch (e) {}
  };
}

function handleWebSocketMessage(data) {
  if (data.type === "init") {
    state.config = data.config || state.config;
    updateConfigDisplay();
    const workers = state.config?.processing?.concurrent_workers || 2;
    setupWorkerTerminals(workers);
    dispatchMetricsUpdate(data.metrics, data.stats);
    updateProcessingStatus(data.is_processing, data.worker_status);
    if (data.worker_buffers) renderWorkerBuffers(data.worker_buffers);
    fetchPdfs();
    renderKeyCards();
    renderModalKeyList();
  } else if (data.type === "metrics") {
    dispatchMetricsUpdate(data.metrics, data.stats);
    updateProcessingStatus(data.is_processing, data.worker_status);
    if (data.worker_buffers) renderWorkerBuffers(data.worker_buffers);
  } else if (data.type === "worker_buffers_update" && data.worker_buffers) {
    renderWorkerBuffers(data.worker_buffers);
  } else if (data.type === "pdf_update" && data.pdf) {
    handlePdfUpdate(data.pdf);
  } else if (data.type === "refresh_table") {
    fetchPdfs(true);
  } else if (data.type === "log") {
    const wid = data.worker_id;
    if (wid === "system" || wid === "general") {
      appendLogLine(el.systemTerminalBody, data.message, data.level, data.timestamp);
    } else {
      const workerNum = parseInt(wid, 10);
      const targetBody = document.getElementById(`worker-terminal-body-${workerNum}`);
      if (targetBody) appendLogLine(targetBody, data.message, data.level, data.timestamp);
      else appendLogLine(el.systemTerminalBody, `[W${wid}] ${data.message}`, data.level, data.timestamp);
    }
  }
}

// ─── Metrics Dispatcher ─────────────────────────────────────────────────────

function dispatchMetricsUpdate(m, stats) {
  if (!m) return;
  anim.cap = m.utilization_cap || 80;
  anim.rpmTarget = m.rpm || 0;
  anim.rpmPctTarget = m.rpm_pct || 0;
  anim.rpmMax = m.rpm_limit || 15;
  if (el.valRpmMax) el.valRpmMax.textContent = anim.rpmMax;

  anim.tpmTarget = m.tpm || 0;
  anim.tpmPctTarget = m.tpm_pct || 0;
  anim.tpmMax = m.tpm_limit || 250000;
  if (el.valTpmMax) el.valTpmMax.textContent = formatNumber(anim.tpmMax);

  anim.rpdMax = m.rpd_limit || 500;
  anim.rpdTarget = m.rpd || 0;
  anim.rpdPctTarget = m.rpd_pct !== undefined ? m.rpd_pct : (anim.rpdTarget / anim.rpdMax) * 100;
  if (el.valRpdMax) el.valRpdMax.textContent = formatNumber(anim.rpdMax);

  if (m.rpd_reset_ts) state.rpdResetTs = m.rpd_reset_ts;
  if (m.rpd_reset_seconds !== undefined) state.rpdResetSeconds = m.rpd_reset_seconds;
  updateRpdCountdown();

  anim.tokensTodayTarget = m.tokens_today || 0;
  anim.tokensTotalTarget = m.total_tokens || 0;
  anim.reqTotalTarget = m.total_requests || 0;

  // Per-key data
  if (m.per_key_usage) {
    state.perKeyUsage = m.per_key_usage;
    renderKeyCards();
  }
  if (m.active_key_id !== undefined) state.activeKeyId = m.active_key_id;
  if (m.active_key_mode !== undefined) state.activeKeyMode = m.active_key_mode;

  // Active key label on RPD gauge title & tag
  if (el.titleRpd && m.active_key_label) {
    el.titleRpd.textContent = `RPD Kihasználtság (${m.active_key_label})`;
  }
  if (el.tagRpd) {
    el.tagRpd.textContent = `NAPI KVÓTA (${state.activeKeyMode === 'auto' ? 'AUTO KULCS' : 'KÉZI KULCS'})`;
  }

  if (stats) {
    el.countCompleted.textContent = formatNumber(stats.completed);
    el.countPending.textContent = formatNumber(stats.pending);
    el.countError.textContent = formatNumber(stats.errors);
    el.countTotal.textContent = formatNumber(stats.total);
    const total = stats.total || 0;
    const completed = stats.completed || 0;
    anim.progressPctTarget = total > 0 ? (completed / total) * 100 : 0;
  }
}

function updateProcessingStatus(isProcessing, workerStatus) {
  state.isProcessing = isProcessing;
  el.btnStart.disabled = isProcessing;
  el.btnStop.disabled = !isProcessing;

  if (isProcessing) {
    el.globalStatusBox.className = "status-indicator-box processing";
    el.statusText.textContent = "Feldolgozás Folyamatban...";
  } else {
    el.globalStatusBox.className = "status-indicator-box";
    el.statusText.textContent = "Készenlét (Idle)";
  }

  if (!isProcessing) {
    // When processing is stopped or idle, purge all active worker slots so processing list is immediately cleared
    for (let i = 1; i <= state.workersCount; i++) {
      state.workerSlots[i] = { workerId: i, status: "idle", fileName: "-", tokens: "-", jsonPath: null, errorMessage: null };
      const jobBadge = document.getElementById(`worker-job-${i}`);
      const panel = document.getElementById(`worker-panel-${i}`);
      if (jobBadge) {
        jobBadge.textContent = "Készenlét (Idle)";
        jobBadge.style.color = "var(--text-muted)";
      }
      if (panel) panel.classList.remove("active-working");
      patchWorkerSlotRow(i);
    }
    if (state.currentFilter === "processing") {
      el.tableRowCount.textContent = `0 / ${state.workersCount} worker (Készenlét)`;
    }
    return;
  }

  if (workerStatus) {
    let activeCount = 0;
    for (let i = 1; i <= state.workersCount; i++) {
      const jobBadge = document.getElementById(`worker-job-${i}`);
      const panel = document.getElementById(`worker-panel-${i}`);
      const st = workerStatus[i];
      if (st) {
        if (!state.workerSlots[i]) {
          state.workerSlots[i] = { workerId: i, status: "idle", fileName: "-", tokens: "-", jsonPath: null, errorMessage: null };
        }
        if (st.current_file) {
          activeCount++;
          if (jobBadge) {
            jobBadge.textContent = `LLM API: ${st.current_file}`;
            jobBadge.style.color = "var(--status-processing)";
          }
          if (panel) panel.classList.add("active-working");
          if (state.workerSlots[i].fileName !== st.current_file) {
            state.workerSlots[i].fileName = st.current_file;
            state.workerSlots[i].tokens = st.tokens ? formatNumber(st.tokens) : "-";
            state.workerSlots[i].jsonPath = null;
            state.workerSlots[i].errorMessage = null;
          } else if (st.tokens && state.workerSlots[i].tokens === "-") {
            state.workerSlots[i].tokens = formatNumber(st.tokens);
          }
          state.workerSlots[i].status = "processing";
        } else {
          if (jobBadge) {
            jobBadge.textContent = st.status || "Készenlét (Idle)";
            jobBadge.style.color = "var(--text-muted)";
          }
          if (panel) panel.classList.remove("active-working");
          state.workerSlots[i] = { workerId: i, status: "idle", fileName: "-", tokens: "-", jsonPath: null, errorMessage: null };
        }
        patchWorkerSlotRow(i);
      }
    }
    if (state.currentFilter === "processing") {
      el.tableRowCount.textContent = activeCount > 0
        ? `${activeCount} / ${state.workersCount} worker aktív (LLM API)`
        : `0 / ${state.workersCount} worker (Készenlét)`;
    }
  }
}

function handlePdfUpdate(updated) {
  const idx = state.pdfs.findIndex(p => p.file_name === updated.file_name);
  if (idx !== -1) {
    state.pdfs[idx].status = updated.status;
    if (updated.tokens_used) state.pdfs[idx].tokens_used = updated.tokens_used;
    if (updated.json_path) state.pdfs[idx].json_path = updated.json_path;
    if (updated.error_message) state.pdfs[idx].error_message = updated.error_message;
  } else {
    state.pdfs.unshift(updated);
  }
  for (let i = 1; i <= state.workersCount; i++) {
    const slot = state.workerSlots[i];
    if (slot && slot.fileName === updated.file_name) {
      slot.status = updated.status;
      if (updated.tokens_used) slot.tokens = formatNumber(updated.tokens_used);
      if (updated.json_path) slot.jsonPath = updated.json_path;
      if (updated.error_message) slot.errorMessage = updated.error_message;
      patchWorkerSlotRow(i);
    }
  }
  if (state.currentFilter !== "processing") renderStandardTable();
}

function updateConfigDisplay() {
  const p = state.config.processing || {};
  el.dispModel.textContent = state.config.model || "gemini-3.5-flash-lite";
  el.dispWorkers.textContent = `${p.concurrent_workers || 2} szál`;
  el.dispCap.textContent = `${p.max_utilization_pct || 80}%`;

  el.cfgModel.value = state.config.model || "gemini-3.5-flash-lite";
  el.cfgWorkers.value = p.concurrent_workers || 2;
  el.valCfgWorkers.textContent = p.concurrent_workers || 2;
  el.cfgCap.value = p.max_utilization_pct || 80;
  el.valCfgCap.textContent = `${p.max_utilization_pct || 80}%`;

  // Key mode radios
  const mode = state.config.active_key_mode || "auto";
  if (el.radioModeAuto) el.radioModeAuto.checked = (mode === "auto");
  if (el.radioModeManual) el.radioModeManual.checked = (mode === "manual");
  if (el.manualKeySelect) el.manualKeySelect.style.display = (mode === "manual") ? "block" : "none";
}

// ─── Zero-Jitter Fixed Worker Table Architecture ────────────────────────────

function renderPdfTable() {
  if (el.tableTitle) {
    const titleMap = {
      processing: "Épp Feldolgozás Alatt (LLM API)",
      completed: "Befejezett PDF-ek",
      error: "Hibás PDF-ek",
      pending: "Várakozó & Bufferelt PDF-ek",
      all: "Összes PDF a Mappában"
    };
    el.tableTitle.textContent = titleMap[state.currentFilter] || "PDF Lista";
  }
  if (state.currentFilter === "processing") buildFixedWorkerTable();
  else renderStandardTable();
}

function buildFixedWorkerTable() {
  const existingRows = el.pdfTableBody.querySelectorAll("tr[data-worker-slot]");
  if (existingRows.length === state.workersCount) {
    for (let i = 1; i <= state.workersCount; i++) patchWorkerSlotRow(i);
    return;
  }
  el.pdfTableBody.innerHTML = "";
  for (let i = 1; i <= state.workersCount; i++) {
    const row = document.createElement("tr");
    row.setAttribute("data-worker-slot", i);
    row.id = `worker-slot-row-${i}`;
    row.innerHTML = `
      <td id="worker-slot-status-${i}"><span class="badge status-badge-pending">Worker #${i}: Készenlét</span></td>
      <td id="worker-slot-file-${i}" style="font-family: var(--font-mono); font-weight: 500; font-size: 0.8rem;">Készenlét (Várakozás feladatra)</td>
      <td id="worker-slot-tokens-${i}" style="font-family: var(--font-mono);">-</td>
      <td id="worker-slot-json-${i}" style="font-size: 0.78rem; color: var(--text-secondary);">-</td>
      <td id="worker-slot-action-${i}" style="text-align: right;"></td>
    `;
    el.pdfTableBody.appendChild(row);
    patchWorkerSlotRow(i);
  }
}

function patchWorkerSlotRow(workerId) {
  if (state.currentFilter !== "processing") return;
  const slot = state.workerSlots[workerId];
  if (!slot) return;
  const statusCell = document.getElementById(`worker-slot-status-${workerId}`);
  const fileCell = document.getElementById(`worker-slot-file-${workerId}`);
  const tokensCell = document.getElementById(`worker-slot-tokens-${workerId}`);
  const jsonCell = document.getElementById(`worker-slot-json-${workerId}`);
  const actionCell = document.getElementById(`worker-slot-action-${workerId}`);
  if (!statusCell) return;

  if (slot.status === "processing") {
    statusCell.innerHTML = `<span class="badge status-badge-processing">Worker #${workerId}: LLM Folyamatban</span>`;
    fileCell.textContent = slot.fileName || "-";
    tokensCell.textContent = (slot.tokens && slot.tokens !== "-") ? `~${slot.tokens} tok` : "Kiküldve...";
    jsonCell.textContent = "-";
    actionCell.innerHTML = "";
  } else if (slot.status === "completed") {
    statusCell.innerHTML = `<span class="badge status-badge-completed">Worker #${workerId}: Befejezve</span>`;
    fileCell.textContent = slot.fileName || "-";
    tokensCell.textContent = slot.tokens || "-";
    const jName = slot.jsonPath ? slot.jsonPath.split(/[\\/]/).pop() : "-";
    jsonCell.textContent = jName;
    actionCell.innerHTML = slot.fileName && slot.fileName !== "-"
      ? `<button class="btn-view-json" onclick="viewJsonModal('${escapeHtml(slot.fileName)}')">Kivonat</button>` : "";
  } else if (slot.status === "error") {
    statusCell.innerHTML = `<span class="badge status-badge-error" title="${escapeHtml(slot.errorMessage || '')}">Worker #${workerId}: Hiba</span>`;
    fileCell.textContent = slot.fileName || "-";
    tokensCell.textContent = "-";
    jsonCell.textContent = slot.errorMessage ? `Hiba: ${slot.errorMessage.substring(0, 30)}...` : "Hiba";
    actionCell.innerHTML = "";
  } else {
    statusCell.innerHTML = `<span class="badge status-badge-pending">Worker #${workerId}: Készenlét</span>`;
    fileCell.textContent = (slot.fileName && slot.fileName !== "-") ? slot.fileName : "Készenlét (Várakozás feladatra)";
    tokensCell.textContent = slot.tokens || "-";
    jsonCell.textContent = slot.jsonPath ? slot.jsonPath.split(/[\\/]/).pop() : "-";
    actionCell.innerHTML = (slot.fileName && slot.fileName !== "-" && slot.jsonPath)
      ? `<button class="btn-view-json" onclick="viewJsonModal('${escapeHtml(slot.fileName)}')">Kivonat</button>` : "";
  }
}

function renderStandardTable() {
  const filtered = state.pdfs.filter(pdf => {
    let matchFilter = false;
    if (state.currentFilter === "all") matchFilter = true;
    else if (state.currentFilter === "pending") matchFilter = (pdf.status === "pending" || pdf.status === "buffered");
    else matchFilter = (pdf.status === state.currentFilter);
    const matchSearch = !state.searchQuery || pdf.file_name.toLowerCase().includes(state.searchQuery);
    return matchFilter && matchSearch;
  });

  const labels = { completed: "elkészült", error: "hiba", pending: "várakozó/bufferelt", all: "összesen" };
  el.tableRowCount.textContent = `${filtered.length} ${labels[state.currentFilter] || "összesen"}`;

  if (filtered.length === 0) {
    el.pdfTableBody.innerHTML = `<tr><td colspan="5" class="table-empty">Nincs a szűrésnek megfelelő PDF fájl.</td></tr>`;
    return;
  }

  el.pdfTableBody.innerHTML = filtered.slice(0, 300).map(pdf => {
    const statusMap = {
      pending: `<span class="badge status-badge-pending">Várakozó</span>`,
      buffered: `<span class="badge status-badge-buffered">Előkészítve (Buffer)</span>`,
      processing: `<span class="badge status-badge-processing">LLM API Kiküldve</span>`,
      completed: `<span class="badge status-badge-completed">Kész</span>`,
      error: `<span class="badge status-badge-error" title="${escapeHtml(pdf.error_message || '')}">Hiba</span>`
    };
    const statusBadge = statusMap[pdf.status] || `<span class="badge badge-subtle">${pdf.status}</span>`;
    const tokens = pdf.tokens_used ? formatNumber(pdf.tokens_used) : "-";
    const jsonName = pdf.json_path ? pdf.json_path.split(/[\\/]/).pop() : "-";
    const hasJson = Boolean(pdf.json_path);
    return `<tr>
      <td>${statusBadge}</td>
      <td title="${escapeHtml(pdf.file_name)}" style="font-weight: 500; font-family: var(--font-mono); font-size: 0.8rem;">${escapeHtml(pdf.file_name)}</td>
      <td style="font-family: var(--font-mono);">${tokens}</td>
      <td style="font-size: 0.78rem; color: var(--text-secondary);">${escapeHtml(jsonName)}</td>
      <td style="text-align: right;">${hasJson ? `<button class="btn-view-json" onclick="viewJsonModal('${escapeHtml(pdf.file_name)}')">Kivonat</button>` : ""}</td>
    </tr>`;
  }).join("");
}

async function fetchPdfs(silent = false) {
  try {
    const res = await fetch("/api/pdfs?limit=5000");
    if (!res.ok) return;
    const data = await res.json();
    state.pdfs = data.pdfs || [];
    renderStandardTable();
  } catch (e) { if (!silent) console.error("Failed to fetch PDFs", e); }
}

// ─── Actions & Event Listeners ──────────────────────────────────────────────

el.btnStart.addEventListener("click", async () => {
  try {
    const res = await fetch("/api/start", { method: "POST" });
    const data = await res.json();
    if (data.status === "empty_queue") alert("Nincs várakozó PDF a mappában!");
    if (data.status === "no_api_keys") alert("Nincs API kulcs konfigurálva! Adj hozzá egyet a beállításokban.");
    fetchPdfs();
  } catch (e) { alert("Hiba a feldolgozás indításakor: " + e); }
});

el.btnStop.addEventListener("click", async () => {
  try {
    el.btnStop.disabled = true;
    el.statusText.textContent = "Leállítás folyamatban (szálak befejezése)...";
    el.globalStatusBox.className = "status-indicator-box warning";
    appendLogLine(el.systemTerminalBody, "Leállítás kérve. Megvárjuk, amíg a folyamatban lévő szálak befejeződnek...", "warning");
    await fetch("/api/stop", { method: "POST" });
  } catch (e) {
    alert("Hiba a leállítás kérésekor: " + e);
  }
});

el.btnScan.addEventListener("click", async () => {
  try {
    const res = await fetch("/api/scan", { method: "POST" });
    const data = await res.json();
    appendLogLine(el.systemTerminalBody, `Szkennelés befejezve: ${data.total_scanned} PDF összesen, ${data.new_added} új hozzáadva.`, "success");
    fetchPdfs();
  } catch (e) { alert("Hiba a szkennelésnél: " + e); }
});

el.btnRetry.addEventListener("click", async () => {
  try {
    const res = await fetch("/api/retry-errors", { method: "POST" });
    if (!res.ok) throw new Error(`Szerver hiba (${res.status})`);
    const data = await res.json();
    appendLogLine(el.systemTerminalBody, `${data.reset_count} hibás elem visszaállítva.`, "info");
    fetchPdfs();
  } catch (e) { alert("Hiba: " + e.message); }
});

el.btnOpenPdf.addEventListener("click", async () => {
  await fetch("/api/open-folder", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ folder: "pdf" }) });
});

el.btnOpenJson.addEventListener("click", async () => {
  await fetch("/api/open-folder", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ folder: "json" }) });
});

if (el.btnOpenObsidian) {
  el.btnOpenObsidian.addEventListener("click", async () => {
    await fetch("/api/open-folder", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ folder: "obsidian" }) });
  });
}

if (el.btnGenObsidian) {
  el.btnGenObsidian.addEventListener("click", async () => {
    try {
      if (el.btnObsidianText) el.btnObsidianText.textContent = "Feldolgozás...";
      el.btnGenObsidian.disabled = true;
      const res = await fetch("/api/obsidian/generate", { method: "POST" });
      if (res.ok) {
        const data = await res.json();
        if (data.status === "up_to_date" || (data.status === "ok" && data.new_count === 0)) {
          if (el.btnObsidianText) el.btnObsidianText.textContent = "Minden friss (0 új)";
        } else if (data.status === "ok" && data.new_count > 0) {
          if (el.btnObsidianText) el.btnObsidianText.textContent = `+${data.new_count} új tanulmány!`;
        } else {
          if (el.btnObsidianText) el.btnObsidianText.textContent = "Kész!";
        }
        setTimeout(() => {
          if (el.btnObsidianText) el.btnObsidianText.textContent = "Obsidian Brain";
          el.btnGenObsidian.disabled = false;
        }, 3200);
      } else {
        throw new Error("Szerver hiba");
      }
    } catch (e) {
      if (el.btnObsidianText) el.btnObsidianText.textContent = "Hiba történt";
      setTimeout(() => {
        if (el.btnObsidianText) el.btnObsidianText.textContent = "Obsidian Brain";
        el.btnGenObsidian.disabled = false;
      }, 3000);
    }
  });
}

// Search & Filter
el.pdfSearchInput.addEventListener("input", (e) => {
  state.searchQuery = e.target.value.trim().toLowerCase();
  if (state.searchQuery && state.currentFilter === "processing") {
    el.filterPills.forEach(p => p.classList.toggle("active", p.dataset.filter === "all"));
    state.currentFilter = "all";
  }
  renderPdfTable();
});

el.filterPills.forEach(pill => {
  pill.addEventListener("click", () => {
    el.filterPills.forEach(p => p.classList.remove("active"));
    pill.classList.add("active");
    state.currentFilter = pill.dataset.filter;
    renderPdfTable();
  });
});

el.autoscrollToggle.addEventListener("change", (e) => { state.autoScroll = e.target.checked; });

el.btnClearLogs.addEventListener("click", () => {
  for (let i = 1; i <= state.workersCount; i++) window.clearWorkerLog(i);
  el.systemTerminalBody.innerHTML = "";
});

// Settings Modal
el.btnSettingsToggle.addEventListener("click", () => {
  renderModalKeyList();
  el.settingsModal.classList.add("open");
});
el.btnSettingsClose.addEventListener("click", () => { el.settingsModal.classList.remove("open"); });

el.cfgWorkers.addEventListener("input", (e) => { el.valCfgWorkers.textContent = e.target.value; });
el.cfgCap.addEventListener("input", (e) => { el.valCfgCap.textContent = `${e.target.value}%`; });

// Key mode radio buttons
if (el.radioModeAuto) {
  el.radioModeAuto.addEventListener("change", () => {
    if (el.manualKeySelect) el.manualKeySelect.style.display = "none";
  });
}
if (el.radioModeManual) {
  el.radioModeManual.addEventListener("change", () => {
    if (el.manualKeySelect) el.manualKeySelect.style.display = "block";
  });
}

// Key mode toggle buttons on dashboard
if (el.btnKeyModeAuto) {
  el.btnKeyModeAuto.addEventListener("click", async () => {
    try {
      await fetch("/api/keys/active", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mode: "auto" })
      });
      state.activeKeyMode = "auto";
      state.config.active_key_mode = "auto";
      if (el.radioModeAuto) el.radioModeAuto.checked = true;
      if (el.manualKeySelect) el.manualKeySelect.style.display = "none";
      renderKeyCards();
      appendLogLine(el.systemTerminalBody, "Kulcsválasztás: AUTOMATIKUS mód aktiválva", "success");
    } catch (e) { alert("Hiba: " + e); }
  });
}

if (el.btnKeyModeManual) {
  el.btnKeyModeManual.addEventListener("click", async () => {
    const keys = state.config.api_keys || [];
    if (keys.length === 0) { alert("Nincs API kulcs konfigurálva!"); return; }
    const firstKey = keys[0].id;
    try {
      await fetch("/api/keys/active", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mode: "manual", key_id: state.activeKeyId || firstKey })
      });
      state.activeKeyMode = "manual";
      state.config.active_key_mode = "manual";
      if (el.radioModeManual) el.radioModeManual.checked = true;
      if (el.manualKeySelect) el.manualKeySelect.style.display = "block";
      renderKeyCards();
      appendLogLine(el.systemTerminalBody, "Kulcsválasztás: KÉZI mód aktiválva", "info");
    } catch (e) { alert("Hiba: " + e); }
  });
}

// Add key button
if (el.btnAddKey) {
  el.btnAddKey.addEventListener("click", async () => {
    const keyVal = document.getElementById("new-key-value").value.trim();
    const label = document.getElementById("new-key-label").value.trim();
    const rpm = parseInt(document.getElementById("new-key-rpm")?.value, 10) || 15;
    const tpm = parseInt(document.getElementById("new-key-tpm")?.value, 10) || 250000;
    const rpd = parseInt(document.getElementById("new-key-rpd")?.value, 10) || 500;

    if (!keyVal) { alert("Add meg az API kulcsot!"); return; }

    try {
      const res = await fetch("/api/keys/add", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ key: keyVal, label: label || null, rpm, tpm, rpd })
      });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || "Hiba");
      }
      const data = await res.json();

      // Add to local state
      state.config.api_keys = state.config.api_keys || [];
      state.config.api_keys.push({ id: data.key_id, key: keyVal, label: label || `Kulcs #${state.config.api_keys.length + 1}`, rpm, tpm, rpd });

      // Clear form
      document.getElementById("new-key-value").value = "";
      document.getElementById("new-key-label").value = "";
      if (document.getElementById("new-key-rpm")) document.getElementById("new-key-rpm").value = "15";
      if (document.getElementById("new-key-tpm")) document.getElementById("new-key-tpm").value = "250000";
      if (document.getElementById("new-key-rpd")) document.getElementById("new-key-rpd").value = "500";

      renderKeyCards();
      renderModalKeyList();
      appendLogLine(el.systemTerminalBody, `Új API kulcs hozzáadva: ${label || data.key_id}`, "success");
    } catch (e) {
      alert("Hiba: " + e.message);
    }
  });
}

// Save Settings (model, workers, cap, key mode)
el.btnSaveSettings.addEventListener("click", async () => {
  const payload = {
    model: el.cfgModel.value,
    concurrent_workers: parseInt(el.cfgWorkers.value, 10),
    max_utilization_pct: parseInt(el.cfgCap.value, 10),
  };

  try {
    const res = await fetch("/api/config", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
    const data = await res.json();
    state.config = data.config;
    updateConfigDisplay();

    if (state.workersCount !== payload.concurrent_workers) {
      setupWorkerTerminals(payload.concurrent_workers);
    }

    // Save key mode
    const keyMode = el.radioModeManual && el.radioModeManual.checked ? "manual" : "auto";
    const manualKeyId = el.selectManualKey ? el.selectManualKey.value : null;
    await fetch("/api/keys/active", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mode: keyMode, key_id: keyMode === "manual" ? manualKeyId : null })
    });
    state.activeKeyMode = keyMode;
    state.config.active_key_mode = keyMode;

    el.settingsModal.classList.remove("open");
    appendLogLine(el.systemTerminalBody, "Beállítások sikeresen elmentve.", "success");
    renderKeyCards();
  } catch (e) {
    alert("Hiba a mentésnél: " + e);
  }
});

// JSON Viewer Modal
window.viewJsonModal = async function(fileName) {
  el.jsonModalTitle.textContent = `Kivonat: ${fileName}`;
  el.jsonModalPre.textContent = "Betöltés...";
  el.jsonModal.classList.add("open");
  try {
    const res = await fetch(`/api/json-view/${encodeURIComponent(fileName)}`);
    if (!res.ok) throw new Error("JSON nem található");
    const json = await res.json();
    el.jsonModalPre.textContent = JSON.stringify(json, null, 2);
  } catch (e) {
    el.jsonModalPre.textContent = "Hiba a JSON betöltésekor: " + e.message;
  }
};

el.btnJsonClose.addEventListener("click", () => { el.jsonModal.classList.remove("open"); });

window.addEventListener("click", (e) => {
  if (e.target === el.settingsModal) el.settingsModal.classList.remove("open");
  if (e.target === el.jsonModal) el.jsonModal.classList.remove("open");
});

window.resetQuotaCounter = async function(keyId = null) {
  try {
    const res = await fetch("/api/quota/reset", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ api_key_id: keyId || null })
    });
    const data = await res.json();
    if (res.ok) {
      showToast(keyId ? "Kulcs kvóta számláló sikeresen nullázva!" : "Összes kvóta számláló sikeresen nullázva!", "success");
      fetchPdfs();
    } else {
      showToast("Hiba a kvóta nullázásakor: " + (data.detail || "Ismeretlen"), "error");
    }
  } catch (err) {
    showToast("Hiba: " + err.message, "error");
  }
};

// ─── 1-Second Sliding Window Decay & Countdown Ticker ───────────────────────

function startSecondTickers() {
  updateRpdCountdown();
  setInterval(() => {
    updateRpdCountdown();
  }, 1000);
}

// ─── Initial REST Data Pre-fetch ───────────────────────────────────────────

async function loadInitialData() {
  try {
    const [statusRes, keysRes, pdfsRes] = await Promise.allSettled([
      fetch("/api/status"),
      fetch("/api/keys"),
      fetch("/api/pdfs?limit=5000")
    ]);

    if (statusRes.status === "fulfilled" && statusRes.value.ok) {
      const data = await statusRes.value.json();
      if (data.config) state.config = data.config;
      updateConfigDisplay();
      if (data.metrics) {
        state.perKeyUsage = data.metrics.per_key_usage || [];
        state.activeKeyId = data.metrics.active_key_id;
        state.activeKeyMode = data.metrics.active_key_mode || "auto";
        dispatchMetricsUpdate(data.metrics, data.stats);
      }
    }

    if (keysRes.status === "fulfilled" && keysRes.value.ok) {
      const kdata = await keysRes.value.json();
      if (kdata.keys && kdata.keys.length > 0) {
        state.config.api_keys = kdata.keys;
      }
      if (kdata.per_key_usage && kdata.per_key_usage.length > 0) {
        state.perKeyUsage = kdata.per_key_usage;
      }
      if (kdata.active_key_id) state.activeKeyId = kdata.active_key_id;
      if (kdata.active_key_mode) state.activeKeyMode = kdata.active_key_mode;
    }

    if (pdfsRes.status === "fulfilled" && pdfsRes.value.ok) {
      const pdata = await pdfsRes.value.json();
      state.pdfs = pdata.pdfs || [];
    }

    renderKeyCards();
    renderCompactKeyChips();
    renderModalKeyList();
    renderStandardTable();
  } catch (e) {
    console.warn("loadInitialData error:", e);
  }
}

// ─── Initialize ─────────────────────────────────────────────────────────────

document.addEventListener("DOMContentLoaded", () => {
  if (el.btnToggleKeysCollapse) {
    el.btnToggleKeysCollapse.addEventListener("click", toggleKeysCollapse);
  }
  updateKeysCollapseView();
  startAnimationEngine();
  startSecondTickers();
  setupWorkerTerminals(state.workersCount);
  loadInitialData();
  initWebSocket();
});

