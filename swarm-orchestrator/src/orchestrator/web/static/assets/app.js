// Swarm Orchestrator — frontend single-page app.
// No build step. Plain ES modules, runs directly in the browser.

const API = "/api/v1";
const TOKEN_KEY = "swarm.api_token";

// ─── State ─────────────────────────────────────────────

const state = {
    status: null,
    config: null,
    topology: null,
    summaries: [], // most-recent first
    transcript: [], // chronological
    events: [], // most-recent first, capped
    nextTriggerAt: null, // unix seconds, for timer mode
    ws: null,
    wsRetry: 0,
    route: "dashboard",
};

const MAX_EVENTS = 500;
const MAX_TRANSCRIPT = 500;
const MAX_SUMMARIES = 50;

// ─── Utilities ─────────────────────────────────────────

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

function escapeHtml(s) {
    return String(s ?? "")
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
}

function fmtTime(ts) {
    if (!ts) return "—";
    const d = new Date(ts * 1000);
    return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

function fmtDate(iso) {
    if (!iso) return "—";
    const d = new Date(iso);
    if (isNaN(d)) return String(iso);
    return d.toLocaleString();
}

function fmtDuration(seconds) {
    if (seconds == null || seconds < 0) return "—";
    const s = Math.floor(seconds);
    const h = Math.floor(s / 3600);
    const m = Math.floor((s % 3600) / 60);
    const sec = s % 60;
    if (h > 0) return `${h}h ${m}m ${sec}s`;
    if (m > 0) return `${m}m ${sec}s`;
    return `${sec}s`;
}

function getToken() {
    return localStorage.getItem(TOKEN_KEY) || "";
}
function setToken(t) {
    if (t) localStorage.setItem(TOKEN_KEY, t);
    else localStorage.removeItem(TOKEN_KEY);
}

async function apiFetch(path, options = {}) {
    const headers = new Headers(options.headers || {});
    const token = getToken();
    if (token) headers.set("Authorization", `Bearer ${token}`);
    if (options.body && !headers.has("Content-Type")) {
        headers.set("Content-Type", "application/json");
    }
    const res = await fetch(`${API}${path}`, { ...options, headers });
    if (!res.ok) {
        let detail = res.statusText;
        try {
            const j = await res.json();
            detail = j.detail || detail;
        } catch {}
        const err = new Error(detail);
        err.status = res.status;
        throw err;
    }
    if (res.status === 204) return null;
    return res.json();
}

// ─── Data loaders ──────────────────────────────────────

async function refreshStatus() {
    try {
        state.status = await apiFetch("/status");
        updateChrome();
        return state.status;
    } catch (e) {
        console.warn("status fetch failed", e);
    }
}

async function refreshConfig() {
    try {
        state.config = await apiFetch("/config");
        updateChrome();
    } catch (e) {
        console.warn("config fetch failed", e);
    }
}

async function refreshTopology() {
    try {
        state.topology = await apiFetch("/topology");
    } catch (e) {
        console.warn("topology fetch failed", e);
    }
}

async function refreshTranscript() {
    try {
        const data = await apiFetch("/transcript?limit=200");
        state.transcript = data.entries || [];
    } catch (e) {
        console.warn("transcript fetch failed", e);
    }
}

async function refreshSummaries() {
    try {
        const data = await apiFetch("/summaries?limit=50");
        state.summaries = (data.summaries || []).map(wrapSummary);
    } catch (e) {
        console.warn("summaries fetch failed", e);
    }
}

function wrapSummary(s, origin = "unknown", sourceName = "") {
    return {
        summary: s,
        origin,
        source_name: sourceName,
        received_at: Date.now() / 1000,
    };
}

// ─── WebSocket ─────────────────────────────────────────

function connectWebSocket() {
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const url = `${protocol}//${window.location.host}/ws`;
    setConnection("connecting", "Connecting…");

    try {
        state.ws = new WebSocket(url);
    } catch (e) {
        scheduleReconnect();
        return;
    }

    state.ws.addEventListener("open", () => {
        state.wsRetry = 0;
        setConnection("connected", "Live");
    });

    state.ws.addEventListener("message", (ev) => {
        let msg;
        try { msg = JSON.parse(ev.data); }
        catch { return; }
        handleEvent(msg);
    });

    state.ws.addEventListener("close", () => {
        setConnection("disconnected", "Disconnected");
        scheduleReconnect();
    });

    state.ws.addEventListener("error", () => {
        try { state.ws.close(); } catch {}
    });
}

function scheduleReconnect() {
    const delay = Math.min(1000 * Math.pow(2, state.wsRetry), 30000);
    state.wsRetry += 1;
    setTimeout(connectWebSocket, delay);
}

function setConnection(status, text) {
    const dot = $(".connection .dot");
    const txt = $("#connection-text");
    if (dot) dot.dataset.status = status;
    if (txt) txt.textContent = text;
}

// ─── Event handling ────────────────────────────────────

function handleEvent(evt) {
    if (!evt || evt.type === "ping") return;

    // Prepend to event log (most recent first), cap length
    state.events.unshift(evt);
    if (state.events.length > MAX_EVENTS) state.events.length = MAX_EVENTS;

    switch (evt.type) {
        case "round.phase":
            if (state.status) {
                state.status.phase = evt.data.phase;
                state.status.round_number = evt.data.round;
            }
            if (evt.data.phase === "DISCUSS" && state.config?.rounds?.mode === "timer") {
                state.nextTriggerAt = Date.now() / 1000 + state.config.rounds.interval_seconds;
            } else {
                state.nextTriggerAt = null;
            }
            updateChrome();
            if (state.route === "dashboard") renderDashboardLive();
            break;

        case "round.complete":
            refreshStatus();
            break;

        case "message.received": {
            state.transcript.push({
                timestamp: evt.data.timestamp,
                sender: evt.data.sender,
                body: evt.data.body,
                is_swarm_signal: evt.data.is_swarm_signal,
            });
            if (state.transcript.length > MAX_TRANSCRIPT) {
                state.transcript.splice(0, state.transcript.length - MAX_TRANSCRIPT);
            }
            if (state.status?.transcript) {
                state.status.transcript.message_count = evt.data.message_count;
                state.status.transcript.participant_count = evt.data.participant_count;
            }
            if (state.route === "transcript") renderTranscriptLive();
            if (state.route === "dashboard") renderDashboardLive();
            break;
        }

        case "summary.created": {
            const wrapped = wrapSummary(
                evt.data.summary,
                evt.data.origin || "local",
                evt.data.source_name || "",
            );
            state.summaries.unshift(wrapped);
            if (state.summaries.length > MAX_SUMMARIES) state.summaries.length = MAX_SUMMARIES;
            if (state.route === "summaries") renderSummariesView();
            if (state.route === "dashboard") renderDashboardLive();
            break;
        }
    }

    if (state.route === "events") prependEventItem(evt);
    if (state.route === "dashboard") appendActivity(evt);
}

// ─── Router ────────────────────────────────────────────

const routes = {
    dashboard:  { title: "Dashboard",  render: renderDashboard },
    summaries:  { title: "Summaries",  render: renderSummariesView },
    transcript: { title: "Transcript", render: renderTranscriptView },
    topology:   { title: "Topology",   render: renderTopologyView },
    events:     { title: "Events",     render: renderEventsView },
    settings:   { title: "Settings",   render: renderSettingsView },
};

function navigate() {
    const hash = window.location.hash.replace(/^#\/?/, "") || "dashboard";
    const route = routes[hash] ? hash : "dashboard";
    state.route = route;

    $$(".nav-item").forEach(el => {
        el.classList.toggle("active", el.dataset.route === route);
    });
    $("#view-title").textContent = routes[route].title;
    routes[route].render();
}

// ─── Views ─────────────────────────────────────────────

function mountTemplate(id) {
    const tmpl = document.getElementById(id);
    const view = $("#view");
    view.innerHTML = "";
    view.appendChild(tmpl.content.cloneNode(true));
}

function bindText(selector, text) {
    const el = $(selector);
    if (el) el.textContent = text;
}

function renderDashboard() {
    mountTemplate("view-dashboard");
    renderDashboardLive();

    const btn = $("#btn-trigger");
    const statusLine = $("#trigger-status");
    btn.addEventListener("click", async () => {
        const token = getToken();
        if (!token) {
            statusLine.className = "status-line is-err";
            statusLine.textContent = "Set an API token in Settings first.";
            return;
        }
        btn.disabled = true;
        statusLine.className = "status-line";
        statusLine.textContent = "Triggering…";
        try {
            const res = await apiFetch("/rounds/trigger", { method: "POST" });
            statusLine.className = "status-line is-ok";
            statusLine.textContent = res.message || "Trigger signalled.";
        } catch (e) {
            statusLine.className = "status-line is-err";
            statusLine.textContent = `Error: ${e.message}`;
        } finally {
            btn.disabled = false;
            setTimeout(() => { statusLine.textContent = ""; statusLine.className = "status-line"; }, 6000);
        }
    });

    // Seed the activity feed from recent events history
    state.events.slice(0, 20).forEach(appendActivity);
}

function renderDashboardLive() {
    if (state.route !== "dashboard") return;
    const s = state.status;
    const t = s?.transcript || {};

    bindText("[data-bind='phase']", s?.phase || "—");
    bindText("[data-bind='round']", `Round ${s?.round_number ?? "—"}`);
    bindText("[data-bind='message_count']", t.message_count ?? "—");
    bindText("[data-bind='participant_count']", t.participant_count ?? "—");
    bindText("[data-bind='token_estimate']", t.token_estimate ?? "—");
    bindText("[data-bind='uptime']", fmtDuration(s?.uptime_seconds));
    bindText("[data-bind='subscribers']", s?.websocket_subscribers ?? 0);

    const modeBadge = $("[data-bind='mode-badge']");
    if (modeBadge) modeBadge.textContent = s?.mode ? s.mode.toUpperCase() : "—";

    const countdown = $("#countdown-value");
    const countdownCard = $("#countdown");
    if (s?.mode === "timer" && state.nextTriggerAt) {
        const remaining = Math.max(0, state.nextTriggerAt - Date.now() / 1000);
        if (countdown) countdown.textContent = fmtDuration(remaining);
    } else if (s?.mode === "timer") {
        if (countdown) countdown.textContent = fmtDuration(s.interval_seconds);
    } else {
        if (countdownCard) countdownCard.style.display = "none";
    }

    renderLatestSummary();
}

function renderLatestSummary() {
    const container = $("#latest-summary");
    const originBadge = $("#latest-origin");
    if (!container) return;
    const latest = state.summaries[0];
    if (!latest) {
        container.innerHTML = `<div class="empty-state">No summaries yet. Waiting for the first round&hellip;</div>`;
        if (originBadge) originBadge.textContent = "—";
        return;
    }
    container.innerHTML = renderSummaryInner(latest);
    if (originBadge) {
        const isLocal = latest.origin === "local";
        originBadge.textContent = isLocal ? "Local" : "Federation";
        originBadge.className = `badge ${isLocal ? "badge-local" : "badge-federation"}`;
    }
}

function appendActivity(evt) {
    const feed = $("#activity-feed");
    if (!feed) return;
    const li = document.createElement("li");
    li.innerHTML = `
        <span class="event-time">${escapeHtml(fmtTime(evt.timestamp))}</span>
        <span class="event-type">${escapeHtml(evt.type)}</span>
        <span class="event-data">${escapeHtml(summarizeEventData(evt))}</span>
    `;
    feed.prepend(li);
    while (feed.children.length > 30) feed.removeChild(feed.lastChild);
}

function summarizeEventData(evt) {
    const d = evt.data || {};
    switch (evt.type) {
        case "round.phase":       return `phase=${d.phase} round=${d.round}`;
        case "round.complete":    return `next_round=${d.next_round}`;
        case "round.failed":      return `round=${d.round}`;
        case "round.manual_trigger": return `source=${d.source || "?"}`;
        case "message.received":  return `${d.sender || "?"}: ${(d.body || "").slice(0, 120)}`;
        case "summary.created":   return `origin=${d.origin} source=${d.source_name || "?"} round=${d.summary?.round_number}`;
        case "orchestrator.running": return `node=${d.node_id} v${d.version || "?"}`;
        default: return JSON.stringify(d).slice(0, 160);
    }
}

// ─── Summaries view ────────────────────────────────────

function renderSummariesView() {
    mountTemplate("view-summaries");
    const list = $("#summary-list");
    const filter = $("#summary-filter");
    const count = $("#summary-count");

    const draw = () => {
        const q = (filter?.value || "").toLowerCase();
        const items = state.summaries.filter(w => {
            if (!q) return true;
            const s = w.summary;
            const hay = [
                s.topic, s.source_node_id, w.source_name,
                s.emerging_consensus,
                ...(s.key_positions || []),
                ...(s.dissenting_views || []),
                ...(s.open_questions || []),
            ].join(" ").toLowerCase();
            return hay.includes(q);
        });
        count.textContent = `${items.length} summaries`;
        list.innerHTML = items.length
            ? items.map(w => `<div class="summary-card origin-${escapeHtml(w.origin)}">${renderSummaryInner(w)}</div>`).join("")
            : `<div class="empty-state">No summaries match.</div>`;
    };
    filter.addEventListener("input", draw);
    draw();
}

function renderSummaryInner(wrapped) {
    const s = wrapped.summary;
    const isLocal = wrapped.origin === "local";
    const source = wrapped.source_name || s.source_node_id;
    const positions = (s.key_positions || []).map(p => `<li>${escapeHtml(p)}</li>`).join("");
    const dissent = (s.dissenting_views || []).map(p => `<li>${escapeHtml(p)}</li>`).join("");
    const questions = (s.open_questions || []).map(p => `<li>${escapeHtml(p)}</li>`).join("");

    return `
        <div class="summary-header">
            <div>
                <div class="summary-title">Round ${escapeHtml(s.round_number)} &middot; ${escapeHtml(source)}</div>
                <div class="summary-meta">${escapeHtml(s.source_node_id)} &middot; ${escapeHtml(fmtDate(s.published))}</div>
            </div>
            <span class="badge ${isLocal ? "badge-local" : "badge-federation"}">
                ${isLocal ? "Local" : "Federation"}
            </span>
        </div>
        ${s.topic ? `<div class="summary-topic">${escapeHtml(s.topic)}</div>` : ""}
        <div class="summary-section">
            <div class="summary-section-label">&#x1F4CC; Key Positions</div>
            <ul>${positions || "<li><em>none</em></li>"}</ul>
        </div>
        ${s.emerging_consensus ? `
            <div class="summary-section">
                <div class="summary-section-label">&#x1F91D; Emerging Consensus</div>
                <p>${escapeHtml(s.emerging_consensus)}</p>
            </div>
        ` : ""}
        ${dissent ? `
            <div class="summary-section">
                <div class="summary-section-label">&#x26A1; Dissenting Views</div>
                <ul>${dissent}</ul>
            </div>
        ` : ""}
        ${questions ? `
            <div class="summary-section">
                <div class="summary-section-label">&#x2753; Open Questions</div>
                <ul>${questions}</ul>
            </div>
        ` : ""}
        <div class="summary-section" style="font-size:12px;color:var(--text-muted);">
            ${s.participant_count ?? 0} participants &middot; ${s.message_count ?? 0} messages
        </div>
    `;
}

// ─── Transcript view ───────────────────────────────────

function renderTranscriptView() {
    mountTemplate("view-transcript");
    renderTranscriptLive();
}

function renderTranscriptLive() {
    if (state.route !== "transcript") return;
    const log = $("#transcript-log");
    const meta = $("#transcript-meta");
    if (!log) return;

    if (!state.transcript.length) {
        log.innerHTML = `<div class="empty-state">No messages yet.</div>`;
    } else {
        log.innerHTML = state.transcript.map(renderMessage).join("");
    }

    const s = state.status?.transcript;
    if (meta) meta.textContent = `${s?.message_count ?? state.transcript.length} messages / ${s?.participant_count ?? "?"} participants`;
    log.scrollTop = log.scrollHeight;
}

function renderMessage(e) {
    const cls = e.is_swarm_signal ? "is-signal" : "";
    return `
        <div class="msg ${cls}">
            <div class="msg-sender">${escapeHtml(e.sender)}</div>
            <div class="msg-body">${escapeHtml(e.body)}</div>
            <div class="msg-time">${escapeHtml(fmtTime(e.timestamp))}</div>
        </div>
    `;
}

// ─── Topology view ─────────────────────────────────────

function renderTopologyView() {
    mountTemplate("view-topology");

    const topo = state.topology;
    const meta = $("#topology-meta");
    const list = $("#topology-list");
    const svg = $("#topology-svg");
    if (!topo || !topo.nodes?.length) {
        if (list) list.innerHTML = `<div class="empty-state">No topology loaded.</div>`;
        if (svg) svg.innerHTML = "";
        if (meta) meta.textContent = "0 nodes";
        return;
    }

    if (meta) meta.textContent = `${topo.nodes.length} nodes`;

    // Render simple circular layout
    const cx = 400, cy = 250, r = 180;
    const nodes = topo.nodes;
    const angle = (i) => (2 * Math.PI * i) / Math.max(nodes.length, 1) - Math.PI / 2;
    const pos = nodes.map((n, i) => ({
        n,
        x: cx + r * Math.cos(angle(i)),
        y: cy + r * Math.sin(angle(i)),
    }));
    const selfIdx = pos.findIndex(p => p.n.is_self);
    const self = selfIdx >= 0 ? pos[selfIdx] : pos[0];

    const edges = pos
        .filter(p => !p.n.is_self && (p.n.role === "participant" || p.n.role === "facilitator"))
        .map(p => `<line x1="${self.x}" y1="${self.y}" x2="${p.x}" y2="${p.y}" stroke="rgba(244,166,42,0.35)" stroke-width="1.5" stroke-dasharray="4 4"/>`)
        .join("");

    const dots = pos.map(p => {
        const color = p.n.is_self ? "#f4a62a" : "#60a5fa";
        const strokeColor = p.n.is_self ? "#ffd166" : "#93c5fd";
        return `
            <g>
                <circle cx="${p.x}" cy="${p.y}" r="22" fill="${color}" stroke="${strokeColor}" stroke-width="2" opacity="0.9"/>
                <text x="${p.x}" y="${p.y + 4}" text-anchor="middle" fill="#0b0f17" font-size="11" font-weight="700" font-family="system-ui, sans-serif">
                    ${escapeHtml((p.n.name || p.n.id).slice(0, 3).toUpperCase())}
                </text>
                <text x="${p.x}" y="${p.y + 44}" text-anchor="middle" fill="#e8ecf4" font-size="11" font-family="ui-monospace, monospace">
                    ${escapeHtml(p.n.id)}
                </text>
            </g>
        `;
    }).join("");

    svg.innerHTML = `
        <defs>
            <radialGradient id="centerGlow" cx="50%" cy="50%" r="50%">
                <stop offset="0%" stop-color="rgba(244,166,42,0.12)"/>
                <stop offset="100%" stop-color="rgba(244,166,42,0)"/>
            </radialGradient>
        </defs>
        <rect x="0" y="0" width="800" height="500" fill="url(#centerGlow)"/>
        ${edges}
        ${dots}
    `;

    list.innerHTML = topo.nodes.map(n => `
        <div class="node-card ${n.is_self ? "is-self" : ""}">
            <div class="node-name">${escapeHtml(n.name || n.id)}${n.is_self ? ' <span class="badge badge-local">this node</span>' : ""}</div>
            <div class="node-domain">${escapeHtml(n.domain || "—")}</div>
            <div class="node-role">${escapeHtml(n.role)}${n.has_public_key ? " &middot; key loaded" : " &middot; no key"}</div>
        </div>
    `).join("");
}

// ─── Events view ───────────────────────────────────────

function renderEventsView() {
    mountTemplate("view-events");
    const log = $("#event-log");
    log.innerHTML = state.events.map(renderEventItem).join("");
    $("#btn-clear-events").addEventListener("click", () => {
        state.events = [];
        log.innerHTML = "";
    });
}

function renderEventItem(evt) {
    return `
        <li>
            <span class="event-time">${escapeHtml(fmtTime(evt.timestamp))}</span>
            <span class="event-type">${escapeHtml(evt.type)}</span>
            <span class="event-data">${escapeHtml(summarizeEventData(evt))}</span>
        </li>
    `;
}

function prependEventItem(evt) {
    const log = $("#event-log");
    if (!log) return;
    log.insertAdjacentHTML("afterbegin", renderEventItem(evt));
    while (log.children.length > MAX_EVENTS) log.removeChild(log.lastChild);
}

// ─── Settings view ─────────────────────────────────────

function renderSettingsView() {
    mountTemplate("view-settings");

    const input = $("#api-token-input");
    const status = $("#token-status");
    input.value = getToken();

    $("#btn-save-token").addEventListener("click", () => {
        setToken(input.value.trim());
        status.className = "status-line is-ok";
        status.textContent = "Token saved.";
        setTimeout(() => { status.textContent = ""; }, 3000);
    });
    $("#btn-clear-token").addEventListener("click", () => {
        setToken("");
        input.value = "";
        status.className = "status-line is-ok";
        status.textContent = "Token cleared.";
        setTimeout(() => { status.textContent = ""; }, 3000);
    });

    $("#config-dump").textContent = state.config
        ? JSON.stringify(state.config, null, 2)
        : "Loading…";
}

// ─── Chrome updates ────────────────────────────────────

function updateChrome() {
    const s = state.status;
    const c = state.config;

    const chipPhase = $("#chip-phase");
    const chipRound = $("#chip-round");
    const chipMode = $("#chip-mode");
    const nodeBadge = $("#node-badge");

    if (chipPhase) {
        const phase = s?.phase || "—";
        chipPhase.textContent = `Phase: ${phase}`;
        chipPhase.className = `chip phase-${phase}`;
    }
    if (chipRound) chipRound.textContent = `Round: ${s?.round_number ?? "—"}`;
    if (chipMode) chipMode.textContent = `Mode: ${s?.mode ?? "—"}`;
    if (nodeBadge) nodeBadge.textContent = c?.node?.id ?? s?.node?.id ?? "—";
}

// ─── Boot ──────────────────────────────────────────────

async function boot() {
    window.addEventListener("hashchange", navigate);
    navigate();

    await Promise.all([
        refreshStatus(),
        refreshConfig(),
        refreshTopology(),
        refreshTranscript(),
        refreshSummaries(),
    ]);
    navigate(); // re-render with data
    connectWebSocket();

    // Periodic status refresh (fallback in case WS misses something)
    setInterval(refreshStatus, 15000);

    // Tick the dashboard countdown once per second
    setInterval(() => {
        if (state.route === "dashboard") renderDashboardLive();
    }, 1000);
}

boot();
