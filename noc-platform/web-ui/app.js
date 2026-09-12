/**
 * NOC Alert Platform - Real-Time Incident Console Controller
 * Pure Vanilla JavaScript ES6+
 */

(() => {
  'use strict';

  // --- Configuration & State ---
  const API_BASE = '/api/v1';

  const state = {
    refreshIntervalSec: 5,     // Declared by user (0 = Off)
    timeSpanMinutes: 15,       // Declared by user (0 = All Time)
    customSince: null,         // ISO string if custom
    customUntil: null,         // ISO string if custom
    severityFilter: '',
    statusFilter: 'ACTIVE',
    searchQuery: '',
    limit: 250,
    selectedAlert: null,
    isFetching: false,
    timerRef: null,
    countdownMsRemaining: 5000,
    lastRefreshTime: new Date()
  };

  // --- DOM Elements ---
  const el = {
    refreshSelect: document.getElementById('refresh-interval-select'),
    manualRefreshBtn: document.getElementById('manual-refresh-btn'),
    countdownSvgProgress: document.getElementById('countdown-progress'),
    countdownSeconds: document.getElementById('countdown-seconds'),
    timespanPills: document.getElementById('timespan-pills'),
    customTimeBtn: document.getElementById('custom-time-btn'),
    customModal: document.getElementById('custom-time-modal'),
    customSinceInput: document.getElementById('custom-since'),
    customUntilInput: document.getElementById('custom-until'),
    applyCustomTimeBtn: document.getElementById('apply-custom-time'),
    cancelCustomTimeBtn: document.getElementById('cancel-custom-time'),
    closeModalBtn: document.getElementById('close-modal-btn'),
    searchInput: document.getElementById('filter-search'),
    clearSearchBtn: document.getElementById('clear-search-btn'),
    severitySelect: document.getElementById('filter-severity'),
    statusSelect: document.getElementById('filter-status'),
    limitSelect: document.getElementById('filter-limit'),
    resetFiltersBtn: document.getElementById('reset-filters-btn'),
    visibleCountBadge: document.getElementById('visible-count-badge'),
    activeTimespanIndicator: document.getElementById('active-timespan-indicator'),
    lastRefreshedTime: document.getElementById('last-refreshed-time'),
    alertsTbody: document.getElementById('alerts-tbody'),
    syncStatus: document.getElementById('sync-status'),
    clusterPill: document.getElementById('cluster-health-pill'),

    // KPIs
    kpiCritical: document.getElementById('kpi-critical-val'),
    kpiActive: document.getElementById('kpi-active-val'),
    kpiFlapping: document.getElementById('kpi-flapping-val'),
    kpiTally: document.getElementById('kpi-tally-val'),

    // Drawer
    drawer: document.getElementById('alert-drawer'),
    drawerCloseBtn: document.getElementById('drawer-close-btn'),
    drawerSevBadge: document.getElementById('drawer-severity-badge'),
    drawerIdent: document.getElementById('drawer-identifier'),
    drawerNode: document.getElementById('drawer-node'),
    drawerAlertKey: document.getElementById('drawer-alert-key'),
    drawerStatus: document.getElementById('drawer-status'),
    drawerTally: document.getElementById('drawer-tally'),
    drawerFlapping: document.getElementById('drawer-flapping'),
    drawerFlapCount: document.getElementById('drawer-flap-count'),
    drawerFirstSeen: document.getElementById('drawer-first-seen'),
    drawerLastSeen: document.getElementById('drawer-last-seen'),
    drawerVersion: document.getElementById('drawer-version'),
    drawerSummary: document.getElementById('drawer-summary'),
    drawerCustomFields: document.getElementById('drawer-custom-fields'),
    actionAckBtn: document.getElementById('action-ack-btn'),
    actionResolveBtn: document.getElementById('action-resolve-btn'),
    actionReopenBtn: document.getElementById('action-reopen-btn'),
    actionDeleteBtn: document.getElementById('action-delete-btn'),

    // Toast
    toastContainer: document.getElementById('toast-container')
  };

  // --- Helper Functions ---

  function formatTimeAgo(isoString) {
    if (!isoString) return '-';
    const date = new Date(isoString);
    const now = new Date();
    const diffSec = Math.floor((now - date) / 1000);

    if (diffSec < 5) return 'just now';
    if (diffSec < 60) return `${diffSec}s ago`;
    const diffMin = Math.floor(diffSec / 60);
    if (diffMin < 60) return `${diffMin}m ago`;
    const diffHours = Math.floor(diffMin / 60);
    if (diffHours < 24) return `${diffHours}h ago`;
    const diffDays = Math.floor(diffHours / 24);
    return `${diffDays}d ago`;
  }

  function formatFullDate(isoString) {
    if (!isoString) return '-';
    try {
      const d = new Date(isoString);
      return d.toISOString().replace('T', ' ').substring(0, 19) + ' UTC';
    } catch {
      return isoString;
    }
  }

  function formatNumber(num) {
    if (num == null) return '0';
    return Number(num).toLocaleString();
  }

  function showToast(message, type = 'info') {
    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    toast.innerHTML = `<span>${message}</span>`;
    el.toastContainer.appendChild(toast);
    setTimeout(() => {
      toast.style.opacity = '0';
      setTimeout(() => toast.remove(), 300);
    }, 3500);
  }

  // --- API Fetchers ---

  async function fetchSummaryMetrics() {
    try {
      const params = new URLSearchParams();
      if (state.timeSpanMinutes > 0 && !state.customSince) {
        params.append('minutes', state.timeSpanMinutes);
      }
      const res = await fetch(`${API_BASE}/metrics/summary?${params.toString()}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();

      el.kpiCritical.textContent = formatNumber(data.critical_alerts);
      el.kpiActive.textContent = formatNumber(data.active_alerts);
      el.kpiFlapping.textContent = formatNumber(data.flapping_alerts);
      el.kpiTally.textContent = formatNumber(data.total_events_tally);

      el.syncStatus.textContent = 'ONLINE';
      el.syncStatus.style.color = 'var(--sev-clear)';
    } catch (err) {
      console.warn('Metrics summary fetch error:', err);
      el.syncStatus.textContent = 'DEGRADED';
      el.syncStatus.style.color = 'var(--sev-major)';
    }
  }

  async function fetchAlerts() {
    if (state.isFetching) return;
    state.isFetching = true;
    el.manualRefreshBtn.classList.add('spinning');

    try {
      const params = new URLSearchParams();
      if (state.statusFilter) params.append('status', state.statusFilter);
      if (state.severityFilter) params.append('severity', state.severityFilter);
      if (state.searchQuery) params.append('search', state.searchQuery);
      params.append('limit', state.limit);

      if (state.customSince) {
        params.append('since', new Date(state.customSince).toISOString());
        if (state.customUntil) {
          params.append('until', new Date(state.customUntil).toISOString());
        }
      } else if (state.timeSpanMinutes > 0) {
        params.append('minutes', state.timeSpanMinutes);
      }

      const res = await fetch(`${API_BASE}/alerts?${params.toString()}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const alerts = await res.json();

      renderAlertsTable(alerts);
      state.lastRefreshTime = new Date();
      el.lastRefreshedTime.textContent = `Updated: ${state.lastRefreshTime.toLocaleTimeString()}`;
    } catch (err) {
      console.error('Failed to fetch alerts:', err);
      showToast(`Error fetching alerts: ${err.message}`, 'error');
    } finally {
      state.isFetching = false;
      el.manualRefreshBtn.classList.remove('spinning');
    }
  }

  // --- Rendering Functions ---

  function getSeverityClass(sev) {
    switch ((sev || '').toUpperCase()) {
      case 'CRITICAL': return 'sev-badge-critical';
      case 'MAJOR': return 'sev-badge-major';
      case 'WARNING': return 'sev-badge-warning';
      case 'CLEAR': return 'sev-badge-clear';
      default: return 'sev-badge-info';
    }
  }

  function getStatusClass(st) {
    switch ((st || '').toUpperCase()) {
      case 'OPEN': return 'status-open';
      case 'ACKNOWLEDGED': return 'status-acknowledged';
      case 'RESOLVED': return 'status-resolved';
      default: return '';
    }
  }

  function renderAlertsTable(alerts) {
    el.visibleCountBadge.textContent = `Showing ${alerts.length} alerts`;

    if (!alerts || alerts.length === 0) {
      el.alertsTbody.innerHTML = `
        <tr class="table-loading-row">
          <td colspan="8">
            <div class="empty-state">
              <svg viewBox="0 0 24 24" width="36" height="36" stroke="currentColor" stroke-width="1.5" fill="none">
                <circle cx="12" cy="12" r="10"></circle>
                <path d="M8 12h8"></path>
              </svg>
              <span>No alerts matching selected time window and filter criteria.</span>
            </div>
          </td>
        </tr>
      `;
      return;
    }

    const fragment = document.createDocumentFragment();

    alerts.forEach(alert => {
      const tr = document.createElement('tr');
      tr.dataset.identifier = alert.identifier;

      const sevClass = getSeverityClass(alert.severity);
      const statusClass = getStatusClass(alert.status);
      const isFlapping = alert.is_flapping;
      const tallyVal = alert.tally || 1;
      const isHighTally = tallyVal > 5;

      tr.innerHTML = `
        <td>
          <span class="badge-severity ${sevClass}">
            <span class="badge-dot"></span>
            ${escapeHtml(alert.severity)}
          </span>
        </td>
        <td>
          <span class="badge-status ${statusClass}">
            ${escapeHtml(alert.status)}
          </span>
        </td>
        <td>
          <div class="ident-cell">
            <span class="ident-text" title="${escapeHtml(alert.identifier)}">${escapeHtml(alert.identifier)}</span>
            <span class="node-text">${escapeHtml(alert.node)}</span>
          </div>
        </td>
        <td>
          <span class="mono" style="color: #93c5fd; font-size: 12px;">${escapeHtml(alert.alert_key)}</span>
        </td>
        <td>
          <div class="summary-cell">
            <span class="summary-text" title="${escapeHtml(alert.summary || '')}">${escapeHtml(alert.summary || '-')}</span>
            ${isFlapping ? '<span class="flapping-pill" title="Flapping detected: State jitter dampening active">⚡ Flapping</span>' : ''}
          </div>
        </td>
        <td style="text-align: center;">
          <span class="tally-badge ${isHighTally ? 'high-tally' : ''}" title="${tallyVal} raw incoming events deduplicated into this single record">
            ${formatNumber(tallyVal)}x
          </span>
        </td>
        <td>
          <div class="time-cell">
            <span class="time-ago">${formatTimeAgo(alert.last_occurrence)}</span>
            <span class="time-full">${formatFullDate(alert.last_occurrence)}</span>
          </div>
        </td>
        <td style="text-align: right;">
          <button class="btn btn-secondary btn-sm inspect-btn" data-id="${escapeHtml(alert.identifier)}">Inspect</button>
        </td>
      `;

      tr.addEventListener('click', (e) => {
        openAlertDrawer(alert);
      });

      fragment.appendChild(tr);
    });

    el.alertsTbody.innerHTML = '';
    el.alertsTbody.appendChild(fragment);
  }

  function escapeHtml(text) {
    if (!text) return '';
    return String(text)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  // --- Inspector Drawer ---

  function openAlertDrawer(alert) {
    state.selectedAlert = alert;
    el.drawerIdent.textContent = alert.identifier;
    el.drawerNode.textContent = alert.node;
    el.drawerAlertKey.textContent = alert.alert_key;
    el.drawerStatus.textContent = alert.status;
    el.drawerTally.textContent = `${alert.tally || 1} deduplicated events`;
    el.drawerFlapping.textContent = alert.is_flapping ? 'YES (Active)' : 'No';
    el.drawerFlapCount.textContent = alert.flap_count || 0;
    el.drawerFirstSeen.textContent = formatFullDate(alert.first_occurrence);
    el.drawerLastSeen.textContent = formatFullDate(alert.last_occurrence);
    el.drawerVersion.textContent = `v${alert.version}`;
    el.drawerSummary.textContent = alert.summary || 'No summary text provided.';

    // Severity badge styling
    el.drawerSevBadge.className = `badge-severity ${getSeverityClass(alert.severity)}`;
    el.drawerSevBadge.innerHTML = `<span class="badge-dot"></span>${escapeHtml(alert.severity)}`;

    // JSON Payload
    try {
      const custom = alert.custom_fields || {};
      el.drawerCustomFields.textContent = JSON.stringify(custom, null, 2);
    } catch {
      el.drawerCustomFields.textContent = '{}';
    }

    el.drawer.classList.remove('hidden');
  }

  function closeAlertDrawer() {
    el.drawer.classList.add('hidden');
    state.selectedAlert = null;
  }

  async function patchSelectedAlert(newStatus) {
    if (!state.selectedAlert) return;
    const id = state.selectedAlert.identifier;
    try {
      const res = await fetch(`${API_BASE}/alerts/${encodeURIComponent(id)}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status: newStatus })
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const updated = await res.json();
      showToast(`Alert ${id} marked as ${newStatus}`, 'success');
      openAlertDrawer(updated);
      fetchAlerts();
      fetchSummaryMetrics();
    } catch (err) {
      showToast(`Action failed: ${err.message}`, 'error');
    }
  }

  async function deleteSelectedAlert() {
    if (!state.selectedAlert) return;
    const id = state.selectedAlert.identifier;
    if (!confirm(`Are you sure you want to soft-delete (PURGE) alert ${id}?`)) return;

    try {
      const res = await fetch(`${API_BASE}/alerts/${encodeURIComponent(id)}`, {
        method: 'DELETE'
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      showToast(`Alert ${id} purged`, 'success');
      closeAlertDrawer();
      fetchAlerts();
      fetchSummaryMetrics();
    } catch (err) {
      showToast(`Purge failed: ${err.message}`, 'error');
    }
  }

  // --- Auto-Refresh Countdown Engine ---

  function restartCountdownTimer() {
    if (state.timerRef) {
      clearInterval(state.timerRef);
      state.timerRef = null;
    }

    if (state.refreshIntervalSec === 0) {
      el.countdownSeconds.textContent = 'Off';
      el.countdownSvgProgress.setAttribute('stroke-dasharray', '0, 100');
      return;
    }

    state.countdownMsRemaining = state.refreshIntervalSec * 1000;
    const totalMs = state.refreshIntervalSec * 1000;

    state.timerRef = setInterval(() => {
      state.countdownMsRemaining -= 100;

      if (state.countdownMsRemaining <= 0) {
        state.countdownMsRemaining = totalMs;
        triggerFullRefresh();
      }

      // Update circular countdown progress ring
      const progressPercent = Math.max(0, (state.countdownMsRemaining / totalMs) * 100);
      el.countdownSvgProgress.setAttribute('stroke-dasharray', `${progressPercent.toFixed(1)}, 100`);

      const remainingSec = Math.ceil(state.countdownMsRemaining / 1000);
      el.countdownSeconds.textContent = `${remainingSec}s`;
    }, 100);
  }

  function triggerFullRefresh() {
    fetchAlerts();
    fetchSummaryMetrics();
  }

  // --- Event Listeners Setup ---

  function setupEventListeners() {
    // Refresh interval declared by the user
    el.refreshSelect.addEventListener('change', (e) => {
      state.refreshIntervalSec = parseInt(e.target.value, 10);
      restartCountdownTimer();
      showToast(`Auto-refresh interval set to: ${e.target.options[e.target.selectedIndex].text}`, 'info');
    });

    // Manual Refresh Button
    el.manualRefreshBtn.addEventListener('click', () => {
      triggerFullRefresh();
      state.countdownMsRemaining = state.refreshIntervalSec * 1000;
    });

    // Keyboard shortcut 'R' for refresh
    window.addEventListener('keydown', (e) => {
      if (e.key.toLowerCase() === 'r' && !['INPUT', 'SELECT', 'TEXTAREA'].includes(document.activeElement.tagName)) {
        triggerFullRefresh();
      }
      if (e.key === 'Escape') {
        closeAlertDrawer();
        el.customModal.classList.add('hidden');
      }
    });

    // Time-Span preset pills declared by the user
    el.timespanPills.addEventListener('click', (e) => {
      const btn = e.target.closest('.pill-btn');
      if (!btn || btn.id === 'custom-time-btn') return;

      document.querySelectorAll('#timespan-pills .pill-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');

      state.timeSpanMinutes = parseInt(btn.dataset.minutes, 10);
      state.customSince = null;
      state.customUntil = null;

      const label = btn.textContent.trim();
      el.activeTimespanIndicator.textContent = `Window: ${label}`;

      triggerFullRefresh();
      showToast(`Time window filtered to: ${label}`, 'info');
    });

    // Custom Time-Span Modal
    el.customTimeBtn.addEventListener('click', () => {
      el.customModal.classList.remove('hidden');
    });

    el.closeModalBtn.addEventListener('click', () => el.customModal.classList.add('hidden'));
    el.cancelCustomTimeBtn.addEventListener('click', () => el.customModal.classList.add('hidden'));

    el.applyCustomTimeBtn.addEventListener('click', () => {
      const sinceVal = el.customSinceInput.value;
      const untilVal = el.customUntilInput.value;

      if (!sinceVal) {
        alert('Please specify at least a Start Date & Time.');
        return;
      }

      state.customSince = sinceVal;
      state.customUntil = untilVal || null;
      state.timeSpanMinutes = 0;

      document.querySelectorAll('#timespan-pills .pill-btn').forEach(b => b.classList.remove('active'));
      el.customTimeBtn.classList.add('active');

      const startText = new Date(sinceVal).toLocaleTimeString();
      const endText = untilVal ? new Date(untilVal).toLocaleTimeString() : 'Now';
      el.activeTimespanIndicator.textContent = `Custom: ${startText} → ${endText}`;

      el.customModal.classList.add('hidden');
      triggerFullRefresh();
      showToast(`Applied custom date range`, 'info');
    });

    // Search filter with debounce
    let searchDebounce = null;
    el.searchInput.addEventListener('input', (e) => {
      const val = e.target.value.trim();
      el.clearSearchBtn.classList.toggle('hidden', val.length === 0);

      clearTimeout(searchDebounce);
      searchDebounce = setTimeout(() => {
        state.searchQuery = val;
        fetchAlerts();
      }, 300);
    });

    el.clearSearchBtn.addEventListener('click', () => {
      el.searchInput.value = '';
      state.searchQuery = '';
      el.clearSearchBtn.classList.add('hidden');
      fetchAlerts();
    });

    // Severity & Status dropdowns
    el.severitySelect.addEventListener('change', (e) => {
      state.severityFilter = e.target.value;
      fetchAlerts();
    });

    el.statusSelect.addEventListener('change', (e) => {
      state.statusFilter = e.target.value;
      fetchAlerts();
    });

    el.limitSelect.addEventListener('change', (e) => {
      state.limit = parseInt(e.target.value, 10);
      fetchAlerts();
    });

    // Reset filters
    el.resetFiltersBtn.addEventListener('click', () => {
      state.severityFilter = '';
      state.statusFilter = 'ACTIVE';
      state.searchQuery = '';
      state.timeSpanMinutes = 15;
      state.customSince = null;
      state.customUntil = null;

      el.severitySelect.value = '';
      el.statusSelect.value = 'ACTIVE';
      el.searchInput.value = '';
      el.clearSearchBtn.classList.add('hidden');

      document.querySelectorAll('#timespan-pills .pill-btn').forEach(b => b.classList.remove('active'));
      const defaultPill = document.querySelector('#timespan-pills [data-minutes="15"]');
      if (defaultPill) defaultPill.classList.add('active');
      el.activeTimespanIndicator.textContent = 'Window: Last 15m';

      triggerFullRefresh();
      showToast('Filters reset to default', 'info');
    });

    // Drawer actions
    el.drawerCloseBtn.addEventListener('click', closeAlertDrawer);
    el.actionAckBtn.addEventListener('click', () => patchSelectedAlert('ACKNOWLEDGED'));
    el.actionResolveBtn.addEventListener('click', () => patchSelectedAlert('RESOLVED'));
    el.actionReopenBtn.addEventListener('click', () => patchSelectedAlert('OPEN'));
    el.actionDeleteBtn.addEventListener('click', deleteSelectedAlert);

    // Close drawer when clicking outside panel
    el.drawer.addEventListener('click', (e) => {
      if (e.target === el.drawer) closeAlertDrawer();
    });
  }

  // --- Initialize Application ---
  function init() {
    setupEventListeners();
    triggerFullRefresh();
    restartCountdownTimer();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
