# Reading Tracker — macOS Menu-Bar App

A SwiftUI menu-bar companion for the SmartSheet project. Click the 📚 icon
in the menu bar → log an article (title, URL, word count, timer) → a row
appears in `Reading Log.csv` viewable in the existing web UI.

The app is a **universal binary** (arm64 + x86_64) and builds without Xcode —
the **Xcode Command Line Tools** are enough.

---

## TL;DR — build and run

```bash
cd macapp
./build.sh
open "build/Reading Tracker.app"
```

That's it. The script generates the custom icon, compiles the Swift sources,
assembles `Reading Tracker.app`, ad-hoc-codesigns it with the entitlements,
and writes the result to `macapp/build/Reading Tracker.app`. Run it on any
Mac with Xcode CLT and a Python 3 with the SmartSheet deps installed (see
[prerequisites](#prerequisites)).

The first launch pops a macOS permission prompt asking for access to the
folder that contains the project (Desktop / Documents / Downloads). **Click
Allow** — the app spawns `python3 app.py` from that folder, and macOS
silently blocks the spawn (`getcwd()` hangs) if permission is denied. The
first time you save without using the timer, you'll also get a Notifications
permission prompt — allow that too if you want the missing-time reminder.

---

## How to start the app (after building)

| Method | Command / steps |
| --- | --- |
| Finder | Double-click `macapp/build/Reading Tracker.app`. |
| Terminal | `open "/path/to/smartsheet/macapp/build/Reading Tracker.app"` |
| Spotlight (recommended) | `cp -R "macapp/build/Reading Tracker.app" /Applications/` once, then `⌘ + Space` → type "Reading Tracker" → Return. |
| Auto-start on login | System Settings → General → Login Items → **+** → pick `Reading Tracker.app`. |
| One-shot rebuild + run | `cd macapp && ./build.sh && open "build/Reading Tracker.app"` |

When running, the app shows a 📚 icon in the menu bar (no Dock icon — it's
an `LSUIElement` accessory app) and auto-starts the FastAPI backend in the
background.

---

## Features

### Menu-bar popover
- **Article title** field (required to save).
- **URL** field with **inline read-status tag**:
  - 🟢 **green capsule** ("Read · `<date>`") if the URL is already in your
    Reading Log — the tooltip shows the original article title.
  - 🔴 **red capsule** ("New — not in your log") if it's a URL you haven't
    logged yet.
  - The check is debounced 500 ms after you stop typing, cancels stale
    requests, and silently hides itself when the server isn't ready.
- **Fetch** button next to the URL → opens the URL in your default browser
  AND asks the backend to scrape the page for `word_count` and `<title>`.
  Uses a 3-rung User-Agent ladder (`ReadingTracker/1.0` → `curl/8.7.1` →
  modern Chrome) so Akamai-style WAFs that 403 browser-shaped UAs don't
  break the flow (this fixes e.g. `results.eci.gov.in`).
- **Word count** field (digit-only) — auto-filled by Fetch but editable.
- **Timer** with `Start / Pause / Resume / Stop / Reset`. Big mm:ss (or
  h:mm:ss for long reads) display with monospaced digits.
- **Manual time entry** — separate **Min** and **Sec** text fields (default
  `00`/`00`) plus a **Set** button. For when you forgot to start the timer.
  Minutes accept up to 4 digits (9999); seconds auto-clamp to 0–59. Disabled
  while the timer is running so a live session can't be silently overwritten.
- **Save reading** — POST to `/api/reading/log` (auto-computes WPM, formats
  the date as `DD-MMM-YYYY : HH:MM:SS`). Resets the form on success.
- **Notification on save without time** — if you click Save with the timer
  at `00:00`, the row is still saved (so you don't lose the article) and
  macOS posts a notification "Reading saved without time — `<title>`. Tap
  to open the spreadsheet and add the time." The notification's **Open
  Spreadsheet** action button (and tapping the body) deep-links to
  `http://localhost:8000`.
- **Live WPM** indicator in the save row updates as the timer ticks.
- **Server status** dot in the header (green = running/adopted, yellow =
  starting, red = failed, grey = stopped).

### Footer controls
- **Open Spreadsheet** — `http://localhost:8000` in your default browser.
- **Settings…** — project root, Python interpreter path, server port.
- **🔁 Reload** — full app restart. Spawns a detached shell that polls until
  our PID is gone (so the python child has been SIGTERM'd cleanly), waits
  500 ms, then `open -n`s a fresh copy of the bundle. Use this after
  changing settings or after editing the SmartSheet backend.
- **Quit** — `NSApp.terminate(nil)`. The `applicationShouldTerminate`
  handler SIGTERMs the python child (3 s grace, then SIGKILL).

### Server lifecycle
- **Auto-spawns `python3 app.py`** from the configured project root on
  launch. stdout / stderr go to `~/Library/Logs/ReadingTracker.log`.
- **Adopts an existing server** if one is already listening on the
  configured port (status shows "adopted" and the lifecycle handler skips
  the SIGTERM at quit, so external servers aren't murdered by the app).
- **Health-poll** for up to 20 s after spawn before declaring "failed".

### Custom app icon
- 1024 × 1024 squircle, warm amber → burnt-orange gradient.
- Open book with two pages and faint horizontal text lines.
- Stopwatch dial overlay (white face, blue bezel and hand, orange progress
  arc) symbolising "reading + time tracking".
- Rendered programmatically by `Resources/make_icon.swift` —
  `iconutil`-compiled into `AppIcon.icns` at all 10 standard sizes.

---

## Prerequisites

| Requirement | How to install |
| --- | --- |
| macOS 13 (Ventura) or newer | — |
| Xcode Command Line Tools (Swift, `swiftc`, `iconutil`, `codesign`) | `xcode-select --install` |
| Python 3.10+ with the SmartSheet backend deps | see below |

### Python deps

The menu-bar app launches `python3 app.py`, which imports:

```
fastapi  uvicorn  pandas  pydantic  httpx  beautifulsoup4
qrcode  watchdog  openai  python-dotenv  plyer
```

Install once into the interpreter the app will use:

```bash
python3 -m pip install \
  fastapi 'uvicorn[standard]' pandas pydantic httpx beautifulsoup4 \
  qrcode watchdog openai python-dotenv plyer
```

To use a venv, set its `bin/python` path under **Settings…** in the app.

---

## What `build.sh` does

1. Renders the custom app icon if `Resources/AppIcon.icns` is missing or
   `Resources/make_icon.swift` is newer (Swift + CoreGraphics, no Xcode
   assets needed). Output: 10 PNGs in `build/AppIcon.iconset/`, compiled to
   `Resources/AppIcon.icns` via `iconutil`.
2. Compiles `Sources/*.swift` for **arm64** and **x86_64** with deploy target
   `macOS 13.0`, then `lipo`s them into a single universal binary. Falls
   back to host-only if cross-compile fails.
3. Stamps the bundle: copies `Info.plist` (with TCC usage strings),
   `AppIcon.icns`, sets `CFBundleExecutable` and `CFBundleIconFile` via
   `PlistBuddy`.
4. Strips extended attributes (`xattr -cr`) and ad-hoc-codesigns the bundle
   with the entitlements (`codesign --sign -`). Verifies with
   `codesign --verify`.

Output:

```
macapp/build/Reading Tracker.app
├── Contents/
│   ├── Info.plist
│   ├── MacOS/
│   │   └── Reading Tracker          (universal binary)
│   ├── Resources/
│   │   └── AppIcon.icns
│   └── _CodeSignature/
```

To **re-render the icon** after editing `Resources/make_icon.swift`, just
run `./build.sh` again — the script picks up the timestamp change
automatically.

---

## Distributing to other machines

Anyone with **macOS 13+** and the **Xcode Command Line Tools** can clone the
repo and run `./build.sh`. Because the build is ad-hoc-signed (no Apple
Developer ID), the first launch on **another** Mac will get the standard
Gatekeeper warning ("can't be opened because it is from an unidentified
developer"). Workarounds:

```bash
# Either right-click the app in Finder → Open → "Open Anyway",
# or strip the quarantine attribute from the terminal:
xattr -dr com.apple.quarantine "/path/to/Reading Tracker.app"
```

Optional: ship just the `.app` bundle (no need to include sources):

```bash
ditto -c -k --keepParent "build/Reading Tracker.app" ReadingTracker.zip
```

---

## First-run setup

1. **Files & Folders permission** — macOS asks "Reading Tracker would like
   to access files in your Desktop folder" the first time it tries to spawn
   python. Click **Allow**. (If you missed it, re-grant under
   **System Settings → Privacy & Security → Files and Folders → Reading
   Tracker**.)
2. **Notifications permission** — pops the first time you save a reading
   without tracking time. Allow it to receive the "fill in the time"
   reminder; deny and the app silently opens the spreadsheet directly
   instead.
3. Click the menu-bar icon → **Settings…**
   - **Project root** — absolute path to the SmartSheet project root (the
     folder containing `app.py`). Default is pre-filled for
     `~/Desktop/CLaude/excel/smartsheet`.
   - **Python path** — leave blank to auto-resolve `python3` via `which`.
     Set to an absolute venv path (e.g. `~/.venvs/smartsheet/bin/python`)
     if needed.
   - **Server port** — default 8000.
4. The status dot should switch from grey/yellow → green within ~3 s. Click
   **Open Spreadsheet** to load `http://localhost:8000` in your browser.

### Optional: silence the auto-open browser

`config.json` has `"open_browser": true`, which pops a browser tab every time
the menu-bar app starts the server. To disable:

```bash
# either edit config.json directly:
#   "open_browser": false
# or PATCH the live server once:
curl -X PATCH http://localhost:8000/api/settings \
     -H 'content-type: application/json' \
     -d '{"open_browser": false}'
```

---

## Troubleshooting

- **`xcode-select: error: tool 'swiftc' requires Xcode...`**
  Run `xcode-select --install` and re-run `./build.sh`.
- **`build.sh` fails on `codesign`**
  The script auto-runs `xattr -cr` first; if codesign still rejects the
  bundle, an MDM policy may block ad-hoc signing — sign with your
  Developer ID instead by replacing `--sign -` in `build.sh`.
- **Status stuck on "starting…"**
  Tail the log: `tail -f ~/Library/Logs/ReadingTracker.log`. Common causes:
  - `ModuleNotFoundError: No module named 'X'` → install the deps for the
    interpreter the app is using (Settings → Python path).
  - Python child hangs at `getcwd` → the macOS folder permission was
    denied. Re-grant under **System Settings → Privacy & Security → Files
    and Folders**.
  - Port conflict → change `serverPort` in Settings, or `lsof -i:8000` to
    find what owns it.
- **Server already running before launch**
  The app probes `/auth/whoami` first — if it gets `200`, it adopts the
  existing process instead of spawning a duplicate (status: **adopted**).
  At quit it leaves the adopted server running.
- **Word-count fetch returns 502**
  Some sites (Akamai-fronted, like ECI) reject browser-shaped User-Agents.
  The backend now tries `ReadingTracker/1.0` → `curl/8.7.1` → modern
  Chrome before giving up; if all three are rejected you'll see a clear
  400 telling you to enter the count manually.
- **No notification on save without time**
  Check **System Settings → Notifications → Reading Tracker** is enabled.
  If notifications are denied, the app falls back to opening the
  spreadsheet directly so the reminder isn't lost.
- **Reset the app's TCC decision** (re-trigger the permission prompt):
  ```bash
  tccutil reset SystemPolicyDesktopFolder local.readingtracker
  tccutil reset SystemPolicyDocumentsFolder local.readingtracker
  tccutil reset SystemPolicyDownloadsFolder local.readingtracker
  ```

---

## Customizing the icon

Edit `Resources/make_icon.swift` (it's a self-contained Swift script that
draws into a `NSBitmapImageRep` and emits the iconset PNGs). Tweak colors,
shapes, layout — then re-run:

```bash
./build.sh    # regenerates AppIcon.icns and rebuilds
```

Preview a single size without rebuilding the app:

```bash
swift Resources/make_icon.swift /tmp/iconset
open /tmp/iconset/icon_512x512.png
```

---

## Backend endpoints used by the app

| Endpoint | Purpose |
| --- | --- |
| `GET  /auth/whoami` | Health probe (also used to decide adopt-vs-spawn). |
| `POST /api/reading/log` | Append a row with title, URL, word count, time, WPM, formatted date. |
| `GET  /api/reading/check?query=` | URL exact-match (after tracking-param normalisation) plus title fuzzy-match. Drives the green/red URL tag. |
| `POST /api/reading/wordcount` | Fetch a URL, strip non-content tags, return readable word count + page title. UA fallback ladder for hostile WAFs. |

All four live in `backend/main.py` and `backend/reading.py`.

---

## File layout

```
macapp/
├── build.sh                       # one-command build → Reading Tracker.app
├── Info.plist                     # bundle metadata + TCC usage strings
├── ReadingTracker.entitlements    # App Sandbox OFF, network client ON
├── Resources/
│   ├── make_icon.swift            # icon generator (run via `swift`)
│   └── AppIcon.icns               # generated, committed for convenience
├── Sources/
│   ├── ReadingTrackerApp.swift    # @main, MenuBarExtra, AppDelegate
│   ├── PopoverView.swift          # popover UI + Settings sheet + Reload/Reset
│   ├── ServerController.swift     # python3 lifecycle, health polling, adoption
│   ├── TimerModel.swift           # start/pause/resume/stop/reset, setManual, WPM
│   ├── NotificationManager.swift  # missing-time reminder via UNUserNotificationCenter
│   ├── APIClient.swift            # async REST client
│   ├── AppSettings.swift          # @AppStorage settings
│   └── Models.swift               # Codable DTOs (Equatable)
└── build/                         # generated; .app bundle lives here
```

---

## Building with Xcode (alternative)

If you'd rather use Xcode's GUI:

1. **File → New → Project… → macOS → App**.
2. Product Name: `Reading Tracker`. Interface: **SwiftUI**. Bundle ID:
   `local.readingtracker`. Save outside this folder.
3. Delete the auto-generated `ContentView.swift` and `Reading_TrackerApp.swift`.
4. Drag `macapp/Sources/` into the Project Navigator. **Copy items if needed
   = OFF**, **Create groups = ON**.
5. Drag `macapp/Info.plist` and point the target's "Info.plist File" build
   setting at it. Drag `macapp/ReadingTracker.entitlements` and set the
   target's "Code Signing Entitlements" path.
6. **Signing & Capabilities → uncheck App Sandbox**.
7. Drag `macapp/Resources/AppIcon.icns` into Resources, or use an
   `Assets.xcassets`-based AppIcon set.
8. **General → Deployment Target = macOS 13.0**.
9. Cmd-R to run.
