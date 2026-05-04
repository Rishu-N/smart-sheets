// SmartSheet — Grid module (Feature Enhancement: all 10 new features)

// ─── State ──────────────────────────────────────────────────
let hot = null;
let currentSheet = null;
let sheetData = null;
let cellMeta = {};
let columnAliases = {};
let rowAliases = {};
let isSyncing = false;

// WebSocket
let ws = null;
let reconnectAttempts = 0;
const MAX_RECONNECT = 5;
let sessionToken = null;
let currentUserId = null;

// Presence
let connectedUsers = [];
let cellLocks = {};

// Search
let searchPanelVisible = false;
let searchResults = [];
let searchIndex = -1;
let searchQuery = '';
let replaceMode = false;

// ─── API Functions ──────────────────────────────────────────

async function fetchSheets() {
    const res = await fetch('/api/sheets');
    if (!res.ok) throw new Error('Failed to fetch sheets');
    return res.json();
}

async function fetchSheet(name) {
    const res = await fetch(`/api/sheet/${encodeURIComponent(name)}`);
    if (!res.ok) throw new Error(`Failed to fetch sheet: ${name}`);
    return res.json();
}

async function patchCell(sheetName, row, col, value) {
    const res = await fetch(`/api/sheet/${encodeURIComponent(sheetName)}/cell`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ row, col, value: String(value ?? '') }),
    });
    if (!res.ok) { showErrorToast('Failed to save cell'); return null; }
    return res.json();
}

async function apiInsertRows(sheetName, index, count) {
    const res = await fetch(`/api/sheet/${encodeURIComponent(sheetName)}/rows`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ index, count }),
    });
    return res.json();
}

async function apiDeleteRows(sheetName, indices) {
    const res = await fetch(`/api/sheet/${encodeURIComponent(sheetName)}/rows`, {
        method: 'DELETE',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ indices }),
    });
    return res.json();
}

async function apiAddColumn(sheetName) {
    const res = await fetch(`/api/sheet/${encodeURIComponent(sheetName)}/columns`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ count: 1 }),
    });
    return res.json();
}

async function apiUndo(sheetName) {
    const res = await fetch(`/api/sheet/${encodeURIComponent(sheetName)}/undo`, { method: 'POST' });
    return res.json();
}

async function apiRedo(sheetName) {
    const res = await fetch(`/api/sheet/${encodeURIComponent(sheetName)}/redo`, { method: 'POST' });
    return res.json();
}

async function apiCreateSheet(name) {
    const res = await fetch('/api/sheets/create', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name }),
    });
    if (!res.ok) { const err = await res.json(); throw new Error(err.detail || 'Failed to create sheet'); }
    return res.json();
}

async function apiRenameSheet(oldName, newName) {
    const res = await fetch(`/api/sheet/${encodeURIComponent(oldName)}/rename`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ new_name: newName }),
    });
    if (!res.ok) { const err = await res.json(); throw new Error(err.detail || 'Rename failed'); }
    return res.json();
}

async function apiUpdateAlias(sheetName, axis, index, label) {
    const res = await fetch(`/api/sheet/${encodeURIComponent(sheetName)}/alias`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ axis, index, label }),
    });
    return res.json();
}

async function fetchMeta(name) {
    const res = await fetch(`/api/sheet/${encodeURIComponent(name)}/meta`);
    if (!res.ok) return { cells: {} };
    return res.json();
}

async function apiUpdateFormat(sheetName, row, col, fmt) {
    const res = await fetch(`/api/sheet/${encodeURIComponent(sheetName)}/format`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ row, col, format: fmt }),
    });
    return res.json();
}

async function fetchShareInfo() {
    const res = await fetch('/api/share-info');
    if (!res.ok) throw new Error('Could not load share info');
    return res.json();
}

async function fetchSettings() {
    const res = await fetch('/api/settings');
    if (!res.ok) throw new Error('Could not load settings');
    return res.json();
}

async function patchSettings(updates) {
    const res = await fetch('/api/settings', {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(updates),
    });
    if (!res.ok) { const err = await res.json(); throw new Error(err.detail || 'Save failed'); }
    return res.json();
}

// ─── Utilities ──────────────────────────────────────────────

function colToLetter(col) {
    let letter = '';
    let n = col;
    while (n >= 0) {
        letter = String.fromCharCode(65 + (n % 26)) + letter;
        n = Math.floor(n / 26) - 1;
    }
    return letter;
}

function letterToCol(letters) {
    let col = 0;
    for (const ch of letters.toUpperCase()) {
        col = col * 26 + (ch.charCodeAt(0) - 64);
    }
    return col - 1;
}

function getCookie(name) {
    const match = document.cookie.match(new RegExp('(^| )' + name + '=([^;]+)'));
    return match ? match[2] : null;
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = String(text);
    return div.innerHTML;
}

function escapeRegex(str) {
    return str.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

// ─── Toast Notifications ────────────────────────────────────

function showToast(message, type = 'info', duration = 3000) {
    const container = getToastContainer();
    const toast = document.createElement('div');
    toast.className = `mini-toast mini-toast-${type}`;
    toast.textContent = message;
    container.appendChild(toast);
    setTimeout(() => { toast.classList.add('fade-out'); }, duration - 400);
    setTimeout(() => toast.remove(), duration);
}

function showErrorToast(msg) { showToast(msg, 'error', 4000); }
function showSuccessToast(msg) { showToast(msg, 'success', 2500); }

function getToastContainer() {
    let c = document.getElementById('toast-container');
    if (!c) {
        c = document.createElement('div');
        c.id = 'toast-container';
        document.body.appendChild(c);
    }
    return c;
}

// ─── Loading Overlay ────────────────────────────────────────

function showLoadingOverlay(msg = 'Loading...') {
    let overlay = document.getElementById('loading-overlay');
    if (!overlay) {
        overlay = document.createElement('div');
        overlay.id = 'loading-overlay';
        document.body.appendChild(overlay);
    }
    overlay.textContent = msg;
    overlay.style.display = 'flex';
}

function hideLoadingOverlay() {
    const overlay = document.getElementById('loading-overlay');
    if (overlay) overlay.style.display = 'none';
}

// ─── Theme Toggle ───────────────────────────────────────────

function initTheme() {
    const saved = localStorage.getItem('theme') || 'dark';
    applyTheme(saved);
}

function applyTheme(theme) {
    document.documentElement.setAttribute('data-theme', theme);
    const btn = document.getElementById('theme-btn');
    if (btn) btn.textContent = theme === 'light' ? '🌙' : '☀';
    localStorage.setItem('theme', theme);
}

function toggleTheme() {
    const current = document.documentElement.getAttribute('data-theme') || 'dark';
    applyTheme(current === 'dark' ? 'light' : 'dark');
}

// ─── Formula Bar (editable cell-ref input) ─────────────────

function setupFormulaBar() {
    const cellRefInput = document.getElementById('cell-ref');
    const formulaInput = document.getElementById('formula-input');

    // Cell-ref: jump to cell on Enter
    cellRefInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
            e.preventDefault();
            const val = cellRefInput.value.trim().toUpperCase();
            const m = val.match(/^([A-Z]+)(\d+)$/);
            if (m && hot) {
                const col = letterToCol(m[1]);
                const row = parseInt(m[2], 10) - 1;
                if (row >= 0 && col >= 0 && row < hot.countRows() && col < hot.countCols()) {
                    hot.selectCell(row, col);
                    hot.scrollViewportTo(row, col);
                } else {
                    showErrorToast('Cell reference out of range');
                }
            } else {
                showErrorToast('Invalid cell reference (e.g. B5)');
            }
            hot?.listen();
        } else if (e.key === 'Escape') {
            const selected = hot?.getSelected();
            if (selected) {
                const [row, col] = selected[0];
                cellRefInput.value = `${colToLetter(col)}${row + 1}`;
            }
            hot?.listen();
        }
    });

    cellRefInput.addEventListener('focus', () => { hot?.unlisten(); });

    // Formula input
    formulaInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
            e.preventDefault();
            const selected = hot?.getSelected();
            if (!selected || selected.length === 0) return;
            const [row, col] = selected[0];
            const value = formulaInput.value;
            hot.setDataAtCell(row, col, value, 'formulaBar');
            hot.selectCell(row, col);
            if (sheetData && sheetData.rows[row]) sheetData.rows[row][col] = value;
        } else if (e.key === 'Escape') {
            const selected = hot?.getSelected();
            if (selected && selected.length > 0) {
                const [row, col] = selected[0];
                formulaInput.value = getRawValue(row, col);
            }
            hot?.listen();
        }
    });

    formulaInput.addEventListener('focus', () => { hot?.unlisten(); });
}

function getRawValue(row, col) {
    if (sheetData && sheetData.rows[row] !== undefined) return sheetData.rows[row][col] ?? '';
    return '';
}

function updateFormulaBar(row, col) {
    const cellRefInput = document.getElementById('cell-ref');
    if (cellRefInput) cellRefInput.value = `${colToLetter(col)}${row + 1}`;
    const formulaInput = document.getElementById('formula-input');
    if (formulaInput) formulaInput.value = getRawValue(row, col);
}

// ─── Share Modal ────────────────────────────────────────────

function setupShareModal() {
    document.getElementById('share-btn').addEventListener('click', openShareModal);
    document.getElementById('share-modal-close').addEventListener('click', closeShareModal);
    document.getElementById('share-modal').addEventListener('click', (e) => {
        if (e.target.id === 'share-modal') closeShareModal();
    });
}

async function openShareModal() {
    document.getElementById('share-modal').style.display = 'flex';
    const body = document.getElementById('share-modal-body');
    body.innerHTML = '<p class="modal-loading">Generating QR code...</p>';
    try {
        const info = await fetchShareInfo();
        // Use a data URL so the XML-namespaced SVG renders correctly in all browsers
        const svgDataUrl = 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(info.qr_svg);
        body.innerHTML = `
            <div class="share-url-row">
                <code id="share-url-text">${escapeHtml(info.lan_url)}</code>
                <button id="share-copy-btn" class="btn-secondary">Copy URL</button>
            </div>
            <div class="share-qr"><img src="${svgDataUrl}" alt="QR Code" style="width:200px;height:200px;"></div>
            <p class="share-hint">Guests on your local network can scan this QR code or open the URL above.</p>
        `;
        document.getElementById('share-copy-btn').addEventListener('click', () => {
            navigator.clipboard.writeText(info.lan_url).then(() => showSuccessToast('URL copied!'));
        });
    } catch (err) {
        body.innerHTML = `<p class="modal-error">Failed to load share info: ${escapeHtml(err.message)}</p>`;
    }
}

function closeShareModal() {
    document.getElementById('share-modal').style.display = 'none';
}

// ─── Settings Modal ─────────────────────────────────────────

function setupSettingsModal() {
    document.getElementById('settings-btn').addEventListener('click', openSettingsModal);
    document.getElementById('settings-modal-close').addEventListener('click', closeSettingsModal);
    document.getElementById('settings-cancel-btn').addEventListener('click', closeSettingsModal);
    document.getElementById('settings-modal').addEventListener('click', (e) => {
        if (e.target.id === 'settings-modal') closeSettingsModal();
    });
    document.getElementById('settings-save-btn').addEventListener('click', saveSettings);
}

async function openSettingsModal() {
    document.getElementById('settings-modal').style.display = 'flex';
    try {
        const cfg = await fetchSettings();
        document.getElementById('cfg-api-key').value = cfg.openai_api_key || '';
        document.getElementById('cfg-base-url').value = cfg.base_url || '';
        document.getElementById('cfg-model').value = cfg.ai_model || 'gpt-5.0';
        document.getElementById('cfg-ctx-rows').value = cfg.max_context_rows || 200;
        document.getElementById('cfg-undo').value = cfg.undo_depth || 50;
        document.getElementById('cfg-desktop-notif').checked = !!cfg.desktop_notifications;
        document.getElementById('cfg-open-browser').checked = !!cfg.open_browser;
        document.getElementById('cfg-require-auth').checked = !!cfg.require_guest_auth;
    } catch (err) {
        showErrorToast('Failed to load settings');
    }
}

function closeSettingsModal() {
    document.getElementById('settings-modal').style.display = 'none';
}

async function saveSettings() {
    const updates = {
        openai_api_key: document.getElementById('cfg-api-key').value.trim(),
        base_url: document.getElementById('cfg-base-url').value.trim(),
        ai_model: document.getElementById('cfg-model').value,
        max_context_rows: parseInt(document.getElementById('cfg-ctx-rows').value, 10),
        undo_depth: parseInt(document.getElementById('cfg-undo').value, 10),
        desktop_notifications: document.getElementById('cfg-desktop-notif').checked,
        open_browser: document.getElementById('cfg-open-browser').checked,
        require_guest_auth: document.getElementById('cfg-require-auth').checked,
    };
    try {
        await patchSettings(updates);
        showSuccessToast('Settings saved');
        closeSettingsModal();
    } catch (err) {
        showErrorToast(`Save failed: ${err.message}`);
    }
}

// ─── Undo / Redo ────────────────────────────────────────────

async function handleUndo() {
    if (!currentSheet) return;
    const result = await apiUndo(currentSheet);
    if (result && result.changes) applyChangesToGrid(result);
}

async function handleRedo() {
    if (!currentSheet) return;
    const result = await apiRedo(currentSheet);
    if (result && result.changes) applyChangesToGrid(result);
}

function applyChangesToGrid(result) {
    if (!result.changes || !hot) return;
    isSyncing = true;
    for (const change of result.changes) {
        if (change.row !== undefined && change.col !== undefined) {
            hot.setDataAtCell(change.row, change.col, change.evaluated ?? change.value, 'remote');
            if (sheetData && sheetData.rows[change.row]) sheetData.rows[change.row][change.col] = change.value;
        } else if (change.action) {
            isSyncing = false;
            loadSheet(currentSheet);
            return;
        }
    }
    isSyncing = false;
    hot.render();
}

// ─── WebSocket ──────────────────────────────────────────────

function connectWebSocket(token) {
    if (ws && ws.readyState === WebSocket.OPEN) return;

    sessionToken = token || getCookie('session_token') || 'host';
    const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
    const url = `${proto}//${location.host}/ws/${sessionToken}`;

    ws = new WebSocket(url);

    ws.onopen = () => { reconnectAttempts = 0; updateConnectionStatus(true); };

    ws.onmessage = (event) => {
        try {
            const msg = JSON.parse(event.data);
            handleWSMessage(msg.event, msg.data);
        } catch (e) { console.error('WS message parse error:', e); }
    };

    ws.onclose = (event) => {
        updateConnectionStatus(false);
        if (event.code !== 4001 && reconnectAttempts < MAX_RECONNECT) {
            const delay = Math.min(1000 * Math.pow(2, reconnectAttempts), 16000);
            reconnectAttempts++;
            setTimeout(() => connectWebSocket(sessionToken), delay);
        }
    };

    ws.onerror = () => {};
}

function sendWS(event, data) {
    if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ event, data }));
}

function handleWSMessage(event, data) {
    switch (event) {
        case 'cell_update':    handleRemoteCellUpdate(data); break;
        case 'cell_lock':      showCellLock(data); break;
        case 'cell_unlock':    removeCellLock(data); break;
        case 'user_join':      addUserToPresence(data); break;
        case 'user_leave':     removeUserFromPresence(data); break;
        case 'presence_list':  initPresence(data.users); break;
        case 'sheet_reload':    loadSheet(data.sheet || currentSheet); break;
        case 'sheet_renamed':   handleSheetRenamed(data); break;
        case 'sheet_deleted':   handleSheetDeleted(data); break;
        case 'sheet_protected': renderSheetTabs(); break;
        case 'otp_request':     showHostOTPToast(data); break;
    }
}

function handleRemoteCellUpdate(data) {
    if (!hot || data.sheet !== currentSheet) return;
    isSyncing = true;
    hot.setDataAtCell(data.row, data.col, data.evaluated ?? data.value, 'remote');
    if (sheetData && sheetData.rows[data.row]) sheetData.rows[data.row][data.col] = data.value;
    isSyncing = false;
}

function handleSheetRenamed(data) {
    if (currentSheet === data.old_name) {
        currentSheet = data.new_name;
    }
    renderSheetTabs();
    populateSheetSelector();
}

async function handleSheetDeleted(data) {
    // If we're currently viewing the deleted sheet, switch to the first remaining one
    if (currentSheet === data.name) {
        const sheets = await fetchSheets();
        if (sheets.length > 0) {
            currentSheet = sheets[0].name;
            await loadSheet(currentSheet);
        }
    }
    await renderSheetTabs();
    await populateSheetSelector();
}

// ─── Cell Locking ───────────────────────────────────────────

function onCellEditStart(row, col) {
    if (currentSheet) sendWS('cell_lock', { sheet: currentSheet, row, col });
}

function onCellEditEnd(row, col) {
    if (currentSheet) sendWS('cell_unlock', { sheet: currentSheet, row, col });
}

function showCellLock(data) {
    if (data.sheet !== currentSheet || !hot) return;
    const key = `${data.row}_${data.col}`;
    cellLocks[key] = { user_id: data.user_id, color: data.color, display_name: data.display_name };
    hot.setCellMeta(data.row, data.col, 'readOnly', true);
    hot.setCellMeta(data.row, data.col, 'className', 'cell-locked');
    hot.render();
    updateLockStyle(data.row, data.col, data.color);
}

function removeCellLock(data) {
    if (data.sheet !== currentSheet || !hot) return;
    const key = `${data.row}_${data.col}`;
    delete cellLocks[key];
    hot.setCellMeta(data.row, data.col, 'readOnly', false);
    hot.setCellMeta(data.row, data.col, 'className', '');
    hot.render();
}

function updateLockStyle(row, col, color) {
    const td = hot.getCell(row, col);
    if (td) {
        td.style.outline = `2px solid ${color}`;
        td.style.outlineOffset = '-2px';
        td.title = cellLocks[`${row}_${col}`]?.display_name || '';
    }
}

// ─── Presence Bar ───────────────────────────────────────────

function initPresence(users) {
    connectedUsers = users || [];
    renderPresenceBar();
}

function addUserToPresence(data) {
    if (!connectedUsers.find(u => u.user_id === data.user_id)) connectedUsers.push(data);
    renderPresenceBar();
}

function removeUserFromPresence(data) {
    connectedUsers = connectedUsers.filter(u => u.user_id !== data.user_id);
    renderPresenceBar();
}

function renderPresenceBar() {
    const bar = document.getElementById('presence-bar');
    if (!bar) return;
    bar.innerHTML = connectedUsers.map(u => {
        const initials = u.display_name.split(' ').map(w => w[0]).join('').toUpperCase().slice(0, 2);
        return `<span class="presence-avatar" style="background:${u.color}" title="${escapeHtml(u.display_name)}">${initials}</span>`;
    }).join('');
}

// ─── Host OTP Toast ─────────────────────────────────────────

function showHostOTPToast(data) {
    const existing = document.getElementById('otp-toast');
    if (existing) existing.remove();
    const toast = document.createElement('div');
    toast.id = 'otp-toast';
    toast.className = 'toast toast-otp';
    toast.innerHTML = `
        <div class="toast-header">
            <strong>Join Request</strong>
            <button class="toast-close" onclick="this.parentElement.parentElement.remove()">&times;</button>
        </div>
        <div class="toast-body">
            <p><strong>${escapeHtml(data.name)}</strong> wants to access the sheet.</p>
            <p class="otp-code">${escapeHtml(data.otp)}</p>
            <p class="otp-hint">Share this code. Expires in <span id="toast-countdown">${Math.floor(data.expires_in / 60)}:00</span></p>
        </div>`;
    document.body.appendChild(toast);
    let remaining = data.expires_in;
    const interval = setInterval(() => {
        remaining--;
        const el = document.getElementById('toast-countdown');
        if (el) { const m = Math.floor(remaining / 60); const s = remaining % 60; el.textContent = `${m}:${s.toString().padStart(2, '0')}`; }
        if (remaining <= 0) { clearInterval(interval); toast.remove(); }
    }, 1000);
    setTimeout(() => { clearInterval(interval); toast.remove(); }, data.expires_in * 1000);
}

// ─── Connection Status ──────────────────────────────────────

function updateConnectionStatus(connected) {
    const el = document.getElementById('status-info');
    if (el) {
        if (connected) el.innerHTML = '<span class="status-dot connected"></span> Connected';
        else el.innerHTML = '<span class="status-dot disconnected"></span> Reconnecting...';
    }
}

// ─── Enhanced Search Panel ──────────────────────────────────

function setupSearchPanel() {
    document.getElementById('search-input').addEventListener('input', (e) => {
        searchQuery = e.target.value;
        performSearch();
    });

    document.getElementById('search-input').addEventListener('keydown', (e) => {
        if (e.key === 'Enter') { e.shiftKey ? navigateSearch(-1) : navigateSearch(1); }
        else if (e.key === 'Escape') { closeSearchPanel(); }
    });

    document.getElementById('search-close-btn').addEventListener('click', closeSearchPanel);

    ['search-case', 'search-whole', 'search-regex', 'search-all-sheets'].forEach(id => {
        document.getElementById(id).addEventListener('change', performSearch);
    });

    document.getElementById('search-replace-one-btn').addEventListener('click', replaceOne);
    document.getElementById('search-replace-all-btn').addEventListener('click', replaceAll);
}

function openSearchPanel(withReplace = false) {
    const panel = document.getElementById('search-panel');
    panel.style.display = 'flex';
    document.getElementById('search-replace-row').style.display = withReplace ? 'flex' : 'none';
    searchPanelVisible = true;
    replaceMode = withReplace;

    // Add panel to grid-wrapper
    const wrapper = document.getElementById('grid-wrapper');
    if (wrapper && !wrapper.contains(panel)) {
        wrapper.insertBefore(panel, wrapper.firstChild);
    }

    document.getElementById('search-input').focus();
    if (searchQuery) performSearch();
}

function closeSearchPanel() {
    document.getElementById('search-panel').style.display = 'none';
    searchPanelVisible = false;
    searchResults = [];
    searchIndex = -1;
    document.getElementById('search-count').textContent = '';
    document.getElementById('search-results').innerHTML = '';
    if (hot) hot.render();
}

async function performSearch() {
    searchResults = [];
    searchIndex = -1;
    const query = document.getElementById('search-input').value;
    if (!query) {
        document.getElementById('search-count').textContent = '';
        document.getElementById('search-results').innerHTML = '';
        if (hot) hot.render();
        return;
    }

    const caseSensitive = document.getElementById('search-case').checked;
    const wholeCell = document.getElementById('search-whole').checked;
    const useRegex = document.getElementById('search-regex').checked;
    const allSheets = document.getElementById('search-all-sheets').checked;

    function matchValue(cellVal) {
        let s = String(cellVal ?? '');
        let q = query;
        if (useRegex) {
            try {
                const flags = caseSensitive ? '' : 'i';
                const re = new RegExp(wholeCell ? `^${q}$` : q, flags);
                return re.test(s);
            } catch { return false; }
        }
        if (!caseSensitive) { s = s.toLowerCase(); q = q.toLowerCase(); }
        return wholeCell ? s === q : s.includes(q);
    }

    if (allSheets) {
        const sheets = await fetchSheets();
        for (const sheet of sheets) {
            const sd = await fetchSheet(sheet.name);
            for (let r = 0; r < sd.rows.length; r++) {
                for (let c = 0; c < sd.rows[r].length; c++) {
                    if (matchValue(sd.rows[r][c])) {
                        searchResults.push({ sheet: sheet.name, row: r, col: c, value: sd.rows[r][c], header: sd.headers[c] });
                    }
                }
            }
        }
    } else if (hot) {
        const data = hot.getData();
        for (let r = 0; r < data.length; r++) {
            for (let c = 0; c < data[r].length; c++) {
                if (matchValue(data[r][c])) {
                    searchResults.push({ sheet: currentSheet, row: r, col: c, value: data[r][c], header: sheetData?.headers?.[c] || '' });
                }
            }
        }
    }

    const countEl = document.getElementById('search-count');
    countEl.textContent = searchResults.length > 0 ? `${searchResults.length} result${searchResults.length !== 1 ? 's' : ''}` : 'No results';

    renderSearchResults();

    if (searchResults.length > 0) {
        searchIndex = 0;
        jumpToSearchResult(0);
    }

    if (hot) hot.render(); // trigger highlight renderer
}

function renderSearchResults() {
    const list = document.getElementById('search-results');
    list.innerHTML = searchResults.map((r, i) => {
        const label = r.header ? `${r.sheet} › ${escapeHtml(r.header)}` : `${r.sheet} › ${colToLetter(r.col)}${r.row + 1}`;
        return `<div class="search-result-item ${i === searchIndex ? 'active' : ''}" data-idx="${i}">
            <span class="search-result-loc">${label}</span>
            <span class="search-result-val">${escapeHtml(String(r.value ?? '').slice(0, 60))}</span>
        </div>`;
    }).join('');

    list.querySelectorAll('.search-result-item').forEach(el => {
        el.addEventListener('click', () => {
            searchIndex = parseInt(el.dataset.idx, 10);
            jumpToSearchResult(searchIndex);
            renderSearchResults();
        });
    });
}

function jumpToSearchResult(idx) {
    const r = searchResults[idx];
    if (!r) return;
    if (r.sheet !== currentSheet) {
        loadSheet(r.sheet).then(() => {
            setTimeout(() => { if (hot) hot.selectCell(r.row, r.col); }, 300);
        });
    } else if (hot) {
        hot.selectCell(r.row, r.col);
        hot.scrollViewportTo(r.row, r.col);
    }
}

function navigateSearch(dir) {
    if (searchResults.length === 0) return;
    searchIndex = (searchIndex + dir + searchResults.length) % searchResults.length;
    jumpToSearchResult(searchIndex);
    renderSearchResults();
    document.getElementById('search-count').textContent = `${searchIndex + 1}/${searchResults.length}`;
}

function replaceOne() {
    if (searchResults.length === 0 || searchIndex < 0) return;
    const r = searchResults[searchIndex];
    if (r.sheet !== currentSheet || !hot) return;
    const replaceVal = document.getElementById('search-replace-input').value;
    const current = String(hot.getDataAtCell(r.row, r.col) ?? '');
    const q = document.getElementById('search-case').checked ? searchQuery : searchQuery;
    const flags = document.getElementById('search-case').checked ? '' : 'i';
    let newVal;
    try {
        const useRegex = document.getElementById('search-regex').checked;
        const pat = useRegex ? searchQuery : escapeRegex(searchQuery);
        newVal = current.replace(new RegExp(pat, flags), replaceVal);
    } catch { newVal = current.replace(searchQuery, replaceVal); }
    hot.setDataAtCell(r.row, r.col, newVal);
    performSearch();
}

async function replaceAll() {
    if (searchResults.length === 0) return;
    const replaceVal = document.getElementById('search-replace-input').value;
    const flags = document.getElementById('search-case').checked ? 'g' : 'gi';
    const useRegex = document.getElementById('search-regex').checked;

    const bySheet = {};
    for (const r of searchResults) {
        if (!bySheet[r.sheet]) bySheet[r.sheet] = [];
        bySheet[r.sheet].push(r);
    }

    for (const [sheetName, results] of Object.entries(bySheet)) {
        if (sheetName === currentSheet && hot) {
            for (const r of results) {
                const current = String(hot.getDataAtCell(r.row, r.col) ?? '');
                try {
                    const pat = useRegex ? searchQuery : escapeRegex(searchQuery);
                    const newVal = current.replace(new RegExp(pat, flags), replaceVal);
                    hot.setDataAtCell(r.row, r.col, newVal);
                } catch {}
            }
        }
    }
    showSuccessToast(`Replaced ${searchResults.length} occurrence(s)`);
    performSearch();
}

// Search highlight renderer (used in cellFormatRenderer)
function isSearchMatch(row, col) {
    if (!searchPanelVisible || searchResults.length === 0) return false;
    return searchResults.some(r => r.sheet === currentSheet && r.row === row && r.col === col);
}

// ─── Cell Formatting ────────────────────────────────────────

function setupFormattingToolbar() {
    const toolbarLeft = document.getElementById('toolbar-left');
    const fmtGroup = document.createElement('div');
    fmtGroup.className = 'fmt-group';
    fmtGroup.innerHTML = `
        <button id="fmt-bold" class="fmt-btn" title="Bold (Ctrl+B)"><b>B</b></button>
        <button id="fmt-italic" class="fmt-btn" title="Italic (Ctrl+I)"><i>I</i></button>
        <input type="color" id="fmt-bg" class="fmt-color" title="Background Color" value="#1e1e2e">
        <input type="color" id="fmt-text" class="fmt-color" title="Text Color" value="#e0e0f0">
    `;
    toolbarLeft.appendChild(fmtGroup);

    document.getElementById('fmt-bold').addEventListener('click', () => toggleFormat('bold'));
    document.getElementById('fmt-italic').addEventListener('click', () => toggleFormat('italic'));
    document.getElementById('fmt-bg').addEventListener('change', (e) => applyColorFormat('bg_color', e.target.value));
    document.getElementById('fmt-text').addEventListener('change', (e) => applyColorFormat('text_color', e.target.value));
}

function toggleFormat(prop) {
    if (!hot || !currentSheet) return;
    const selected = hot.getSelected();
    if (!selected || selected.length === 0) return;
    const [r1, c1, r2, c2] = selected[0];
    for (let r = Math.min(r1, r2); r <= Math.max(r1, r2); r++) {
        for (let c = Math.min(c1, c2); c <= Math.max(c1, c2); c++) {
            const key = `${r}_${c}`;
            const current = cellMeta[key] || {};
            const newVal = !current[prop];
            if (newVal) { if (!cellMeta[key]) cellMeta[key] = {}; cellMeta[key][prop] = true; }
            else { if (cellMeta[key]) delete cellMeta[key][prop]; }
            apiUpdateFormat(currentSheet, r, c, { [prop]: newVal || null });
        }
    }
    hot.render();
}

function applyColorFormat(prop, color) {
    if (!hot || !currentSheet) return;
    const selected = hot.getSelected();
    if (!selected || selected.length === 0) return;
    const [r1, c1, r2, c2] = selected[0];
    for (let r = Math.min(r1, r2); r <= Math.max(r1, r2); r++) {
        for (let c = Math.min(c1, c2); c <= Math.max(c1, c2); c++) {
            const key = `${r}_${c}`;
            if (!cellMeta[key]) cellMeta[key] = {};
            cellMeta[key][prop] = color;
            apiUpdateFormat(currentSheet, r, c, { [prop]: color });
        }
    }
    hot.render();
}

function cellFormatRenderer(instance, td, row, col, prop, value, cellProperties) {
    Handsontable.renderers.TextRenderer.apply(this, arguments);
    const key = `${row}_${col}`;
    const fmt = cellMeta[key];
    if (fmt) {
        if (fmt.bold) td.style.fontWeight = '700';
        if (fmt.italic) td.style.fontStyle = 'italic';
        if (fmt.bg_color) td.style.background = fmt.bg_color;
        if (fmt.text_color) td.style.color = fmt.text_color;
    }
    if (isSearchMatch(row, col)) {
        td.classList.add('search-match');
    }
}

// ─── Column / Row Header Aliases ────────────────────────────

function buildColHeader(col) {
    const letter = colToLetter(col);
    const alias = columnAliases[String(col)];
    if (alias) {
        return `${escapeHtml(alias)} <span class="col-alias-letter">(${letter})</span>`;
    }
    return letter;
}

function buildRowHeader(row) {
    const num = row + 1;
    const alias = rowAliases[String(row)];
    if (alias) {
        return `${escapeHtml(alias)} <span class="row-alias-num">(${num})</span>`;
    }
    return String(num);
}

// Double-click on column header to edit alias
function setupHeaderAliasEditing() {
    if (!hot) return;
    const container = hot.rootElement;

    container.addEventListener('dblclick', (e) => {
        const th = e.target.closest('th');
        if (!th) return;

        // Determine if it's a column header or row header
        const tableHead = th.closest('thead');
        const tableBody = th.closest('tbody');

        if (tableHead) {
            // Column header
            const col = th.cellIndex - 1; // -1 because first th is row header
            if (col < 0) return;
            const currentAlias = columnAliases[String(col)] || '';
            showHeaderAliasInput(th, 'col', col, currentAlias);
        } else if (tableBody) {
            // Row header (first td in a row)
            const isRowHeader = th.tagName === 'TH' && th.classList.contains('rowHeader');
            if (!isRowHeader) return;
            const rowEl = th.closest('tr');
            if (!rowEl) return;
            const rows = Array.from(rowEl.parentNode.children);
            const row = rows.indexOf(rowEl);
            if (row < 0) return;
            const currentAlias = rowAliases[String(row)] || '';
            showHeaderAliasInput(th, 'row', row, currentAlias);
        }
    });
}

function showHeaderAliasInput(th, axis, index, currentAlias) {
    // Remove any existing overlay
    const existing = document.getElementById('alias-input-overlay');
    if (existing) existing.remove();

    const rect = th.getBoundingClientRect();
    const input = document.createElement('input');
    input.id = 'alias-input-overlay';
    input.type = 'text';
    input.value = currentAlias;
    input.placeholder = axis === 'col' ? 'Column name...' : 'Row label...';
    input.className = 'alias-input-overlay';
    input.style.position = 'fixed';
    input.style.left = `${rect.left}px`;
    input.style.top = `${rect.top}px`;
    input.style.width = `${Math.max(rect.width, 100)}px`;
    input.style.zIndex = '9999';
    document.body.appendChild(input);
    input.focus();
    input.select();

    async function commit() {
        const label = input.value.trim();
        input.remove();
        if (axis === 'col') {
            columnAliases[String(index)] = label;
            if (!label) delete columnAliases[String(index)];
        } else {
            rowAliases[String(index)] = label;
            if (!label) delete rowAliases[String(index)];
        }
        await apiUpdateAlias(currentSheet, axis, index, label);
        hot.updateSettings({
            colHeaders: axis === 'col' ? (col) => buildColHeader(col) : undefined,
            rowHeaders: axis === 'row' ? (row) => buildRowHeader(row) : undefined,
        });
        hot.render();
    }

    input.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') { e.preventDefault(); commit(); }
        else if (e.key === 'Escape') { input.remove(); }
    });
    input.addEventListener('blur', () => { setTimeout(() => { if (document.getElementById('alias-input-overlay')) commit(); }, 150); });
}

// ─── Add Row / Column Buttons ───────────────────────────────

function setupAddRowButton() {
    let btn = document.getElementById('add-row-btn');
    if (btn) return;
    btn = document.createElement('button');
    btn.id = 'add-row-btn';
    btn.className = 'add-row-btn';
    btn.title = 'Add row';
    btn.textContent = '+ Add Row';
    btn.addEventListener('click', async () => {
        if (!currentSheet || !sheetData) return;
        await apiInsertRows(currentSheet, sheetData.row_count, 1);
        await loadSheet(currentSheet);
    });
    document.getElementById('sheet-tabs').before(btn);
}

function setupAddColRightButton() {
    const btn = document.getElementById('add-col-btn-right');
    if (!btn) return;
    btn.addEventListener('click', async () => {
        if (!currentSheet) return;
        await apiAddColumn(currentSheet);
        await loadSheet(currentSheet);
    });
}

// ─── Sheet Tabs ─────────────────────────────────────────────

async function renderSheetTabs() {
    const tabs = document.getElementById('sheet-tabs');
    if (!tabs) return;
    const sheets = await fetchSheets();

    tabs.innerHTML = sheets.map(s =>
        `<button class="sheet-tab ${s.name === currentSheet ? 'active' : ''} ${s.protected ? 'sheet-tab-protected' : ''}"
            data-sheet="${escapeHtml(s.name)}"
            data-protected="${s.protected ? '1' : '0'}"
            title="${s.protected ? '🔒 Protected — right-click to unprotect' : 'Right-click for options'}">
            ${s.protected ? '🔒 ' : ''}${escapeHtml(s.name)}
        </button>`
    ).join('') + '<button class="sheet-tab sheet-tab-add" id="add-sheet-btn" title="New sheet">+</button>';

    tabs.querySelectorAll('.sheet-tab:not(.sheet-tab-add)').forEach(btn => {
        btn.addEventListener('click', () => loadSheet(btn.dataset.sheet));
        btn.addEventListener('dblclick', () => renameSheetPrompt(btn.dataset.sheet, btn));
        btn.addEventListener('contextmenu', e => { e.preventDefault(); showTabContextMenu(e, btn); });
    });

    document.getElementById('add-sheet-btn').addEventListener('click', createNewSheet);
}

// ─── Sheet Tab Context Menu ──────────────────────────────────

let _tabCtxMenu = null;

function showTabContextMenu(e, btn) {
    closeTabContextMenu();
    const sheetName = btn.dataset.sheet;
    const isProtected = btn.dataset.protected === '1';

    const menu = document.createElement('div');
    menu.className = 'tab-ctx-menu';
    menu.style.cssText = `position:fixed;left:${e.clientX}px;top:${e.clientY}px;z-index:9999`;

    const items = [
        { label: '✏️ Rename', action: () => renameSheetPrompt(sheetName, btn) },
        { label: isProtected ? '🔓 Unprotect' : '🔒 Protect', action: () => toggleProtectSheet(sheetName) },
        ...(!isProtected ? [{ label: '🗑️ Delete', action: () => deleteSheetPrompt(sheetName), danger: true }] : []),
    ];

    items.forEach(item => {
        const el = document.createElement('button');
        el.textContent = item.label;
        el.className = 'tab-ctx-item' + (item.danger ? ' tab-ctx-danger' : '');
        el.addEventListener('click', () => { closeTabContextMenu(); item.action(); });
        menu.appendChild(el);
    });

    document.body.appendChild(menu);
    _tabCtxMenu = menu;

    // Close on next outside click
    setTimeout(() => document.addEventListener('click', closeTabContextMenu, { once: true }), 0);
}

function closeTabContextMenu() {
    if (_tabCtxMenu) { _tabCtxMenu.remove(); _tabCtxMenu = null; }
}

async function deleteSheetPrompt(sheetName) {
    if (!confirm(`Delete sheet "${sheetName}"?\n\nThis cannot be undone.`)) return;
    try {
        await apiDeleteSheet(sheetName);
        showSuccessToast(`Sheet "${sheetName}" deleted`);
        // handleSheetDeleted arrives via WebSocket; also handle locally for robustness
        if (currentSheet === sheetName) {
            const sheets = await fetchSheets();
            if (sheets.length > 0) { currentSheet = sheets[0].name; await loadSheet(currentSheet); }
        }
        await renderSheetTabs();
        await populateSheetSelector();
    } catch (err) {
        showErrorToast(err.message);
    }
}

async function toggleProtectSheet(sheetName) {
    try {
        const res = await apiProtectSheet(sheetName);
        const msg = res.protected ? `🔒 "${sheetName}" is now protected` : `🔓 "${sheetName}" unprotected`;
        showSuccessToast(msg);
        await renderSheetTabs();
    } catch (err) {
        showErrorToast(err.message);
    }
}

async function apiDeleteSheet(name) {
    const res = await fetch(`/api/sheet/${encodeURIComponent(name)}`, { method: 'DELETE' });
    if (!res.ok) { const err = await res.json(); throw new Error(err.detail || 'Delete failed'); }
    return res.json();
}

async function apiProtectSheet(name) {
    const res = await fetch(`/api/sheet/${encodeURIComponent(name)}/protect`, { method: 'PATCH' });
    if (!res.ok) { const err = await res.json(); throw new Error(err.detail || 'Protect toggle failed'); }
    return res.json();
}

async function renameSheetPrompt(sheetName, btnEl) {
    const newName = prompt(`Rename sheet "${sheetName}" to:`, sheetName);
    if (!newName || newName.trim() === sheetName) return;
    try {
        await apiRenameSheet(sheetName, newName.trim());
        if (currentSheet === sheetName) currentSheet = newName.trim();
        await renderSheetTabs();
        await populateSheetSelector();
        showSuccessToast(`Renamed to "${newName.trim()}"`);
    } catch (err) {
        showErrorToast(err.message);
    }
}

async function createNewSheet() {
    const name = prompt('New sheet name:');
    if (!name || !name.trim()) return;
    try {
        await apiCreateSheet(name.trim());
        await renderSheetTabs();
        await loadSheet(name.trim());
        showSuccessToast(`Sheet "${name.trim()}" created`);
    } catch (err) {
        showErrorToast(err.message);
    }
}

// ─── Handsontable Setup ─────────────────────────────────────

function initGrid(containerId, headers, data) {
    const container = document.getElementById(containerId);
    // Use actual pixel height so Handsontable works inside a flex layout.
    // height:'100%' doesn't resolve when the parent is flex-sized.
    const initialHeight = container.clientHeight || window.innerHeight - 200;

    hot = new Handsontable(container, {
        data: data,
        colHeaders: (col) => buildColHeader(col),
        rowHeaders: (row) => buildRowHeader(row),
        width: '100%',
        height: initialHeight,
        stretchH: 'all',
        manualColumnResize: true,
        manualRowResize: true,
        columnSorting: true,
        autoWrapRow: true,
        autoWrapCol: true,
        undo: false,
        licenseKey: 'non-commercial-and-evaluation',

        renderer: cellFormatRenderer,

        contextMenu: {
            items: {
                'row_above': { name: 'Insert row above' },
                'row_below': { name: 'Insert row below' },
                'remove_row': { name: 'Delete row' },
                'separator1': '---------',
                'copy': { name: 'Copy' },
                'cut': { name: 'Cut' },
                'separator2': '---------',
                'undo_action': { name: 'Undo', callback: () => handleUndo() },
                'redo_action': { name: 'Redo', callback: () => handleRedo() },
            },
        },

        afterChange: (changes, source) => {
            if (!changes || source === 'loadData' || source === 'remote' || isSyncing) return;
            for (const [row, prop, oldVal, newVal] of changes) {
                const col = typeof prop === 'number' ? prop : hot.propToCol(prop);
                if (oldVal === newVal) continue;
                if (sheetData && sheetData.rows[row]) sheetData.rows[row][col] = String(newVal ?? '');
                patchCell(currentSheet, row, col, String(newVal ?? '')).then(result => {
                    if (result && result.evaluated !== undefined) {
                        const displayed = String(newVal ?? '');
                        if (result.evaluated !== displayed) {
                            isSyncing = true;
                            hot.setDataAtCell(row, col, result.evaluated, 'remote');
                            isSyncing = false;
                        }
                    }
                });
            }
            updateStatusBar();
        },

        afterSelectionEnd: (row, col) => {
            updateFormulaBar(row, col);
            updateStatusBar();
        },

        afterBeginEditing: (row, col) => { onCellEditStart(row, col); },

        afterCreateRow: (index, amount, source) => {
            if (source === 'ContextMenu.rowAbove' || source === 'ContextMenu.rowBelow') {
                apiInsertRows(currentSheet, index, amount).then(() => loadSheet(currentSheet));
            }
        },

        afterRemoveRow: (index, amount, physicalRows, source) => {
            if (source === 'ContextMenu.removeRow') {
                apiDeleteRows(currentSheet, physicalRows || [index]).then(() => loadSheet(currentSheet));
            }
        },

        afterDeselect: () => {
            const selected = hot.getSelected();
            if (selected) {
                for (const sel of selected) onCellEditEnd(sel[0], sel[1]);
            }
        },

        afterGetColHeader: (col, TH) => {
            // hot may be null if this fires during the constructor — skip until assigned
            if (!hot) return;
            // Add "+" button to last column header
            if (col === hot.countCols() - 1) {
                let addBtn = TH.querySelector('.col-add-btn');
                if (!addBtn) {
                    addBtn = document.createElement('button');
                    addBtn.className = 'col-add-btn';
                    addBtn.title = 'Add column';
                    addBtn.textContent = '+';
                    addBtn.addEventListener('click', async (e) => {
                        e.stopPropagation();
                        if (!currentSheet) return;
                        await apiAddColumn(currentSheet);
                        await loadSheet(currentSheet);
                    });
                    TH.style.position = 'relative';
                    TH.appendChild(addBtn);
                }
            }
        },
    });

    setupHeaderAliasEditing();

    // Trigger a re-render so afterGetColHeader fires with hot assigned (the + button)
    setTimeout(() => { if (hot) hot.render(); }, 0);

    // Keep Handsontable height in sync as the container resizes
    const ro = new ResizeObserver(entries => {
        for (const entry of entries) {
            const h = entry.contentRect.height;
            if (h > 0 && hot) hot.updateSettings({ height: h });
        }
    });
    ro.observe(container);

    return hot;
}

// ─── Sheet Loading ──────────────────────────────────────────

async function loadSheet(name) {
    showLoadingOverlay('Loading sheet...');
    try {
        const [data, meta] = await Promise.all([fetchSheet(name), fetchMeta(name)]);
        sheetData = data;
        currentSheet = name;
        cellMeta = meta.cells || {};
        columnAliases = meta.column_aliases || {};
        rowAliases = meta.row_aliases || {};

        if (hot) {
            isSyncing = true;
            hot.loadData(data.evaluated);
            hot.updateSettings({
                colHeaders: (col) => buildColHeader(col),
                rowHeaders: (row) => buildRowHeader(row),
            });
            isSyncing = false;
        } else {
            initGrid('spreadsheet', data.headers, data.evaluated);
            setupFormulaBar();
        }

        updateStatusBar();
        await renderSheetTabs();

        const selector = document.getElementById('sheet-selector');
        if (selector) selector.value = name;

        if (!ws || ws.readyState !== WebSocket.OPEN) connectWebSocket();

        // Re-run search if panel is open
        if (searchPanelVisible) performSearch();
    } catch (err) {
        showErrorToast(`Failed to load sheet: ${err.message}`);
    } finally {
        hideLoadingOverlay();
    }
}

// ─── Sheet Selector ─────────────────────────────────────────

async function populateSheetSelector() {
    const sheets = await fetchSheets();
    const selector = document.getElementById('sheet-selector');
    selector.innerHTML = '';
    for (const sheet of sheets) {
        const opt = document.createElement('option');
        opt.value = sheet.name;
        opt.textContent = sheet.name;  // simplified — no row count
        selector.appendChild(opt);
    }
    selector.addEventListener('change', () => loadSheet(selector.value));
    return sheets;
}

// ─── Export ─────────────────────────────────────────────────

function setupExportButton() {
    document.getElementById('export-btn').addEventListener('click', () => {
        if (currentSheet) window.location = `/api/sheet/${encodeURIComponent(currentSheet)}/export`;
    });
}

// ─── Keyboard Shortcuts ─────────────────────────────────────

function setupKeyboardShortcuts() {
    document.addEventListener('keydown', (e) => {
        const isCtrl = e.ctrlKey || e.metaKey;
        if (isCtrl && e.key === 'z' && !e.shiftKey) { e.preventDefault(); e.stopPropagation(); handleUndo(); }
        else if (isCtrl && (e.key === 'y' || (e.key === 'z' && e.shiftKey))) { e.preventDefault(); e.stopPropagation(); handleRedo(); }
        else if (isCtrl && e.key === 's') { e.preventDefault(); }
        else if (isCtrl && e.key === 'f' && !e.shiftKey) { e.preventDefault(); openSearchPanel(false); }
        else if (isCtrl && e.key === 'h') { e.preventDefault(); openSearchPanel(true); }
        else if (isCtrl && e.key === 'b') { e.preventDefault(); toggleFormat('bold'); }
        else if (isCtrl && e.key === 'i' && !e.shiftKey) { e.preventDefault(); toggleFormat('italic'); }
        else if (e.key === 'Escape') { if (searchPanelVisible) closeSearchPanel(); }
    }, true);
}

// ─── Status Bar ─────────────────────────────────────────────

function updateStatusBar() {
    const posEl = document.getElementById('status-position');
    if (!hot) return;
    const selected = hot.getSelected();
    if (selected && selected.length > 0) {
        const [row, col] = selected[0];
        posEl.textContent = `${colToLetter(col)}${row + 1} | ${sheetData?.row_count ?? 0} rows × ${sheetData?.col_count ?? 0} cols`;
    }
}

// ─── Init ───────────────────────────────────────────────────

async function init() {
    try {
        initTheme();
        setupSearchPanel();
        setupFormattingToolbar();
        setupShareModal();
        setupSettingsModal();

        document.getElementById('theme-btn').addEventListener('click', toggleTheme);

        const sheets = await populateSheetSelector();
        if (sheets.length > 0) {
            await loadSheet(sheets[0].name);
        } else {
            document.getElementById('status-info').textContent = 'No sheets found — create one with the + button';
        }

        setupExportButton();
        setupKeyboardShortcuts();
        setupAddRowButton();
        setupAddColRightButton();
    } catch (err) {
        console.error('Init error:', err);
        showErrorToast(`Startup error: ${err.message}`);
    }
}

init();

export { hot, currentSheet, sheetData, loadSheet, patchCell, fetchSheets, fetchSheet, applyChangesToGrid, connectWebSocket };
