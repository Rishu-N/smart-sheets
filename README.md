# SmartSheet

A local-first, AI-powered spreadsheet that runs in your browser. Host it on your laptop and anyone on your local network can open it and collaborate in real time — no accounts, no cloud, no build step.

---

## Features

### Grid & Data
- **Spreadsheet grid** — Handsontable-powered grid with column sorting, resizable rows/columns, and a formula bar
- **Server-side formulas** — `=SUM`, `=AVERAGE`, `=COUNT`, `=COUNTA`, `=MIN`, `=MAX`, `=IF`, `=CONCAT` evaluated on the backend; results broadcast to all clients
- **Multiple sheets** — tab bar at the bottom; create new sheets with the `+` button; double-click a tab to rename it
- **Add rows** — `+ Add Row` button below the grid appends a blank row; right-click context menu for insert above/below and delete
- **Add columns** — `+` button on the last column header OR the persistent `+` strip on the right edge of the grid appends a column
- **Export CSV** — one-click download of the current sheet

### Formatting
- **Cell formatting** — bold (Ctrl+B), italic (Ctrl+I), background colour, text colour; persisted in `.meta.json` per sheet
- **Custom column & row names** — double-click any column or row header to set a display alias shown as `"Revenue (A)"` / `"Q1 (1)"` — original letter/number stays visible inline; stored in `.meta.json`

### History
- **Undo / Redo** — delta-based, 50-level history per sheet (Ctrl+Z / Ctrl+Y or Ctrl+Shift+Z)

### Collaboration
- **Real-time collaboration** — WebSocket sync; edits appear on all connected clients within ~100 ms
- **Open LAN sync** — by default (`require_guest_auth: false`) anyone on your network opens the sheet straight away — no login, no OTP
- **Cell locking** — a coloured border marks cells being edited by another user; they become read-only until released
- **Presence bar** — coloured avatar initials in the toolbar show who is connected
- **LAN guest auth** (optional) — when enabled, guests enter their name, you see their OTP in the terminal and as a browser toast; wrong OTP 3× triggers a 2-minute lockout

### Search
- **Enhanced search** — Ctrl+F slides in a side panel with case-sensitive, whole-cell, and regex toggles; search across all sheets; clickable results list; find & replace (Ctrl+H)

### Sharing & Settings
- **Share QR modal** — click **Share** to show your LAN URL and a scannable QR code guests can use to join
- **Light / dark theme** — toggle with the ☀ button in the toolbar; preference saved in the browser
- **Editable cell reference box** — type a cell address (e.g. `C7`) in the top-left box and press Enter to jump there
- **Settings modal** — gear icon lets you change the AI model, API key, base URL, undo depth, and auth mode without restarting

### AI Assistant
Click **AI** in the toolbar to open the sidebar. Requires `openai_api_key` in `config.json` or `OPENAI_API_KEY` in a `.env` file.

| Mode | Description |
|------|-------------|
| **Q&A** | Ask questions about your data; answer streams in real time |
| **Data Dump** | Paste unstructured text; AI parses it into rows with a preview before committing |
| **Column Fill** | Describe what a column should contain; AI generates values with a diff preview |
| **Formula** | Describe what you want; AI writes the formula and explains it |
| **Edit Mode** | Toggle the **✎ Edit** switch to let AI modify the spreadsheet — creates new sheets, edits cells, appends rows — with a full diff preview before you confirm or cancel |

Every AI commit automatically creates a timestamped backup at `data/.backups/<sheet>_<timestamp>.bak`.

### Developer Tools
- **Swagger UI** — full interactive API documentation at `http://localhost:8000/docs` (ReDoc at `/redoc`)
- **Auto-backup** — every AI commit creates a timestamped `.bak` copy in `data/.backups/`
- **File watcher** — edit the CSV directly on disk; the browser reloads automatically

---

## Requirements

- Python 3.11+
- pip packages: `fastapi`, `uvicorn`, `pandas`, `watchdog`, `openai`, `python-dotenv`, `qrcode`, `plyer`

Install everything at once:

```bash
pip install fastapi uvicorn[standard] pandas watchdog openai python-dotenv qrcode plyer
```

---

## Quick Start

```bash
cd smartsheet
python3 app.py
```

The server starts on port 8000, prints your LAN URL and a QR code, and opens the browser automatically.

**You (the host)** — the browser opens straight to the spreadsheet, no login needed.

**Guests on your LAN** — by default, they open `http://<your-LAN-IP>:8000` and land straight on the sheet. No name entry, no OTP. To require OTP auth, set `require_guest_auth: true` in `config.json` (or toggle it in the Settings modal).

---

## Configuration

Edit `config.json` before starting, or use the **Settings** modal (gear icon) while the app is running — changes take effect immediately without a restart.

The app also reads `OPENAI_API_KEY` from a `.env` file in the project root or `backend/` directory (the `.env` value is used when `openai_api_key` in `config.json` is blank).

| Key | Default | Description |
|-----|---------|-------------|
| `openai_api_key` | `""` | Your OpenAI API key. Leave blank to disable AI features (or set `OPENAI_API_KEY` in `.env`). |
| `base_url` | `""` | Optional custom base URL for the OpenAI API (e.g. a proxy or compatible endpoint). |
| `port` | `8000` | Port the server listens on. |
| `data_dir` | `"./data"` | Folder where CSV sheet files are stored. |
| `open_browser` | `true` | Auto-open browser on startup. |
| `require_guest_auth` | `false` | When `false`, LAN guests access the sheet without OTP. Set to `true` to re-enable OTP auth. |
| `otp_expiry_seconds` | `300` | How long a guest OTP is valid (seconds). |
| `otp_max_attempts` | `3` | Wrong OTP attempts before lockout. |
| `otp_lockout_seconds` | `120` | Lockout duration after too many wrong attempts. |
| `desktop_notifications` | `true` | Show OS notification when a guest requests access. |
| `undo_depth` | `50` | Number of undo steps kept per sheet. |
| `ai_model` | `"gpt-4.1"` | OpenAI model used for AI features. Supported: `gpt-4.1`, `gpt-4.1-mini`, `gpt-4o`, `gpt-4o-mini`. |
| `max_context_rows` | `200` | Rows sent to the AI in full; larger sheets send summary stats instead. |

---

## Keyboard Shortcuts

| Shortcut | Action |
|----------|--------|
| Ctrl+Z | Undo |
| Ctrl+Y / Ctrl+Shift+Z | Redo |
| Ctrl+S | No-op (auto-saves on every edit) |
| Ctrl+F | Open search panel |
| Ctrl+H | Open search panel in find & replace mode |
| Ctrl+B | Toggle bold on selected cells |
| Ctrl+I | Toggle italic on selected cells |
| Escape | Close search panel |

---

## Sheets

- Click the **`+`** tab at the bottom to create a new sheet.
- **Double-click** a sheet tab to rename it.
- Drop any `.csv` file into the `data/` folder — it appears as a new tab on reload.

---

## Adding Rows and Columns

- Click **`+ Add Row`** below the grid to append a blank row.
- Click the **`+`** button on the last column header, or the **`+`** strip on the right edge of the grid, to append a new column.
- Right-click any cell for the context menu (insert above/below, delete row).

---

## Renaming Column and Row Headers

Double-click any column or row header to type a custom display alias. The alias is shown inline alongside the original letter/number: `"Revenue (A)"` or `"Quarter (1)"`. Aliases are stored in `.meta.json` and do not rename the underlying CSV column.

---

## Formulas

Formulas start with `=` and are evaluated server-side. Supported functions:

| Function | Example |
|----------|---------|
| `SUM` | `=SUM(B2:B20)` |
| `AVERAGE` | `=AVERAGE(C2:C10)` |
| `COUNT` | `=COUNT(D2:D100)` |
| `COUNTA` | `=COUNTA(A2:A50)` |
| `MIN` | `=MIN(E2:E20)` |
| `MAX` | `=MAX(E2:E20)` |
| `IF` | `=IF(C2>100,"High","Low")` |
| `CONCAT` | `=CONCAT(A2," ",B2)` |

Arithmetic expressions with cell references also work: `=C2*D2`, `=(A2+B2)/2`.

Row 1 is always the header. Data starts at row 2, which maps to Excel cell reference row 2.

---

## AI Assistant

Click **AI** in the toolbar to open the sidebar. Requires `openai_api_key` in `config.json` or `OPENAI_API_KEY` in `.env`.

### Q&A
Ask any question about the current sheet. The answer streams in real time. Example: *"Which product has the highest total revenue?"*

### Data Dump
Paste raw text (copy-paste from an email, a note, a website). AI parses it into rows matching your sheet's columns. A preview shows the new rows highlighted — click **Commit Changes** to append them, or **Cancel** to discard.

### Column Fill
Select a column from the dropdown, describe what you want, and click **Generate Values**. A diff table shows old vs new values. Click **Commit Changes** to write them. Example: *"Generate a product category based on the Name column."*

### Formula
Describe the formula in plain English, enter the target cell, and click **Generate Formula**. The formula and an explanation are shown. Click **Commit Changes** to insert it.

### Edit Mode
Enable the **✎ Edit** toggle in the AI sidebar header. In Edit Mode, the Q&A input becomes an instruction box. Describe what you want to change — *"Add a total revenue column multiplying Quantity × Price"* or *"Create a new sheet called Summary with aggregated data"*. The AI uses tool calls to plan changes, then shows a diff preview (cell changes table, new sheets, rows to append). Click **Commit Changes** to apply or **Cancel** to discard.

Every commit automatically creates a backup at `data/.backups/<sheet>_<timestamp>.bak`.

---

## API Reference & Swagger

Full interactive Swagger docs are available at **`http://localhost:8000/docs`** (ReDoc at `/redoc`). All endpoints are grouped by tag:

**Auth** (`/auth/`)
| Method | Path | Description |
|--------|------|-------------|
| GET | `/auth/whoami` | Check host status and open-access flag |
| POST | `/auth/request` | Request guest OTP `{name}` |
| POST | `/auth/verify` | Verify OTP and get session `{request_id, otp}` |
| POST | `/auth/disconnect` | Disconnect a guest session (host only) `{user_id}` |
| GET | `/auth/sessions` | List active sessions (host only) |

**Sheets** (`/api/sheets`, `/api/sheet/:name`)
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/sheets` | List all sheets |
| POST | `/api/sheets/create` | Create a new empty sheet `{name, columns}` |
| GET | `/api/sheet/:name` | Load sheet data (headers, rows, evaluated formulas) |
| PATCH | `/api/sheet/:name/rename` | Rename sheet `{new_name}` |
| GET | `/api/sheet/:name/export` | Download sheet as CSV |
| POST | `/api/sheet/:name/columns` | Append columns `{count}` |

**Cells** (`/api/sheet/:name/…`)
| Method | Path | Description |
|--------|------|-------------|
| PATCH | `/api/sheet/:name/cell` | Update a cell `{row, col, value}` |
| POST | `/api/sheet/:name/rows` | Insert rows `{index, count}` |
| DELETE | `/api/sheet/:name/rows` | Delete rows `{indices: [...]}` |
| POST | `/api/sheet/:name/undo` | Undo last action |
| POST | `/api/sheet/:name/redo` | Redo last undone action |
| GET | `/api/sheet/:name/meta` | Get cell formatting + alias metadata |
| PATCH | `/api/sheet/:name/format` | Set cell format `{row, col, format}` |
| PATCH | `/api/sheet/:name/alias` | Set header alias `{axis, index, label}` |

**AI** (`/api/ai/…`)
| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/ai/query` | Stream Q&A answer (SSE) `{question, sheet}` |
| POST | `/api/ai/fill` | Generate column values `{sheet, column_index, instruction}` |
| POST | `/api/ai/dump` | Parse raw text into rows `{sheet, raw_text}` |
| POST | `/api/ai/formula` | Generate a formula `{sheet, description, target_cell}` |
| POST | `/api/ai/edit` | AI edit mode (tool use) `{sheet, instruction}` |
| POST | `/api/ai/confirm` | Commit a pending AI result `{confirm_id, sheet}` |

**Share & Settings**
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/share-info` | Returns `{lan_url, qr_svg}` for the Share modal |
| GET | `/api/settings` | Return current config values |
| PATCH | `/api/settings` | Update config values (live, no restart needed) |

**Real-time**
| Protocol | Path | Description |
|----------|------|-------------|
| WS | `/ws/:session_token` | Real-time sync (cell updates, locks, presence) |

---

## Project Structure

```
smartsheet/
├── app.py                  # Entry point: prints banner, starts uvicorn
├── config.json             # Configuration file
├── .env                    # Optional: OPENAI_API_KEY (not committed)
├── data/                   # CSV sheet files (created on first run)
│   ├── sample.csv
│   └── .backups/           # Auto-backups created before AI commits
├── backend/
│   ├── main.py             # FastAPI app, all HTTP + WebSocket endpoints + Swagger
│   ├── config.py           # Config loader / singleton + .env support + save_config()
│   ├── sheet_manager.py    # CSV read/write, formula evaluation, undo, column/alias ops
│   ├── undo_manager.py     # Delta-based undo/redo stacks per sheet
│   ├── auth_manager.py     # OTP generation, session management, open-LAN sessions
│   ├── sync.py             # WebSocket connection manager, cell locks, presence
│   ├── watcher.py          # Watchdog file watcher for external CSV edits
│   ├── ai_engine.py        # OpenAI client, 5 AI modes (Q&A/fill/dump/formula/edit), backups
│   └── notifier.py         # Terminal OTP print + desktop notification
├── frontend/
│   ├── index.html          # App shell, auth screens, modals, search panel
│   ├── grid.js             # Grid, WebSocket client, all UI logic (theme, search, aliases…)
│   ├── auth.js             # Name/OTP auth screens; skips auth in open-LAN mode
│   ├── ai_panel.js         # AI sidebar with 5 mode tabs + edit mode, SSE stream reader
│   └── style.css           # Dark + light theme, all component styles
└── macapp/                 # Optional macOS menu-bar companion (SwiftUI)
    └── README.md           # `cd macapp && ./build.sh && open "build/Reading Tracker.app"`
```

---

## macOS menu-bar app (optional)

A SwiftUI menu-bar companion lives in [`macapp/`](macapp/README.md). 📚 icon
in the menu bar → click → popover with title / URL / word-count fields, a
start-pause-stop-reset timer, and a Save button that appends a row to the
`Reading Log` sheet (visible in the existing web UI).

**What it does**

- Auto-spawns `python3 app.py` on launch (or adopts an already-running
  server). SIGTERMs the python child cleanly on quit.
- **Inline read-status tag** next to the URL field: 🟢 green capsule if you
  have already logged that URL, 🔴 red if it's new — debounced check
  against `/api/reading/check`.
- **Fetch** opens the URL in your browser AND scrapes the page for a word
  count via `/api/reading/wordcount`. Three-rung User-Agent fallback so
  Akamai-style WAFs that 403 browser UAs don't break the flow.
- **Manual time entry** — separate Min/Sec fields default to `00`/`00`,
  for when you forgot to start the timer.
- **Reset** button on the timer; **🔁 Reload** in the footer for a clean
  app restart.
- **Notification on save without time** — saves the row anyway and posts a
  macOS notification ("tap to open spreadsheet and add the time") with a
  deep link to the web UI.
- **Date format** in the saved row: `DD-MMM-YYYY : HH:MM:SS`
  (e.g. `04-May-2026 : 17:36:42`).

**Build and run** — any Mac with Xcode Command Line Tools:

```bash
cd macapp
./build.sh
open "build/Reading Tracker.app"
```

To make it appear in Spotlight / Launchpad, copy the bundle to
`/Applications/` once after building:

```bash
cp -R "macapp/build/Reading Tracker.app" /Applications/
```

See [`macapp/README.md`](macapp/README.md) for the full feature list,
prerequisites, distribution, icon customization, and troubleshooting.

---

## Security Notes

- The server is designed for **trusted local networks only**. Do not expose port 8000 to the internet.
- In the default open-LAN mode (`require_guest_auth: false`), anyone who can reach port 8000 can read and edit sheets. Only use this on networks you trust.
- Session tokens are stored in a browser cookie (`HttpOnly: false` so JavaScript can read them for the WebSocket URL).
- The host machine is identified by its local IP addresses (127.0.0.1, ::1, and your LAN IP). No password is needed for the host.
- OTPs are single-use and expire after 5 minutes by default (only relevant when `require_guest_auth: true`).
- Keep your `.env` file out of version control — it contains your OpenAI API key.
