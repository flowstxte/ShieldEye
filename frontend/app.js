const proto     = location.protocol === "https:" ? "wss:" : "ws:";
const WS_URL    = `${proto}//${location.host}/ws`;
const MAX_ALERTS = 100;

// State
let socket       = null;
let alerts       = [];
let activeFilter = "all";
let counts       = { critical: 0, high: 0, medium: 0, low: 0 };
let feedStarted  = false;

// DOM refs
const canvas     = document.getElementById("video-canvas");
const ctx        = canvas.getContext("2d");
const noSignal   = document.getElementById("no-signal");
const feedStatus = document.getElementById("feed-status");
const detBar     = document.getElementById("det-bar");
const alertList  = document.getElementById("alert-list");
const connEl     = document.getElementById("conn-indicator");
const connText   = document.getElementById("conn-text");
const clockEl    = document.getElementById("clock");
const liveDot    = document.getElementById("live-dot");
const toastWrap  = document.getElementById("toast-wrap");

// Clock
function tickClock() {
  const n = new Date();
  clockEl.textContent =
    String(n.getHours()).padStart(2,"0") + ":" +
    String(n.getMinutes()).padStart(2,"0") + ":" +
    String(n.getSeconds()).padStart(2,"0");
}
setInterval(tickClock, 1000);
tickClock();

// WebSocket
function connect() {
  setConn("connecting");

  // Reset feed state on every (re)connect attempt
  feedStarted = false;
  noSignal.classList.remove("hidden");
  liveDot.classList.remove("live");

  socket = new WebSocket(WS_URL);

  socket.onopen = () => setConn("connected");

  socket.onmessage = (e) => {
    try { handle(JSON.parse(e.data)); }
    catch(err) { console.error("[WS] Parse error:", err); }
  };

  socket.onclose = () => {
    setConn("disconnected");
    document.getElementById("stat-fps").textContent = "—";
    document.getElementById("stat-persons-val").textContent = "0";
    setTimeout(connect, 3000);
  };

  socket.onerror = () => socket.close();
}

function handle(msg) {
  switch (msg.type) {

    case "frame":
      drawFrame(msg.data);
      updateDet(msg.detections || []);
      if (msg.fps) document.getElementById("stat-fps").textContent = msg.fps.toFixed(1);

      if (!feedStarted) {
        feedStarted = true;
        noSignal.classList.add("hidden");
        liveDot.classList.add("live");
      }
      break;

    case "alert":
      addAlert(msg.alert, true);
      break;

    case "alert_history":
      alerts = [];
      counts = { critical: 0, high: 0, medium: 0, low: 0 };
      for (const a of (msg.alerts || [])) {
        if (!alerts.find(x => x.id === a.id)) {
          alerts.push(a);
          counts[a.severity] = (counts[a.severity] || 0) + 1;
        }
      }
      document.getElementById("stat-alert-count").textContent = alerts.length;
      renderAlerts();
      renderCounts();
      break;

    case "alerts_cleared":
      alerts  = [];
      counts  = { critical: 0, high: 0, medium: 0, low: 0 };
      renderAlerts();
      renderCounts();
      document.getElementById("stat-alert-count").textContent = "0";
      break;

    case "camera_error":
      const subMsg = noSignal.querySelector(".sub");
      if (subMsg) subMsg.textContent = msg.message;
      feedStatus.textContent = "NO SOURCE";
      feedStatus.className   = "feed-status alert-state";
      break;
  }
}

// Reusable Image buffer with frame queue to eliminate memory churn and frame jitter
const frameImg = new Image();
let isRendering = false;
let pendingFrame = null;

frameImg.onload = () => {
  if (canvas.width !== frameImg.naturalWidth || canvas.height !== frameImg.naturalHeight) {
    canvas.width  = frameImg.naturalWidth;
    canvas.height = frameImg.naturalHeight;
  }
  ctx.drawImage(frameImg, 0, 0, canvas.width, canvas.height);
  isRendering = false;

  if (pendingFrame) {
    const next = pendingFrame;
    pendingFrame = null;
    isRendering = true;
    frameImg.src = next;
  }
};

function drawFrame(b64) {
  const src = "data:image/jpeg;base64," + b64;
  if (isRendering) {
    pendingFrame = src;
  } else {
    isRendering = true;
    frameImg.src = src;
  }
}

// Detection bar + feed status badge
function updateDet(dets) {
  document.getElementById("stat-persons-val").textContent = dets.length;

  if (!dets.length) {
    detBar.innerHTML       = '<span class="det-empty">No active detections</span>';
    feedStatus.textContent = "LIVE";
    feedStatus.className   = "feed-status live";
    return;
  }

  let hasAlert = false, hasSuspect = false;
  detBar.innerHTML = dets.map(d => {
    const s = d.suspicion || 0;
    let cls = "normal";
    if      (s >= 0.75) { cls = "alert";   hasAlert   = true; }
    else if (s >= 0.30) { cls = "suspect"; hasSuspect = true; }
    return `<span class="det-tag ${cls}">#${d.id} ${d.label} ${Math.round(s*100)}%</span>`;
  }).join("");

  if      (hasAlert)   { feedStatus.textContent = "ALERT";   feedStatus.className = "feed-status alert-state"; }
  else if (hasSuspect) { feedStatus.textContent = "WATCH";   feedStatus.className = "feed-status suspect"; }
  else                 { feedStatus.textContent = "LIVE";    feedStatus.className = "feed-status live"; }
}

// Alert management
function addAlert(a, isNew) {
  if (alerts.find(x => x.id === a.id)) return;  // deduplicate
  alerts.unshift(a);
  if (alerts.length > MAX_ALERTS) {
    const dropped = alerts.pop();
    if (dropped && counts[dropped.severity] > 0) {
      counts[dropped.severity]--;
    }
  }
  counts[a.severity] = (counts[a.severity] || 0) + 1;
  document.getElementById("stat-alert-count").textContent = alerts.length;
  renderAlerts(isNew ? a.id : null);
  renderCounts();

  if (isNew && (a.severity === "critical" || a.severity === "high")) {
    showToast(a);
  }
}

function renderAlerts(flashId) {
  const list = activeFilter === "all"
    ? alerts
    : alerts.filter(a => a.severity === activeFilter);

  if (!list.length) {
    alertList.innerHTML = `
      <div class="alert-empty">
        <p>No alerts yet</p>
        <p class="sub">Suspicious activity will appear here</p>
      </div>`;
    return;
  }

  const ICONS = { critical:"🚨", high:"🔶", medium:"⚠️", low:"ℹ️" };

  alertList.innerHTML = list.map(a => {
    const score    = a.suspicion_score || 0;
    const barColor = score >= 0.75 ? "#f43f5e" : score >= 0.4 ? "#f59e0b" : "#22d3a0";
    const isFlash  = a.id === flashId;
    return `
      <div class="alert-card ${a.severity}" ${isFlash ? 'style="animation:slide-in 0.2s ease"' : ""}>
        <div class="card-top">
          <span class="card-title">${ICONS[a.severity]||"📋"} ${esc(a.title)}</span>
          <span class="card-time">${esc(a.time_str||"")}</span>
        </div>
        <div class="card-detail">${esc(a.detail||"")}</div>
        <div class="card-footer">
          <span class="badge ${a.severity}">${a.severity}</span>
          <span class="badge track">Person #${a.track_id}</span>
        </div>
        ${score > 0 ? `
        <div class="sus-wrap">
          <span class="sus-label">Risk</span>
          <div class="sus-track">
            <div class="sus-fill" style="width:${Math.round(score*100)}%;background:${barColor}"></div>
          </div>
          <span class="sus-pct">${Math.round(score*100)}%</span>
        </div>` : ""}
      </div>`;
  }).join("");
}

function renderCounts() {
  document.getElementById("cnt-critical").textContent = counts.critical || 0;
  document.getElementById("cnt-high").textContent     = counts.high     || 0;
  document.getElementById("cnt-medium").textContent   = counts.medium   || 0;
  document.getElementById("cnt-low").textContent      = counts.low      || 0;
}

// Toast notification popups
function showToast(alert) {
  if (!toastWrap) return;
  const ICONS = { critical: "🚨", high: "🔶", medium: "⚠️", low: "ℹ️" };
  const toast = document.createElement("div");
  toast.className = `toast ${alert.severity}`;
  toast.innerHTML = `
    <span>${ICONS[alert.severity] || "📋"}</span>
    <div>
      <strong>${esc(alert.title)}</strong> — ${esc(alert.detail)}
    </div>
  `;
  toastWrap.appendChild(toast);
  setTimeout(() => {
    if (toast.parentNode) toast.parentNode.removeChild(toast);
  }, 4300);
}

// Filter tabs
document.querySelectorAll(".ftab").forEach(btn => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".ftab").forEach(b => b.classList.remove("active"));
    btn.classList.add("active");
    activeFilter = btn.dataset.filter;
    renderAlerts();
  });
});

// Clear alerts
document.getElementById("clear-btn").addEventListener("click", async () => {
  try {
    await fetch("/api/alerts/clear", { method: "POST" });
  } catch {
    // Fallback if API unreachable — clear locally
    alerts = [];
    counts = { critical:0, high:0, medium:0, low:0 };
    renderAlerts();
    renderCounts();
    document.getElementById("stat-alert-count").textContent = "0";
  }
});

// Connection state
function setConn(state) {
  connEl.className   = `conn ${state}`;
  connText.textContent = { connecting:"connecting", connected:"connected", disconnected:"reconnecting" }[state];
}

// HTML escape
function esc(s) {
  const d = document.createElement("div");
  d.appendChild(document.createTextNode(String(s)));
  return d.innerHTML;
}

connect();

// --- Resizable Panel Logic (Pointer Events for Mouse, Stylus & Touch) ---
const resizer = document.getElementById('drag-resizer');
let isResizing = false;

resizer.addEventListener('pointerdown', (e) => {
  isResizing = true;
  resizer.classList.add('dragging');
  resizer.setPointerCapture(e.pointerId);
  document.body.style.userSelect = 'none'; 
});

resizer.addEventListener('pointermove', (e) => {
  if (!isResizing) return;
  let newWidth = window.innerWidth - e.clientX;
  if (newWidth < 280) newWidth = 280; // Minimum width
  if (newWidth > 800) newWidth = 800; // Maximum width
  document.documentElement.style.setProperty('--panel-width', `${newWidth}px`);
});

const stopResize = (e) => {
  if (isResizing) {
    isResizing = false;
    resizer.classList.remove('dragging');
    try { resizer.releasePointerCapture(e.pointerId); } catch {}
    document.body.style.userSelect = '';
  }
};

resizer.addEventListener('pointerup', stopResize);
resizer.addEventListener('pointercancel', stopResize);