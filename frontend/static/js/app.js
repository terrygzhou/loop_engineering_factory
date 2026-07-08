/**
 * Loop Engineering UI — Client-side application
 * Connects via WebSocket for real-time progress and REST API for state management.
 */

// ─── Configuration ────────────────────────────────────────────────
const CONFIG = {
  wsUrl: `${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/ws/progress`,
  apiBase: '/api',
  pollingInterval: 5000,
};

// ─── State ──────────────────────────────────────────────────────
const state = {
  workflow: { status: 'idle', cycle: 0, phase: '', waitingFor: null, projectName: '' },
  phases: {},
  messages: [],
  interviewActive: false,
  interviewPhase: null,
  reconnectAttempts: 0,
  maxReconnectAttempts: 10,
  metrics: {},
  thresholds: {},
  // Track which artifact keys we've already shown (dedup)
  shownArtifacts: {},
  // Track which log entries we've already rendered (by index)
  lastRenderedMsgCount: 0,
};

// ─── DOM Elements ─────────────────────────────────────────────────
const dom = {
  cycleNum: document.getElementById('cycle-num'),
  statusBadge: document.getElementById('status-badge'),
  statusDot: document.querySelector('.status-dot'),
  statusText: document.querySelector('.status-text'),
  btnStart: document.getElementById('btn-start'),
  btnAbort: document.getElementById('btn-abort'),
  pipeline: document.getElementById('pipeline'),
  progressLog: document.getElementById('progress-log'),
  detailSection: document.getElementById('detail-section'),
  detailTitle: document.getElementById('detail-title'),
  detailContent: document.getElementById('detail-content'),
  phaseTabs: document.getElementById('phase-tabs'),
  modalOverlay: document.getElementById('modal-overlay'),
  modalTitle: document.getElementById('modal-title'),
  modalBody: document.getElementById('modal-body'),
  modalClose: document.getElementById('modal-close'),
  btnSubmit: document.getElementById('btn-submit'),
  btnCancel: document.getElementById('btn-cancel'),
  projectBadge: document.getElementById('project-badge'),
  projectName: document.getElementById('project-name'),
  metricsGrid: document.getElementById('metrics-grid'),
};

// ─── Initialization ─────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  console.log('[App] Initializing...');
  connectWebSocket();
  startPolling();
  setupEventListeners();
  fetchStatus();
  fetchMetrics();
});

// ─── WebSocket Connection ─────────────────────────────────────────
function connectWebSocket() {
  if (state.ws && state.ws.readyState === WebSocket.OPEN) {
    return;
  }

  try {
    state.ws = new WebSocket(CONFIG.wsUrl);

    state.ws.onopen = () => {
      console.log('[WS] Connected');
      state.reconnectAttempts = 0;
    };

    state.ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        handleProgressEvent(data);
      } catch (e) {
        console.error('[WS] Parse error:', e);
      }
    };

    state.ws.onclose = () => {
      console.log('[WS] Disconnected');
      attemptReconnect();
    };

    state.ws.onerror = (err) => {
      console.error('[WS] Error:', err);
    };
  } catch (err) {
    console.error('[WS] Connection failed:', err);
    attemptReconnect();
  }
}

function attemptReconnect() {
  if (state.reconnectAttempts >= state.maxReconnectAttempts) {
    console.error('[WS] Max reconnect attempts reached');
    return;
  }
  state.reconnectAttempts++;
  const delay = Math.min(1000 * state.reconnectAttempts, 10000);
  console.log(`[WS] Reconnecting in ${delay}ms (attempt ${state.reconnectAttempts})`);
  setTimeout(connectWebSocket, delay);
}

// ─── REST API ──────────────────────────────────────────────────────
async function fetchStatus() {
  try {
    const res = await fetch(`${CONFIG.apiBase}/status`);
    const data = await res.json();
    updateState(data);
    renderAll();
  } catch (err) {
    console.error('[API] Fetch status failed:', err);
  }
}

async function fetchMetrics() {
  try {
    const res = await fetch(`${CONFIG.apiBase}/metrics`);
    const data = await res.json();
    state.metrics = data.current || {};
    state.thresholds = data.thresholds || {};
    renderMetrics();
  } catch (err) {
    console.error('[API] Fetch metrics failed:', err);
  }
}

async function startWorkflow() {
  const projectName = document.getElementById('req-project-name')?.value?.trim() || '';
  const spec = document.getElementById('req-spec')?.value?.trim() || '';
  try {
    const res = await fetch(`${CONFIG.apiBase}/start`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ project_name: projectName, spec }),
    });
    const data = await res.json();
    console.log('[API] Workflow started:', data);
    renderAll();
  } catch (err) {
    console.error('[API] Start workflow failed:', err);
  }
}

async function abortWorkflow() {
  try {
    const res = await fetch(`${CONFIG.apiBase}/abort`, { method: 'POST' });
    const data = await res.json();
    console.log('[API] Workflow aborted:', data);
    state.workflow.status = 'idle';
    state.interviewActive = false;
    renderAll();
  } catch (err) {
    console.error('[API] Abort workflow failed:', err);
  }
}

async function submitInput(phase, inputType, value) {
  try {
    const res = await fetch(`${CONFIG.apiBase}/input`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ phase, input_type: inputType, value }),
    });
    const data = await res.json();
    console.log('[API] Input submitted:', data);
    closeModal();
  } catch (err) {
    console.error('[API] Submit input failed:', err);
  }
}

// ─── State Management ─────────────────────────────────────────────
function updateState(data) {
  state.workflow = {
    status: data.status,
    cycle: data.cycle,
    phase: data.phase,
    waitingFor: data.waitingFor,
    projectName: data.projectName || state.workflow.projectName || '',
  };
  if (data.phases) {
    state.phases = data.phases.reduce((acc, phase) => {
      acc[phase.phase] = phase;
      return acc;
    }, {});
  }
  if (data.messages) {
    state.messages = data.messages;
  }
  // Also refresh metrics on each status poll
  fetchMetrics();
}

function handleProgressEvent(event) {
  state.messages.push(event);
  if (event.phase in state.phases) {
    updatePhaseState(event.phase, event.action, event.data, event);
  }

  // Clear interview state when workflow completes
  if (event.phase === 'SYSTEM' && event.action === 'completed') {
    state.interviewActive = false;
    state.workflow.status = 'complete';
    renderAll();
    return;
  }

  // Handle explicit workflow abort — clean reset without error flash
  if (event.phase === 'SYSTEM' && event.action === 'aborted') {
    state.interviewActive = false;
    state.workflow.status = 'idle';
    for (const phaseName in state.phases) {
      state.phases[phaseName] = {
        ...state.phases[phaseName],
        status: 'pending',
        artifacts: {},
        messages: [],
      };
    }
    state.shownArtifacts = {};
    state.lastRenderedMsgCount = 0;
    renderAll();
    return;
  }

  // Handle workflow error (genuine failure) — reset to idle with error styling
  if (event.phase === 'SYSTEM' && event.action === 'error') {
    state.interviewActive = false;
    state.workflow.status = 'error';
    state.shownArtifacts = {};
    state.lastRenderedMsgCount = 0;
    renderAll();
    return;
  }

  // Handle skill-driven interview (bridge sends data.fields or data.questions)
  if (event.action === 'interview' && event.data && (event.data.fields || event.data.questions)) {
    // Skip duplicate: already showing interview for this phase
    if (state.interviewActive && state.interviewPhase === event.phase) return;
    renderInterview(event.phase, event.data.fields || event.data.questions);
    return;
  }

  // Handle architecture review with Mermaid diagram rendering
  if (event.action === 'review' && event.data && event.data.type === 'arch_review') {
    renderArchReview(event.phase, event.data);
    return;
  }

  // Handle human review of DEFINE output
  if (event.action === 'review' && event.data && event.data.type === 'human_review') {
    renderReview(event.phase, event.data);
    return;
  }

  // Deduplicate: only render new progress entries
  if (event.action === 'artifact') {
    renderArtifactEvent(event);
    return;
  }

  renderProgressEvent(event);
}

function updatePhaseState(phase, action, data, event) {
  if (!state.phases[phase]) {
    state.phases[phase] = { phase, status: 'pending', messages: [], artifacts: {} };
  }
  const ps = state.phases[phase];
  switch (action) {
    case 'started':
      ps.status = 'running';
      ps.startedAt = event?.timestamp;
      break;
    case 'progress':
      ps.messages.push(event);
      break;
    case 'waiting':
      ps.status = 'waiting';
      // If backend is waiting for review approval, show modal immediately
      if (data && data.type === 'review_approval') {
        showInputModal(phase);
      }
      break;
    case 'completed':
      ps.status = 'complete';
      ps.completedAt = event?.timestamp;
      break;
    case 'error':
      ps.status = 'error';
      break;
    case 'artifact':
      if (data && data.artifact_name) {
        ps.artifacts[data.artifact_name] = data.artifact_value;
      }
      break;
  }
}

// ─── Rendering ────────────────────────────────────────────────────
function renderAll() {
  renderStatus();
  renderPipeline();
  renderProgressLog();
  renderPhaseTabs();
  renderDetail();
  renderMetrics();
}

function renderStatus() {
  const { status, cycle, projectName } = state.workflow;
  dom.cycleNum.textContent = cycle;

  // Project name badge
  if (projectName) {
    dom.projectBadge.style.display = 'inline-flex';
    dom.projectName.textContent = projectName;
  }

  // Status badge
  dom.statusBadge.className = `status-badge status-${status}`;
  dom.statusDot.className = `status-dot ${status}`;
  dom.statusText.textContent = status.toUpperCase();

  // Start button
  if (status === 'running' || status === 'waiting' || status === 'complete') {
    dom.btnStart.disabled = true;
    dom.btnStart.textContent = status === 'complete' ? 'Workflow Complete' : 'Running...';
  } else {
    dom.btnStart.disabled = false;
    dom.btnStart.textContent = 'Start Workflow';
  }

  // Abort button
  if (status === 'running' || status === 'waiting') {
    dom.btnAbort.style.display = 'inline-flex';
  } else {
    dom.btnAbort.style.display = 'none';
  }

  // Show modal if waiting for input
  if (state.workflow.waitingFor) {
    showInputModal(state.workflow.waitingFor);
  }
}

function renderPipeline() {
  const phases = dom.pipeline.querySelectorAll('.pipeline-phase');
  phases.forEach(el => {
    const phaseName = el.dataset.phase;
    const phase = state.phases[phaseName];
    if (!phase) return;

    // Make keyboard accessible
    if (!el.hasAttribute('role')) {
      el.setAttribute('role', 'button');
      el.setAttribute('tabindex', '0');
    }

    // Update status indicator with screen-reader text (not color alone — WCAG)
    const statusEl = el.querySelector('.phase-status');
    const statusText = phase.status || '';
    statusEl.className = `phase-status ${phase.status}`;
    statusEl.setAttribute('aria-label', statusText || 'pending');

    // Update phase card state
    el.className = 'pipeline-phase';
    if (phase.status === 'running') el.classList.add('running');
    if (phase.status === 'complete') el.classList.add('complete');
    if (phase.status === 'error') el.classList.add('error');
    if (phase.status === 'waiting') el.classList.add('waiting');
    if (phase.status === 'active' || state.workflow.phase === phaseName) el.classList.add('active');

    // Update ARIA label with current status
    el.setAttribute('aria-label', `${phaseName} phase — ${phase.status || 'pending'}`);
    el.setAttribute('aria-describedby', 'detail-title');

    // Phase duration
    const durationEl = el.querySelector('.phase-duration');
    if (phase.startedAt) {
      const start = new Date(phase.startedAt).getTime();
      const end = phase.completedAt ? new Date(phase.completedAt).getTime() : Date.now();
      const duration = formatDuration(end - start);
      durationEl.textContent = duration;
    } else {
      durationEl.textContent = '';
    }
  });
}

function renderProgressLog() {
  // Only append new entries — don't re-render the whole log
  const newMessages = state.messages.slice(state.lastRenderedMsgCount);
  if (newMessages.length === 0) return;

  // Hide empty state when first message arrives
  const emptyEl = document.getElementById('progress-empty');
  if (emptyEl && emptyEl.style.display !== 'none') {
    emptyEl.style.display = 'none';
  }

  newMessages.forEach((msg) => {
    // Deduplicate: skip artifact entries we've already shown
    if (msg.action === 'artifact') {
      const key = `${msg.phase}:${msg.data?.artifact_name}`;
      if (state.shownArtifacts[key]) return;
      state.shownArtifacts[key] = true;
    }

    const entry = document.createElement('div');
    entry.className = 'log-entry new';
    entry.innerHTML = `
      <span class="log-phase ${msg.phase}" aria-label="Phase: ${msg.phase}">${msg.phase}</span>
      <span class="log-message">
        <span class="log-action ${msg.action}" aria-label="Action: ${msg.action}">${msg.action}</span>
        ${escapeHtml(msg.message)}
      </span>
      <span class="log-time">${formatTime(msg.timestamp)}</span>
    `;
    dom.progressLog.appendChild(entry);
  });

  state.lastRenderedMsgCount = state.messages.length;

  // Auto-scroll to bottom
  dom.progressLog.parentElement.scrollTop = dom.progressLog.parentElement.scrollHeight;
}

function renderProgressEvent(event) {
  // Hide empty state when first message arrives
  const emptyEl = document.getElementById('progress-empty');
  if (emptyEl && emptyEl.style.display !== 'none') {
    emptyEl.style.display = 'none';
  }

  const entry = document.createElement('div');
  entry.className = 'log-entry new';
  entry.innerHTML = `
    <span class="log-phase ${event.phase}" aria-label="Phase: ${event.phase}">${event.phase}</span>
    <span class="log-message">
      <span class="log-action ${event.action}" aria-label="Action: ${event.action}">${event.action}</span>
      ${escapeHtml(event.message)}
    </span>
    <span class="log-time">${formatTime(event.timestamp)}</span>
  `;
  dom.progressLog.appendChild(entry);

  // Increment counter for next incremental render
  state.lastRenderedMsgCount = state.messages.length;
  dom.progressLog.parentElement.scrollTop = dom.progressLog.parentElement.scrollHeight;

  // Also update phase state
  if (event.phase in state.phases) {
    updatePhaseState(event.phase, event.action, event.data, event);
    renderPipeline();
  }
}

function renderArtifactEvent(event) {
  // Hide empty state when first message arrives
  const emptyEl = document.getElementById('progress-empty');
  if (emptyEl && emptyEl.style.display !== 'none') {
    emptyEl.style.display = 'none';
  }

  const key = `${event.phase}:${event.data?.artifact_name}`;
  if (state.shownArtifacts[key]) return;
  state.shownArtifacts[key] = true;

  const entry = document.createElement('div');
  entry.className = 'log-entry new';
  entry.innerHTML = `
    <span class="log-phase ${event.phase}" aria-label="Phase: ${event.phase}">${event.phase}</span>
    <span class="log-message">
      <span class="log-action ${event.action}" aria-label="Action: ${event.action}">${event.action}</span>
      ${escapeHtml(event.message)}
    </span>
    <span class="log-time">${formatTime(event.timestamp)}</span>
  `;
  dom.progressLog.appendChild(entry);
  state.lastRenderedMsgCount = state.messages.length;
  dom.progressLog.parentElement.scrollTop = dom.progressLog.parentElement.scrollHeight;
}

function renderPhaseTabs() {
  if (state.interviewActive) return;

  // Show tabs for phases that have artifacts
  const phasesWithArtifacts = Object.values(state.phases)
    .filter(p => p.status === 'complete' && p.artifacts && Object.keys(p.artifacts).length > 0);

  if (phasesWithArtifacts.length <= 1) {
    dom.phaseTabs.innerHTML = '';
    return;
  }

  const currentPhase = state.workflow.phase || phasesWithArtifacts[phasesWithArtifacts.length - 1]?.phase;

  dom.phaseTabs.innerHTML = phasesWithArtifacts.map(p => `
    <button class="phase-tab ${p.phase === currentPhase ? 'active' : ''}"
            data-phase="${p.phase}"
            onclick="selectPhaseTab('${p.phase}')">
      ${p.phase} <span class="tab-count">(${Object.keys(p.artifacts).length})</span>
    </button>
  `).join('');
}

// Called from onclick in phase tabs
window.selectPhaseTab = function(phaseName) {
  dom.phaseTabs.querySelectorAll('.phase-tab').forEach(tab => {
    tab.classList.toggle('active', tab.dataset.phase === phaseName);
  });
  renderDetailForPhase(phaseName);
};

function renderDetail() {
  // If there's an active interview, don't overwrite it
  if (state.interviewActive) return;

  if (state.workflow.waitingFor) {
    const phase = state.phases[state.workflow.waitingFor];
    if (phase) {
      dom.detailTitle.textContent = `${phase.phase} — Review Required`;
      dom.detailContent.innerHTML = `
        <p>Phase: ${phase.phase}</p>
        <p>Status: Waiting for your review and approval</p>
        ${phase.messages ? `<p>Messages: ${phase.messages.length}</p>` : ''}
        <p class="detail-placeholder">Submit your input to proceed...</p>
      `;
    }
    return;
  }

  // Check if a tab is active
  const activeTab = dom.phaseTabs.querySelector('.phase-tab.active');
  if (activeTab) {
    renderDetailForPhase(activeTab.dataset.phase);
    return;
  }

  // Default: show latest completed phase artifacts
  const completedPhases = Object.values(state.phases).filter(p => p.status === 'complete' && p.artifacts && Object.keys(p.artifacts).length > 0);
  if (completedPhases.length > 0) {
    const latest = completedPhases[completedPhases.length - 1];
    renderDetailForPhase(latest.phase);
  } else {
    dom.detailTitle.textContent = 'Phase Details';
    dom.detailContent.innerHTML = '<p class="detail-placeholder">Workflow output will appear here as phases complete</p>';
  }
}

function renderDetailForPhase(phaseName) {
  const phase = state.phases[phaseName];
  if (!phase) return;

  dom.detailTitle.textContent = `${phase.phase} — Output`;
  const duration = phase.startedAt && phase.completedAt
    ? formatDuration(new Date(phase.completedAt).getTime() - new Date(phase.startedAt).getTime())
    : (phase.startedAt ? formatDuration(Date.now() - new Date(phase.startedAt).getTime()) + ' (running)' : '—');

  let html = `<div class="detail-meta"><span>Duration: ${duration}</span><span>Artifacts: ${Object.keys(phase.artifacts || {}).length}</span></div>`;

  for (const [name, value] of Object.entries(phase.artifacts || {})) {
    const display = typeof value === 'object' ? JSON.stringify(value, null, 2) : String(value);
    // Truncate long artifacts in the log view
    const truncated = display.length > 500 ? display.slice(0, 500) + '\n\n... (truncated, ' + display.length + ' chars total)' : display;
    html += `<div class="detail-artifact">
      <span class="detail-artifact-name">${name}</span>
      <pre class="detail-artifact-value">${escapeHtml(truncated)}</pre>
    </div>`;
  }

  if (phase.messages && phase.messages.length > 0) {
    html += `<div class="detail-log"><strong>Activity Log</strong>`;
    phase.messages.slice(-5).forEach(m => {
      html += `<div class="detail-log-entry"><span class="log-action ${m.action}">${m.action}</span> ${escapeHtml(m.message)}</div>`;
    });
    html += `</div>`;
  }

  dom.detailContent.innerHTML = html;
}

// ─── Metrics Rendering ───────────────────────────────────────────
function renderMetrics() {
  const metricCards = dom.metricsGrid.querySelectorAll('.metric-card');
  const metrics = state.metrics || {};
  const thresholds = state.thresholds || {};

  metricCards.forEach(card => {
    const metricName = card.dataset.metric;
    const valueEl = card.querySelector('.metric-value');
    const statusEl = card.querySelector('.metric-status');

    if (!metrics[metricName]) {
      valueEl.textContent = '—';
      statusEl.textContent = 'pending';
      statusEl.className = 'metric-status';
      card.classList.remove('pass', 'fail', 'warn');
      return;
    }

    const value = metrics[metricName];
    valueEl.textContent = typeof value === 'number' ? (Number.isInteger(value) ? value : value.toFixed(2)) : value;

    // Determine pass/fail based on thresholds
    let status = 'pass';
    let statusText = 'pass';

    if (metricName === 'spec_confidence' && value < (thresholds.min_spec_confidence || 0.9)) {
      status = 'fail'; statusText = 'below threshold';
    } else if (metricName === 'arch_uncertainty' && value > (thresholds.max_arch_uncertainty || 0.8)) {
      status = 'fail'; statusText = 'above threshold';
    } else if (metricName === 'security_findings' && value > (thresholds.max_security_findings || 0)) {
      status = 'fail'; statusText = 'findings detected';
    } else if (metricName === 'review_revisions' && value > (thresholds.max_review_revisions || 2)) {
      status = 'warn'; statusText = 'exceeds threshold';
    } else if (metricName === 'uat_pass_rate' && value < (thresholds.uat_pass_rate || 0.95)) {
      status = 'fail'; statusText = 'below threshold';
    } else if (metricName === 'task_count') {
      status = 'info'; statusText = 'info';
    }

    statusEl.textContent = statusText;
    statusEl.className = `metric-status ${status}`;
    card.classList.remove('pass', 'fail', 'warn', 'info');
    card.classList.add(status);
  });
}

// ─── Modal ──────────────────────────────────────────────────────
function showInputModal(phase) {
  dom.modalTitle.textContent = `${phase} — User Input Required`;
  dom.modalBody.innerHTML = `
    <label for="user-input-text">Provide your input for the ${phase} phase:</label>
    <textarea id="user-input-text" placeholder="Enter your instructions, feedback, or approval..."></textarea>
  `;
  dom.modalOverlay.style.display = 'flex';

  // Setup submit button
  dom.btnSubmit.onclick = () => {
    const value = document.getElementById('user-input-text').value;
    if (value.trim()) {
      submitInput(phase, 'text', value);
    }
  };

  // Enter to submit
  document.getElementById('user-input-text').addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && e.ctrlKey) {
      dom.btnSubmit.click();
    }
  });

  // Focus textarea
  setTimeout(() => document.getElementById('user-input-text')?.focus(), 100);
}

function closeModal() {
  dom.modalOverlay.style.display = 'none';
}

// ─── Skill-driven Interview ─────────────────────────────────────
function renderInterview(phase, questions) {
  state.interviewActive = true;
  state.interviewPhase = phase;

  dom.detailTitle.textContent = `${phase} — Skill-Driven Interview`;
  dom.detailContent.innerHTML = `
    <div class="interview-intro">
      The <strong>interview-me</strong> skill is asking for your requirements.
      Answer each question below — your responses will feed directly into the spec.
    </div>
    <div class="interview-in-detail" id="interview-questions">
      ${questions.map((q, i) => `
        <div class="interview-question" style="--phase-color: var(--color-define);">
          <div class="q-category">${q.label}</div>
          <div class="q-text">${q.question}${q.required ? '<span class="q-required" aria-label="required field"> (required)</span>' : ''}</div>
          <label class="screen-reader-only" for="interview-answer-${i}">${q.question}</label>
          <textarea class="form-textarea interview-answer" id="interview-answer-${i}" data-index="${i}"
                    data-category="${q.category}" rows="2"
                    placeholder="${q.placeholder}"></textarea>
        </div>
      `).join('')}
    </div>
    <div class="interview-actions">
      <button class="btn btn-secondary" id="interview-cancel">Skip Interview</button>
      <button class="btn btn-primary" id="interview-submit">Submit Answers</button>
    </div>
  `;

  const finishInterview = () => {
    state.interviewActive = false;
    state.interviewPhase = null;
  };

  document.getElementById('interview-submit').addEventListener('click', () => {
    const answers = {};
    document.querySelectorAll('.interview-answer').forEach(ta => {
      const cat = ta.dataset.category;
      const val = ta.value.trim();
      if (val) answers[cat] = val;
    });

    // Validate required fields
    const requiredMissing = questions.filter(q => q.required && !answers[q.category]);
    if (requiredMissing.length > 0) {
      alert(`Please fill in required questions: ${requiredMissing.map(q => q.label).join(', ')}`);
      return;
    }

    // Format as structured text for the workflow
    const formatted = Object.entries(answers).map(([cat, val]) => {
      const q = questions.find(q => q.category === cat);
      return `[${(q || {}).label || cat}] ${val}`;
    }).join('\n\n');

    submitInput(phase, 'interview_answers', formatted);
    finishInterview();
    dom.detailTitle.textContent = `${phase} — Answers Submitted`;
    dom.detailContent.innerHTML = '<p class="detail-placeholder">Your answers have been submitted. The workflow will continue...</p>';
  });

  document.getElementById('interview-cancel').addEventListener('click', () => {
    submitInput(phase, 'skip_interview', 'User skipped interview');
    finishInterview();
    dom.detailTitle.textContent = `${phase} — Interview Skipped`;
    dom.detailContent.innerHTML = '<p class="detail-placeholder">Interview skipped. The workflow will continue with available context.</p>';
  });
}

// ─── Human Review (same as CLI: per-section approve/edit/reject) ──
function renderReview(phase, data) {
  state.interviewActive = true;
  state.interviewPhase = phase;

  const sections = data.sections || [];
  const summary = data.summary || {};
  const metrics = data.metrics || {};

  // Summary header
  let summaryHtml = '<div class="review-summary"><h3>Review Summary</h3>';
  for (const [key, desc] of Object.entries(summary)) {
    summaryHtml += `<p><strong>${key}:</strong> ${desc}</p>`;
  }
  if (metrics.spec_confidence != null) {
    summaryHtml += `<p><strong>spec_confidence:</strong> ${metrics.spec_confidence.toFixed(2)}</p>`;
  }
  summaryHtml += '</div>';

  // Per-section review blocks
  let sectionsHtml = sections.map((s, i) => {
    const content = s.content || '';
    const display = content ? escapeHtml(content) : '(not provided)';
    return `
      <div class="review-section" id="review-section-${i}">
        <div class="review-section-header">
          <h4>${s.label} (${s.word_count || 0} words)</h4>
          <div class="review-section-actions">
            <button class="btn btn-sm btn-approve" data-section="${s.key}" data-index="${i}">Approve</button>
            <button class="btn btn-sm btn-edit" data-section="${s.key}" data-index="${i}">Edit</button>
            <button class="btn btn-sm btn-reject" data-section="${s.key}" data-index="${i}">Reject</button>
          </div>
        </div>
        <div class="review-section-content">
          <pre class="detail-artifact-value">${display}</pre>
        </div>
        <div class="review-section-edit" id="review-edit-${i}" style="display:none;">
          <textarea class="form-textarea" id="review-edit-text-${i}" rows="10"
                    placeholder="Enter revised content...">${content}</textarea>
          <div class="review-edit-actions">
            <button class="btn btn-sm btn-save-edit" data-index="${i}" data-section="${s.key}">Save</button>
            <button class="btn btn-sm btn-cancel-edit" data-index="${i}">Cancel</button>
          </div>
        </div>
        <div class="review-section-feedback" id="review-feedback-${i}" style="display:none;">
          <textarea class="form-textarea" id="review-feedback-text-${i}" rows="2"
                    placeholder="Feedback on this section..."></textarea>
          <button class="btn btn-sm btn-submit-feedback" data-index="${i}" data-section="${s.key}">Submit Feedback</button>
        </div>
        <div class="review-section-status" id="review-status-${i}"></div>
      </div>
    `;
  }).join('');

  // Submit all button
  const actionsHtml = `
    <div class="review-actions">
      <button class="btn btn-secondary" id="review-cancel">Reject All</button>
      <button class="btn btn-primary" id="review-approve-all">Approve All</button>
    </div>
  `;

  dom.detailTitle.textContent = `${phase} — Human Review`;
  dom.detailContent.innerHTML = summaryHtml + sectionsHtml + actionsHtml;

  // Track per-section decisions: {key: {approved, comment?, edited?}}
  const reviewState = {};

  // Bind approve buttons
  document.querySelectorAll('.btn-approve').forEach(btn => {
    btn.addEventListener('click', () => {
      const idx = btn.dataset.index, key = btn.dataset.section;
      reviewState[key] = {approved: true};
      document.getElementById(`review-status-${idx}`).innerHTML = '<span class="status-approved">✓ Approved</span>';
    });
  });

  // Bind edit buttons
  document.querySelectorAll('.btn-edit').forEach(btn => {
    btn.addEventListener('click', () => {
      const idx = btn.dataset.index;
      document.getElementById(`review-edit-${idx}`).style.display = 'block';
      document.getElementById(`review-content-${idx}`).style.display = 'none';
    });
  });

  // Bind save edit buttons
  document.querySelectorAll('.btn-save-edit').forEach(btn => {
    btn.addEventListener('click', () => {
      const idx = btn.dataset.index, key = btn.dataset.section;
      const textarea = document.getElementById(`review-edit-text-${idx}`);
      const edited = textarea.value;
      reviewState[key] = {approved: true, edited: true, content: edited};
      document.getElementById(`review-status-${idx}`).innerHTML = '<span class="status-edited">✓ Edited & Approved</span>';
      document.getElementById(`review-edit-${idx}`).style.display = 'none';
    });
  });

  // Bind cancel edit buttons
  document.querySelectorAll('.btn-cancel-edit').forEach(btn => {
    btn.addEventListener('click', () => {
      const idx = btn.dataset.index;
      document.getElementById(`review-edit-${idx}`).style.display = 'none';
    });
  });

  // Bind reject buttons
  document.querySelectorAll('.btn-reject').forEach(btn => {
    btn.addEventListener('click', () => {
      const idx = btn.dataset.index;
      document.getElementById(`review-feedback-${idx}`).style.display = 'block';
    });
  });

  // Bind submit feedback buttons
  document.querySelectorAll('.btn-submit-feedback').forEach(btn => {
    btn.addEventListener('click', () => {
      const idx = btn.dataset.index, key = btn.dataset.section;
      const textarea = document.getElementById(`review-feedback-text-${idx}`);
      reviewState[key] = {approved: false, comment: textarea.value};
      document.getElementById(`review-status-${idx}`).innerHTML = '<span class="status-rejected">✗ Rejected — feedback sent</span>';
      document.getElementById(`review-feedback-${idx}`).style.display = 'none';
    });
  });

  // Approve all
  document.getElementById('review-approve-all').addEventListener('click', () => {
    const allSections = sections.map(s => s.key);
    const sectionFeedback = {};
    for (const key of allSections) {
      sectionFeedback[key] = reviewState[key] || {approved: true};
    }
    submitInput(phase, 'human_review', {approved: true, section_feedback: sectionFeedback});
    finishReview();
    dom.detailTitle.textContent = `${phase} — Approved`;
    dom.detailContent.innerHTML = '<p class="detail-placeholder">All sections approved. The workflow will continue to PLAN...</p>';
  });

  // Show a feedback modal before rejecting all
  function showReviewRejectModal(sectionFeedback) {
    dom.modalTitle.textContent = `${phase} — Reject All`;
    dom.modalBody.innerHTML = `
      <p>Please provide feedback explaining why you are rejecting all sections. This is <strong>required</strong>.</p>
      <textarea id="review-reject-text" class="form-textarea" rows="5"
                placeholder="Explain your feedback for rejecting all sections..."></textarea>
    `;
    dom.modalOverlay.style.display = 'flex';

    dom.btnSubmit.onclick = () => {
      const textarea = document.getElementById('review-reject-text');
      const comments = textarea.value.trim();
      if (!comments) {
        alert('Feedback is required to reject all sections.');
        textarea.focus();
        return;
      }
      submitInput(phase, 'human_review', {approved: false, feedback: {comments, sectionFeedback}});
      finishReview();
      dom.detailTitle.textContent = `${phase} — Rejected`;
      dom.detailContent.innerHTML = '<p class="detail-placeholder">Workflow will loop back to DEFINE for revisions.</p>';
    };

    setTimeout(() => document.getElementById('review-reject-text')?.focus(), 100);
  }

  // Reject all — show modal first
  document.getElementById('review-cancel').addEventListener('click', () => {
    const allSections = sections.map(s => s.key);
    const sectionFeedback = {};
    for (const key of allSections) {
      sectionFeedback[key] = reviewState[key] || {approved: false, comment: 'Rejected (no comment)'};
    }
    showReviewRejectModal(sectionFeedback);
  });

  function finishReview() {
    state.interviewActive = false;
    state.interviewPhase = null;
  }
}

// ─── Architecture Review with Mermaid Diagram Rendering ──────────
function renderArchReview(phase, data) {
  state.interviewActive = true;
  state.interviewPhase = phase;

  // Get PNG data URLs from backend
  const diagramPngs = data.diagram_pngs || {};
  const pngKeys = Object.keys(diagramPngs);

  // Fallback to old diagram format if no PNGs
  const diagrams = data.diagrams || {};
  const rawKeys = Object.keys(diagrams);
  const usePng = pngKeys.length > 0;

  const keys = usePng ? pngKeys : rawKeys;

  // Build tabbed diagram viewer
  let tabsHtml = '<div class="diagram-tabs" role="tablist">';
  keys.forEach((key, i) => {
    const label = key.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
    tabsHtml += `<button class="diagram-tab ${i === 0 ? 'active' : ''}" data-tab="${key}">${label}</button>`;
  });
  tabsHtml += '</div>';

  let panelsHtml = '<div class="diagram-panels">';
  keys.forEach((key, i) => {
    if (usePng) {
      const dataUrl = diagramPngs[key] || '';
      panelsHtml += `<div class="diagram-panel ${i === 0 ? 'active' : ''}" id="diagram-panel-${key}" data-diagram="${key}">
        <div class="diagram-image-container">
          ${dataUrl ? `<img src="${dataUrl}" alt="${key.replace(/_/g, ' ')}" class="diagram-image">` : '<p>No diagram generated</p>'}
        </div>
      </div>`;
    } else {
      const raw = diagrams[key];
      panelsHtml += `<div class="diagram-panel ${i === 0 ? 'active' : ''}" id="diagram-panel-${key}" data-diagram="${key}">
        <div class="mermaid-container"><div class="mermaid" id="mermaid-${key}">${raw || 'No diagram generated'}</div></div>
        <div class="diagram-source-toggle"><button class="btn btn-sm btn-secondary" onclick="toggleSource('${key}')">Toggle Source</button></div>
        <pre class="diagram-source" id="source-${key}" style="display:none;">${raw || ''}</pre>
      </div>`;
    }
  });
  panelsHtml += '</div>';

  // Review summary
  const summaryHtml = `
    <div class="review-summary">
      <h3>Architecture Review</h3>
      <p>Review the generated architecture diagrams. Approve to proceed to BUILD, or reject with feedback to loop back to DEFINE.</p>
    </div>
  `;

  // Feedback textarea
  const feedbackHtml = `
    <div class="review-feedback">
      <label class="form-label">Comments / Feedback (optional)</label>
      <textarea class="form-textarea" id="arch-review-feedback" rows="3" placeholder="Notes for the next cycle if rejected..."></textarea>
    </div>
  `;

  // Action buttons
  const actionsHtml = `
    <div class="review-actions">
      <button class="btn btn-secondary" id="arch-review-reject">Reject — Loop Back</button>
      <button class="btn btn-primary" id="arch-review-approve">Approve — Proceed to BUILD</button>
    </div>
  `;

  dom.detailTitle.textContent = `${phase} — Architecture Review`;
  dom.detailContent.innerHTML = tabsHtml + panelsHtml + summaryHtml + feedbackHtml + actionsHtml;

  // Render Mermaid diagrams (only for fallback mode)
  if (!usePng) {
    const renderAll = async () => {
      for (const key of rawKeys) {
        try {
          const el = document.getElementById(`mermaid-${key}`);
          if (el && el.textContent.trim() !== 'No diagram generated') {
            await mermaid.run({nodes: [el]});
          }
        } catch (e) {
          console.error(`Mermaid render failed for ${key}:`, e);
        }
      }
    };
    renderAll();
  }

  // Tab switching
  document.querySelectorAll('.diagram-tab').forEach(tab => {
    tab.addEventListener('click', () => {
      document.querySelectorAll('.diagram-tab').forEach(t => t.classList.remove('active'));
      document.querySelectorAll('.diagram-panel').forEach(p => p.classList.remove('active'));
      tab.classList.add('active');
      const panel = document.getElementById(`diagram-panel-${tab.dataset.tab}`);
      if (panel) panel.classList.add('active');
    });
  });

  // Approve button
  document.getElementById('arch-review-approve').addEventListener('click', () => {
    submitInput(phase, 'arch_review', {
      approved: true,
      feedback: document.getElementById('arch-review-feedback').value,
    });
    finishInterview();
    dom.detailTitle.textContent = `${phase} — Approved`;
    dom.detailContent.innerHTML = '<p class="detail-placeholder">Architecture approved. Workflow will proceed to BUILD phase.</p>';
  });

  // Reject button
  document.getElementById('arch-review-reject').addEventListener('click', () => {
    const feedback = document.getElementById('arch-review-feedback').value || 'No feedback provided';
    submitInput(phase, 'arch_review', {
      approved: false,
      feedback: feedback,
    });
    finishInterview();
    dom.detailTitle.textContent = `${phase} — Rejected`;
    dom.detailContent.innerHTML = `<p class="detail-placeholder">Architecture rejected with feedback. Workflow will loop back to DEFINE for revisions.</p>`;
  });
}

// Toggle diagram source visibility
function toggleSource(key) {
  const sourceEl = document.getElementById(`source-${key}`);
  if (sourceEl) {
    sourceEl.style.display = sourceEl.style.display === 'none' ? 'block' : 'none';
  }
}

// ─── Event Listeners ─────────────────────────────────────────────
function setupEventListeners() {
  // Start workflow → show requirement modal
  dom.btnStart.addEventListener('click', () => {
    document.getElementById('requirement-overlay').style.display = 'flex';
    document.getElementById('req-project-name').focus();
  });

  // Abort workflow
  dom.btnAbort.addEventListener('click', () => {
    if (confirm('Abort the running workflow? This will reset all state.')) {
      abortWorkflow();
    }
  });

  // Requirement modal controls
  document.getElementById('req-close').addEventListener('click', () => {
    document.getElementById('requirement-overlay').style.display = 'none';
  });
  document.getElementById('btn-cancel-req').addEventListener('click', () => {
    document.getElementById('requirement-overlay').style.display = 'none';
  });
  document.getElementById('btn-submit-req').addEventListener('click', async () => {
    const projectName = document.getElementById('req-project-name').value.trim();
    const spec = document.getElementById('req-spec').value.trim();
    const contextFolder = document.getElementById('req-context-folder').value.trim();
    if (!projectName) {
      alert('Please enter a project name');
      document.getElementById('req-project-name').focus();
      return;
    }
    state.workflow.projectName = projectName;
    document.getElementById('requirement-overlay').style.display = 'none';
    try {
      const res = await fetch(`${CONFIG.apiBase}/start`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ project_name: projectName, spec: spec, context_folder: contextFolder }),
      });
      const data = await res.json();
      console.log('[API] Workflow started:', data);
    } catch (err) {
      console.error('[API] Start workflow failed:', err);
    }
  });

  // Modal controls
  dom.modalClose.addEventListener('click', closeModal);
  dom.btnCancel.addEventListener('click', closeModal);

  // Phase click for details
  dom.pipeline.addEventListener('click', (e) => {
    const phaseEl = e.target.closest('.pipeline-phase');
    if (!phaseEl) return;

    const phaseName = phaseEl.dataset.phase;
    const phase = state.phases[phaseName];
    if (!phase) return;

    renderDetailForPhase(phaseName);
    // Also activate the corresponding tab if it exists
    dom.phaseTabs.querySelectorAll('.phase-tab').forEach(tab => {
      tab.classList.toggle('active', tab.dataset.phase === phaseName);
    });
  });

  // Phase keyboard activation (Enter/Space)
  dom.pipeline.addEventListener('keydown', (e) => {
    const phaseEl = e.target.closest('.pipeline-phase');
    if (!phaseEl) return;
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      phaseEl.click();
    }
  });

  // Modal focus trap
  const trapFocus = (e, container) => {
    const focusable = container.querySelectorAll('button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])');
    if (!focusable.length) return;
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (e.key === 'Tab') {
      if (e.shiftKey) {
        if (document.activeElement === first) {
          e.preventDefault();
          last.focus();
        }
      } else {
        if (document.activeElement === last) {
          e.preventDefault();
          first.focus();
        }
      }
    }
    if (e.key === 'Escape') {
      closeModal();
      const cancelBtn = document.getElementById('btn-cancel-req');
      if (cancelBtn) cancelBtn.click();
    }
  };

  dom.modalOverlay.addEventListener('keydown', (e) => trapFocus(e, dom.modalOverlay));
  document.getElementById('requirement-overlay').addEventListener('keydown', (e) => trapFocus(e, document.getElementById('requirement-overlay')));
}

// ─── Polling ─────────────────────────────────────────────────────
function startPolling() {
  setInterval(fetchStatus, CONFIG.pollingInterval);
}

// ─── Utilities ──────────────────────────────────────────────────
function escapeHtml(text) {
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

function formatTime(timestamp) {
  if (!timestamp) return '';
  const date = new Date(timestamp);
  return date.toLocaleTimeString('en-AU', { hour12: false });
}

function formatDuration(ms) {
  if (ms < 0) ms = 0;
  const seconds = Math.floor(ms / 1000);
  const mins = Math.floor(seconds / 60);
  const secs = seconds % 60;
  if (mins > 0) {
    return `${mins}m${secs.toString().padStart(2, '0')}s`;
  }
  return `${secs}s`;
}
