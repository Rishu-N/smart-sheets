// SmartSheet — AI Panel module

import { currentSheet, sheetData, hot, loadSheet, patchCell, fetchSheet } from '/grid.js';

// ─── State ──────────────────────────────────────────────────
let panelOpen = false;
let currentMode = 'qa';  // qa | dump | fill | formula
let chatHistory = [];
let pendingConfirmId = null;
let isStreaming = false;
let editMode = false;

// ─── Panel Setup ────────────────────────────────────────────

export function initAIPanel() {
    createPanelHTML();
    setupPanelEvents();
}

function createPanelHTML() {
    // Bind to existing toggle button in toolbar (added via index.html)
    const btn = document.getElementById('ai-toggle-btn');
    if (btn) btn.addEventListener('click', togglePanel);

    // Panel container
    const panel = document.createElement('div');
    panel.id = 'ai-panel';
    panel.className = 'ai-panel';
    panel.innerHTML = `
        <div class="ai-panel-header">
            <div class="ai-panel-tabs">
                <button class="ai-tab active" data-mode="qa">Q&A</button>
                <button class="ai-tab" data-mode="dump">Data Dump</button>
                <button class="ai-tab" data-mode="fill">Column Fill</button>
                <button class="ai-tab" data-mode="formula">Formula</button>
            </div>
            <div class="ai-header-actions">
                <label class="ai-edit-toggle" title="Enable edit mode — AI can modify your spreadsheet">
                    <input type="checkbox" id="ai-edit-mode-chk">
                    <span>✎ Edit</span>
                </label>
                <button class="ai-panel-close" id="ai-close-btn">&times;</button>
            </div>
        </div>

        <div class="ai-panel-body">
            <!-- Q&A Mode -->
            <div class="ai-mode" id="ai-mode-qa">
                <div id="ai-edit-banner" class="ai-edit-banner" style="display:none">
                    ✎ Edit mode ON — AI will preview changes before applying
                </div>
                <div class="ai-chat" id="ai-chat"></div>
                <div class="ai-input-area">
                    <textarea id="ai-query-input" placeholder="Ask about your data..." rows="2"></textarea>
                    <button id="ai-send-btn" class="ai-action-btn">Send</button>
                </div>
                <div id="ai-edit-preview" class="ai-preview" style="display:none"></div>
            </div>

            <!-- Data Dump Mode -->
            <div class="ai-mode" id="ai-mode-dump" style="display:none">
                <p class="ai-mode-desc">Paste unstructured text and AI will parse it into spreadsheet rows.</p>
                <textarea id="ai-dump-input" class="ai-textarea" placeholder="Paste text data here...&#10;e.g. John, New York, $500&#10;Jane, California, $1200" rows="6"></textarea>
                <button id="ai-dump-btn" class="ai-action-btn">Parse Data</button>
                <div id="ai-dump-preview" class="ai-preview"></div>
            </div>

            <!-- Column Fill Mode -->
            <div class="ai-mode" id="ai-mode-fill" style="display:none">
                <p class="ai-mode-desc">Select a column, describe the values you want, and AI will generate them.</p>
                <div class="ai-field">
                    <label>Target Column</label>
                    <select id="ai-fill-column"></select>
                </div>
                <div class="ai-field">
                    <label>Instruction</label>
                    <textarea id="ai-fill-instruction" class="ai-textarea" placeholder="e.g. Generate product categories based on the name column" rows="3"></textarea>
                </div>
                <button id="ai-fill-btn" class="ai-action-btn">Generate Values</button>
                <div id="ai-fill-preview" class="ai-preview"></div>
            </div>

            <!-- Formula Mode -->
            <div class="ai-mode" id="ai-mode-formula" style="display:none">
                <p class="ai-mode-desc">Describe what you want the formula to do.</p>
                <div class="ai-field">
                    <label>Target Cell</label>
                    <input type="text" id="ai-formula-cell" placeholder="e.g. E2" class="ai-text-input">
                </div>
                <div class="ai-field">
                    <label>Description</label>
                    <textarea id="ai-formula-desc" class="ai-textarea" placeholder="e.g. Calculate the total by multiplying quantity and price" rows="3"></textarea>
                </div>
                <button id="ai-formula-btn" class="ai-action-btn">Generate Formula</button>
                <div id="ai-formula-preview" class="ai-preview"></div>
            </div>
        </div>

        <!-- Confirm bar (shown when preview is active) -->
        <div class="ai-confirm-bar" id="ai-confirm-bar" style="display:none">
            <button id="ai-confirm-btn" class="ai-confirm-action">Commit Changes</button>
            <button id="ai-cancel-btn" class="ai-cancel-action">Cancel</button>
        </div>
    `;
    document.getElementById('app-container').appendChild(panel);
}

function setupPanelEvents() {
    // Tab switching
    document.querySelectorAll('.ai-tab').forEach(tab => {
        tab.addEventListener('click', () => switchMode(tab.dataset.mode));
    });

    // Close button
    document.getElementById('ai-close-btn').addEventListener('click', togglePanel);

    // Q&A
    document.getElementById('ai-send-btn').addEventListener('click', sendQuery);
    document.getElementById('ai-query-input').addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendQuery();
        }
    });

    // Data Dump
    document.getElementById('ai-dump-btn').addEventListener('click', sendDump);

    // Column Fill
    document.getElementById('ai-fill-btn').addEventListener('click', sendFill);

    // Formula
    document.getElementById('ai-formula-btn').addEventListener('click', sendFormula);

    // Confirm / Cancel
    document.getElementById('ai-confirm-btn').addEventListener('click', confirmResult);
    document.getElementById('ai-cancel-btn').addEventListener('click', cancelResult);

    // Edit mode toggle
    document.getElementById('ai-edit-mode-chk').addEventListener('change', (e) => {
        editMode = e.target.checked;
        document.getElementById('ai-edit-banner').style.display = editMode ? 'block' : 'none';
        document.getElementById('ai-query-input').placeholder = editMode
            ? 'Describe what to change...'
            : 'Ask about your data...';
        document.getElementById('ai-edit-preview').style.display = 'none';
        hideConfirmBar();
    });
}

// ─── Panel Toggle ───────────────────────────────────────────

function togglePanel() {
    panelOpen = !panelOpen;
    const panel = document.getElementById('ai-panel');
    panel.classList.toggle('open', panelOpen);

    // Update fill column selector when opening
    if (panelOpen && currentMode === 'fill') {
        populateColumnSelector();
    }
}

// ─── Mode Switching ─────────────────────────────────────────

function switchMode(mode) {
    currentMode = mode;
    document.querySelectorAll('.ai-tab').forEach(t => t.classList.toggle('active', t.dataset.mode === mode));
    document.querySelectorAll('.ai-mode').forEach(m => m.style.display = 'none');
    document.getElementById(`ai-mode-${mode}`).style.display = '';

    if (mode === 'fill') populateColumnSelector();
    if (mode === 'formula') updateFormulaCellFromSelection();

    // Hide confirm bar when switching
    hideConfirmBar();
}

function populateColumnSelector() {
    const select = document.getElementById('ai-fill-column');
    select.innerHTML = '';
    const headers = sheetData?.headers || [];
    headers.forEach((h, i) => {
        const opt = document.createElement('option');
        opt.value = i;
        opt.textContent = h;
        select.appendChild(opt);
    });
}

function updateFormulaCellFromSelection() {
    if (!hot) return;
    const selected = hot.getSelected();
    if (selected && selected.length > 0) {
        const [row, col] = selected[0];
        const letter = colToLetter(col);
        document.getElementById('ai-formula-cell').value = `${letter}${row + 2}`; // +2: header=row1, data starts row2
    }
}

function colToLetter(col) {
    let letter = '';
    let n = col;
    while (n >= 0) {
        letter = String.fromCharCode(65 + (n % 26)) + letter;
        n = Math.floor(n / 26) - 1;
    }
    return letter;
}

// ─── Q&A Mode ───────────────────────────────────────────────

async function sendQuery() {
    const input = document.getElementById('ai-query-input');
    const question = input.value.trim();
    if (!question || !currentSheet || isStreaming) return;

    appendMessage('user', question);
    input.value = '';
    isStreaming = true;

    if (editMode) {
        await sendEditRequest(question);
        isStreaming = false;
        return;
    }

    // Get selection info
    let selection = null;
    if (hot) {
        const selected = hot.getSelected();
        if (selected && selected.length > 0) {
            selection = {
                start_row: selected[0][0],
                start_col: selected[0][1],
                end_row: selected[0][2],
                end_col: selected[0][3],
            };
        }
    }

    const msgEl = appendMessage('assistant', '');
    const contentEl = msgEl.querySelector('.ai-msg-content');

    try {
        const res = await fetch('/api/ai/query', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ question, sheet: currentSheet, selection }),
        });

        if (!res.ok) {
            const err = await res.json();
            contentEl.textContent = `Error: ${err.detail || 'Unknown error'}`;
            isStreaming = false;
            return;
        }

        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';
        let fullText = '';

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split('\n');
            buffer = lines.pop() || '';

            for (const line of lines) {
                if (!line.startsWith('data: ')) continue;
                try {
                    const payload = JSON.parse(line.slice(6));
                    if (payload.error) {
                        contentEl.textContent = `Error: ${payload.error}`;
                        break;
                    }
                    if (payload.chunk) {
                        fullText += payload.chunk;
                        contentEl.textContent = fullText;
                        scrollChat();
                    }
                } catch (e) { /* skip malformed */ }
            }
        }

        chatHistory.push({ role: 'assistant', content: fullText });
    } catch (err) {
        contentEl.textContent = `Error: ${err.message}`;
    }

    isStreaming = false;
}

async function sendEditRequest(instruction) {
    const msgEl = appendMessage('assistant', '');
    const contentEl = msgEl.querySelector('.ai-msg-content');
    contentEl.textContent = 'Analyzing changes...';

    const preview = document.getElementById('ai-edit-preview');
    preview.style.display = 'none';
    preview.innerHTML = '';

    try {
        const res = await fetch('/api/ai/edit', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ sheet: currentSheet, instruction }),
        });

        if (!res.ok) {
            const err = await res.json();
            contentEl.textContent = `Error: ${err.detail || 'Unknown error'}`;
            return;
        }

        const data = await res.json();
        contentEl.textContent = data.explanation || 'Ready to apply changes.';
        pendingConfirmId = data.confirm_id;
        renderEditPreview(data);
        scrollChat();
    } catch (err) {
        contentEl.textContent = `Error: ${err.message}`;
    }
}

function renderEditPreview(data) {
    const preview = document.getElementById('ai-edit-preview');
    const parts = [];

    if (data.cell_changes && data.cell_changes.length > 0) {
        let html = `<p class="ai-hint"><strong>${data.cell_changes.length} cell change(s)</strong></p>`;
        html += '<table class="ai-preview-table"><thead><tr><th>Cell</th><th>Old</th><th>New</th></tr></thead><tbody>';
        for (const ch of data.cell_changes) {
            const letter = colToLetter(ch.col);
            html += `<tr class="ai-row-changed">`;
            html += `<td>${letter}${ch.row + 1}</td>`;
            html += `<td class="ai-old-val">${escapeHtml(ch.old_value)}</td>`;
            html += `<td class="ai-new-val">${escapeHtml(ch.new_value)}</td>`;
            html += '</tr>';
        }
        html += '</tbody></table>';
        parts.push(html);
    }

    if (data.new_sheets && data.new_sheets.length > 0) {
        for (const ns of data.new_sheets) {
            parts.push(`<p class="ai-hint">📄 New sheet: <strong>${escapeHtml(ns.name)}</strong> (${ns.headers.length} columns)</p>`);
        }
    }

    if (data.new_rows && data.new_rows.length > 0) {
        parts.push(`<p class="ai-hint">➕ ${data.new_rows.length} row(s) to append</p>`);
    }

    if (parts.length === 0) {
        preview.innerHTML = '<p class="ai-hint">No changes proposed.</p>';
    } else {
        preview.innerHTML = parts.join('');
        showConfirmBar();
    }
    preview.style.display = 'block';
}

function appendMessage(role, content) {
    const chat = document.getElementById('ai-chat');
    const msg = document.createElement('div');
    msg.className = `ai-msg ai-msg-${role}`;
    msg.innerHTML = `<div class="ai-msg-content">${escapeHtml(content)}</div>`;
    chat.appendChild(msg);
    if (role === 'user') chatHistory.push({ role, content });
    scrollChat();
    return msg;
}

function scrollChat() {
    const chat = document.getElementById('ai-chat');
    chat.scrollTop = chat.scrollHeight;
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// ─── Data Dump Mode ─────────────────────────────────────────

async function sendDump() {
    const input = document.getElementById('ai-dump-input');
    const rawText = input.value.trim();
    if (!rawText || !currentSheet) return;

    const preview = document.getElementById('ai-dump-preview');
    preview.innerHTML = '<p class="ai-loading">Parsing data...</p>';

    try {
        const res = await fetch('/api/ai/dump', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ sheet: currentSheet, raw_text: rawText }),
        });

        if (!res.ok) {
            const err = await res.json();
            preview.innerHTML = `<p class="ai-error">Error: ${err.detail}</p>`;
            return;
        }

        const data = await res.json();
        pendingConfirmId = data.confirm_id;
        renderDumpPreview(data);
        showConfirmBar();
    } catch (err) {
        preview.innerHTML = `<p class="ai-error">Error: ${err.message}</p>`;
    }
}

function renderDumpPreview(data) {
    const preview = document.getElementById('ai-dump-preview');
    if (!data.rows || data.rows.length === 0) {
        preview.innerHTML = '<p class="ai-hint">No rows parsed.</p>';
        return;
    }

    const headers = sheetData?.headers || [];
    let html = '<table class="ai-preview-table"><thead><tr>';
    for (const h of headers) html += `<th>${escapeHtml(h)}</th>`;
    html += '</tr></thead><tbody>';

    for (const row of data.rows) {
        html += '<tr class="ai-row-new">';
        for (let i = 0; i < headers.length; i++) {
            html += `<td>${escapeHtml(String(row[i] ?? ''))}</td>`;
        }
        html += '</tr>';
    }
    html += '</tbody></table>';
    html += `<p class="ai-hint">${data.rows.length} row(s) will be appended.</p>`;
    preview.innerHTML = html;
}

// ─── Column Fill Mode ───────────────────────────────────────

async function sendFill() {
    const colIdx = parseInt(document.getElementById('ai-fill-column').value);
    const instruction = document.getElementById('ai-fill-instruction').value.trim();
    if (isNaN(colIdx) || !instruction || !currentSheet) return;

    const colName = sheetData?.headers?.[colIdx] || `Column ${colIdx}`;
    const preview = document.getElementById('ai-fill-preview');
    preview.innerHTML = '<p class="ai-loading">Generating values...</p>';

    try {
        const res = await fetch('/api/ai/fill', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                sheet: currentSheet,
                column_index: colIdx,
                column_name: colName,
                instruction,
            }),
        });

        if (!res.ok) {
            const err = await res.json();
            preview.innerHTML = `<p class="ai-error">Error: ${err.detail}</p>`;
            return;
        }

        const data = await res.json();
        pendingConfirmId = data.confirm_id;
        renderFillPreview(data);
        showConfirmBar();
    } catch (err) {
        preview.innerHTML = `<p class="ai-error">Error: ${err.message}</p>`;
    }
}

function renderFillPreview(data) {
    const preview = document.getElementById('ai-fill-preview');
    if (!data.fills || data.fills.length === 0) {
        preview.innerHTML = '<p class="ai-hint">No changes to preview.</p>';
        return;
    }

    let html = `<p class="ai-hint">Column: <strong>${escapeHtml(data.column_name)}</strong></p>`;
    html += '<table class="ai-preview-table"><thead><tr><th>Row</th><th>Old</th><th>New</th></tr></thead><tbody>';

    for (const fill of data.fills) {
        const changed = fill.old_value !== fill.new_value;
        html += `<tr class="${changed ? 'ai-row-changed' : ''}">`;
        html += `<td>${fill.row + 1}</td>`;
        html += `<td class="ai-old-val">${escapeHtml(fill.old_value)}</td>`;
        html += `<td class="ai-new-val">${escapeHtml(fill.new_value)}</td>`;
        html += '</tr>';
    }
    html += '</tbody></table>';
    preview.innerHTML = html;
}

// ─── Formula Mode ───────────────────────────────────────────

async function sendFormula() {
    const targetCell = document.getElementById('ai-formula-cell').value.trim();
    const description = document.getElementById('ai-formula-desc').value.trim();
    if (!targetCell || !description || !currentSheet) return;

    const preview = document.getElementById('ai-formula-preview');
    preview.innerHTML = '<p class="ai-loading">Generating formula...</p>';

    try {
        const res = await fetch('/api/ai/formula', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                sheet: currentSheet,
                description,
                target_cell: targetCell,
            }),
        });

        if (!res.ok) {
            const err = await res.json();
            preview.innerHTML = `<p class="ai-error">Error: ${err.detail}</p>`;
            return;
        }

        const data = await res.json();
        pendingConfirmId = data.confirm_id;
        renderFormulaPreview(data);
        showConfirmBar();
    } catch (err) {
        preview.innerHTML = `<p class="ai-error">Error: ${err.message}</p>`;
    }
}

function renderFormulaPreview(data) {
    const preview = document.getElementById('ai-formula-preview');
    let html = `
        <div class="ai-formula-result">
            <div class="ai-formula-box">
                <label>Formula for ${escapeHtml(data.target_cell)}:</label>
                <code class="ai-formula-code">${escapeHtml(data.formula)}</code>
            </div>
            <p class="ai-formula-explanation">${escapeHtml(data.explanation)}</p>
        </div>
    `;
    preview.innerHTML = html;
}

// ─── Confirm / Cancel ───────────────────────────────────────

async function confirmResult() {
    if (!pendingConfirmId || !currentSheet) return;

    const confirmBtn = document.getElementById('ai-confirm-btn');
    confirmBtn.textContent = 'Committing...';
    confirmBtn.disabled = true;

    try {
        const res = await fetch('/api/ai/confirm', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ confirm_id: pendingConfirmId, sheet: currentSheet }),
        });

        if (!res.ok) {
            const err = await res.json();
            alert(`Commit failed: ${err.detail}`);
            return;
        }

        // Reload sheet to reflect changes
        await loadSheet(currentSheet);
        clearPreviews();
        hideConfirmBar();
    } catch (err) {
        alert(`Commit error: ${err.message}`);
    } finally {
        confirmBtn.textContent = 'Commit Changes';
        confirmBtn.disabled = false;
        pendingConfirmId = null;
    }
}

function cancelResult() {
    pendingConfirmId = null;
    clearPreviews();
    hideConfirmBar();
}

function showConfirmBar() {
    document.getElementById('ai-confirm-bar').style.display = '';
}

function hideConfirmBar() {
    document.getElementById('ai-confirm-bar').style.display = 'none';
}

function clearPreviews() {
    document.getElementById('ai-dump-preview').innerHTML = '';
    document.getElementById('ai-fill-preview').innerHTML = '';
    document.getElementById('ai-formula-preview').innerHTML = '';
}
