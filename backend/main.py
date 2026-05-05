"""FastAPI application for SmartSheet."""

import asyncio
import json
import logging
import webbrowser
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from backend.auth_manager import Session, get_auth_manager, init_auth_manager
from backend.sync import get_sync_manager
from backend.config import get_config, load_config, save_config
from backend.notifier import print_otp_to_terminal, send_desktop_notification
from backend.sheet_manager import (
    add_column as sm_add_column,
    create_sheet as sm_create_sheet,
    delete_rows as sm_delete_rows,
    delete_sheet as sm_delete_sheet,
    insert_rows as sm_insert_rows,
    list_sheets as sm_list_sheets,
    perform_redo as sm_redo,
    perform_undo as sm_undo,
    read_meta as sm_read_meta,
    read_sheet as sm_read_sheet,
    rename_sheet as sm_rename_sheet,
    update_cell as sm_update_cell,
    update_cell_format as sm_update_cell_format,
    update_header_alias as sm_update_header_alias,
)
from backend.undo_manager import init_undo_manager
from backend.watcher import start_watcher, stop_watcher
from backend.ai_engine import init_ai_engine, get_ai_engine
from backend.reading import (
    READING_SHEET_NAME,
    ensure_reading_sheet,
    fetch_word_count,
    find_matches,
)

logger = logging.getLogger("smartsheet")

# Global references
_watcher_observer = None
_event_loop = None


# ─── Pydantic Request / Response Models ──────────────────────

class CreateSheetBody(BaseModel):
    name: str = Field(..., min_length=1, max_length=50, description="Sheet name")
    columns: int = Field(5, ge=1, le=100, description="Number of initial columns")

class UpdateCellBody(BaseModel):
    row: int = Field(..., ge=0, description="0-based data row index")
    col: int = Field(..., ge=0, description="0-based column index")
    value: str = Field("", description="New cell value or formula (prefix = for formulas)")

class InsertRowsBody(BaseModel):
    index: int = Field(0, ge=0, description="Row index to insert before")
    count: int = Field(1, ge=1, le=1000, description="Number of rows to insert")

class DeleteRowsBody(BaseModel):
    indices: list[int] = Field(..., description="List of 0-based row indices to delete")

class UpdateFormatBody(BaseModel):
    row: int = Field(..., ge=0)
    col: int = Field(..., ge=0)
    format: dict[str, Any] = Field({}, description="Format dict e.g. {bold: true, bg_color: '#ff0'}")

class UpdateAliasBody(BaseModel):
    axis: str = Field(..., description="'col' or 'row'")
    index: int = Field(..., ge=0, description="0-based column or row index")
    label: str = Field("", description="Display alias. Empty string clears the alias.")

class RenameSheetBody(BaseModel):
    new_name: str = Field(..., min_length=1, max_length=50, description="New sheet name")

class AddColumnsBody(BaseModel):
    count: int = Field(1, ge=1, le=50, description="Number of columns to append")

class AuthRequestBody(BaseModel):
    name: str = Field(..., min_length=2, max_length=32, description="Guest display name")

class AuthVerifyBody(BaseModel):
    request_id: str = Field(..., description="Request ID from /auth/request")
    otp: str = Field(..., min_length=6, max_length=6, description="6-digit OTP")

class AuthDisconnectBody(BaseModel):
    user_id: str = Field(..., description="User ID to disconnect")

class AIQueryBody(BaseModel):
    question: str = Field(..., description="Question to ask about the spreadsheet data")
    sheet: str = Field(..., description="Sheet name to query")
    selection: Optional[dict] = Field(None, description="Optional selected range {start_row, end_row}")

class AIFillBody(BaseModel):
    sheet: str = Field(..., description="Sheet name")
    column_index: int = Field(..., ge=0, description="0-based column index to fill")
    column_name: str = Field("", description="Column header name (for context)")
    instruction: str = Field(..., description="Natural language description of what to fill")
    target_rows: Optional[list[int]] = Field(None, description="Specific row indices to fill (null = all rows)")

class AIDumpBody(BaseModel):
    sheet: str = Field(..., description="Sheet name")
    raw_text: str = Field(..., description="Unstructured text to parse into rows")

class AIFormulaBody(BaseModel):
    sheet: str = Field(..., description="Sheet name")
    description: str = Field(..., description="Natural language description of the formula")
    target_cell: str = Field(..., description="Target cell reference e.g. 'B5'")

class AIEditBody(BaseModel):
    sheet: str = Field(..., description="Sheet name to edit")
    instruction: str = Field(..., description="Natural language instruction for what to change")

class AIConfirmBody(BaseModel):
    confirm_id: str = Field(..., description="Confirm ID from the AI generation endpoint")
    sheet: str = Field(..., description="Sheet name")

class SettingsPatchBody(BaseModel):
    openai_api_key: Optional[str] = Field(None, description="OpenAI API key")
    base_url: Optional[str] = Field(None, description="Custom OpenAI-compatible base URL")
    ai_model: Optional[str] = Field(None, description="Model ID e.g. gpt-4.1")
    max_context_rows: Optional[int] = Field(None, ge=10, le=10000)
    undo_depth: Optional[int] = Field(None, ge=1, le=500)
    open_browser: Optional[bool] = None
    desktop_notifications: Optional[bool] = None
    otp_expiry_seconds: Optional[int] = Field(None, ge=30, le=3600)
    require_guest_auth: Optional[bool] = None

class ReadingLogBody(BaseModel):
    title: str = Field(..., min_length=1, max_length=500, description="Article title")
    url: str = Field("", max_length=2000, description="Article URL")
    word_count: int = Field(..., ge=0, description="Total words in the article")
    time_seconds: int = Field(..., ge=0, description="Elapsed reading time in seconds")
    wpm: float = Field(..., ge=0, description="Words per minute (computed client-side)")

class ReadingWordCountBody(BaseModel):
    url: str = Field(..., min_length=1, max_length=2000, description="URL to fetch and word-count")


# ─── OpenAPI Tags ─────────────────────────────────────────────

_TAGS_METADATA = [
    {"name": "auth", "description": "Authentication — OTP guest flow and host identification"},
    {"name": "sheets", "description": "Sheet management — CRUD, data access, import/export"},
    {"name": "cells", "description": "Cell-level operations — update, undo/redo, formatting"},
    {"name": "ai", "description": "AI assistant — Q&A, column fill, data dump, formula generation, edit mode"},
    {"name": "share", "description": "Share info — LAN URL and QR code"},
    {"name": "settings", "description": "Live settings — read and update config without restarting"},
    {"name": "realtime", "description": "WebSocket — real-time sync, cell locks, presence"},
    {"name": "reading", "description": "Reading Log — log sessions, fetch word counts, dedupe checks"},
]


def _get_client_ip(request: Request) -> str:
    """Extract client IP from request."""
    # Check X-Forwarded-For first (in case of proxy)
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "127.0.0.1"


# ─── Auth Middleware ─────────────────────────────────────────

_PUBLIC_PREFIXES = ("/auth/", "/docs", "/openapi.json", "/redoc")


class AuthMiddleware:
    """ASGI middleware: enforce session auth on /api/ routes for non-host IPs.
    WebSocket and non-API scopes are always passed through untouched."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        # Only inspect HTTP requests — pass everything else (websocket, lifespan) through
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")

        # Public paths and non-API paths — pass through
        if any(path.startswith(p) for p in _PUBLIC_PREFIXES) or not path.startswith("/api/"):
            await self.app(scope, receive, send)
            return

        # Extract client IP
        client = scope.get("client")
        ip = client[0] if client else "127.0.0.1"
        # Check X-Forwarded-For header
        for name, value in scope.get("headers", []):
            if name == b"x-forwarded-for":
                ip = value.decode().split(",")[0].strip()
                break

        auth_mgr = get_auth_manager()

        # Host IPs — always pass through
        if auth_mgr.is_host(ip):
            await self.app(scope, receive, send)
            return

        # Open LAN mode — allow all guests without session check
        try:
            config = get_config()
            if not config.require_guest_auth:
                await self.app(scope, receive, send)
                return
        except RuntimeError:
            pass

        # Extract session token from Cookie header
        token = None
        for name, value in scope.get("headers", []):
            if name == b"cookie":
                for part in value.decode().split(";"):
                    part = part.strip()
                    if part.startswith("session_token="):
                        token = part[len("session_token="):]
                        break

        if not token or not auth_mgr.validate_session(token):
            body = json.dumps({"error": "unauthorized", "message": "Session token required"}).encode()
            await send({
                "type": "http.response.start",
                "status": 401,
                "headers": [
                    [b"content-type", b"application/json"],
                    [b"content-length", str(len(body)).encode()],
                ],
            })
            await send({"type": "http.response.body", "body": body})
            return

        # Valid session — store in scope state for downstream handlers
        session = auth_mgr.validate_session(token)
        if "state" not in scope:
            scope["state"] = {}
        scope["state"]["session"] = session
        await self.app(scope, receive, send)
        return


# ─── Lifespan ────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _watcher_observer, _event_loop

    _event_loop = asyncio.get_running_loop()

    # Load config if not already loaded
    try:
        config = get_config()
    except RuntimeError:
        import os
        config_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config.json")
        config = load_config(config_path)

    # Initialize managers
    init_undo_manager(config.undo_depth)
    init_auth_manager(config.otp_expiry_seconds, config.otp_max_attempts, config.otp_lockout_seconds)

    # Initialize AI engine if API key is set
    if config.openai_api_key:
        init_ai_engine(config.openai_api_key, config.ai_model, config.max_context_rows, config.base_url)
        logger.info("[STARTUP] AI engine initialized")
    else:
        logger.warning("[STARTUP] No openai_api_key — AI features disabled")

    # Ensure data directory exists
    config.data_dir.mkdir(parents=True, exist_ok=True)

    # Bootstrap the Reading Log sheet (idempotent)
    ensure_reading_sheet(config.data_dir)

    # Start file watcher — bridge sync thread to async event loop
    def on_csv_change(sheet_name: str):
        logger.info(f"[WATCHER] External change detected: {sheet_name}")
        sync_mgr = get_sync_manager()
        asyncio.run_coroutine_threadsafe(
            sync_mgr.broadcast("sheet_reload", {"sheet": sheet_name}),
            _event_loop,
        )

    _watcher_observer = start_watcher(str(config.data_dir), on_csv_change)
    logger.info(f"[STARTUP] File watcher started on {config.data_dir}")

    # Auto-open browser
    if config.open_browser:
        webbrowser.open(f"http://localhost:{config.port}")

    yield

    if _watcher_observer:
        stop_watcher(_watcher_observer)
        logger.info("[SHUTDOWN] File watcher stopped")


app = FastAPI(
    title="SmartSheet API",
    version="1.0.0",
    description=(
        "**SmartSheet** is a local-first, AI-powered spreadsheet with real-time collaboration.\n\n"
        "All endpoints under `/api/` require either a host IP or a valid `session_token` cookie "
        "(when `require_guest_auth` is `true`). In the default open-LAN mode, all guests have access.\n\n"
        "The AI endpoints require an `openai_api_key` to be configured."
    ),
    openapi_tags=_TAGS_METADATA,
    lifespan=lifespan,
)

# Middleware — auth check (added first so it runs on every request)
app.add_middleware(AuthMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── Auth Endpoints ──────────────────────────────────────────


@app.get("/auth/whoami", tags=["auth"], summary="Check host status and open-access flag")
async def auth_whoami(request: Request):
    ip = _get_client_ip(request)
    auth_mgr = get_auth_manager()
    config = get_config()

    # Check if already has a valid session
    token = request.cookies.get("session_token")
    session = auth_mgr.validate_session(token) if token else None

    return {
        "is_host": auth_mgr.is_host(ip),
        "ip": ip,
        "has_session": session is not None,
        "display_name": session.display_name if session else None,
        "color": session.color if session else None,
        "session_token": session.session_token if session else None,
        "open_access": not config.require_guest_auth,
    }


@app.post("/auth/request", tags=["auth"], summary="Request guest OTP")
async def auth_request(body: AuthRequestBody, request: Request):
    ip = _get_client_ip(request)
    auth_mgr = get_auth_manager()
    config = get_config()

    # Rate limit
    if not auth_mgr.check_rate_limit(ip):
        raise HTTPException(status_code=429, detail="Too many requests. Try again in a minute.")

    # Check lockout
    locked, remaining = auth_mgr.is_locked_out(ip)
    if locked:
        raise HTTPException(status_code=429, detail=f"Locked out. Try again in {remaining} seconds.")

    name = body.name.strip()
    if not name or len(name) < 2 or len(name) > 32:
        raise HTTPException(status_code=400, detail="Name must be 2-32 characters")

    # Generate OTP
    otp_req = auth_mgr.create_otp_request(name, ip)

    # Notify host via terminal
    print_otp_to_terminal(name, otp_req.otp, config.otp_expiry_seconds)

    # Notify host via desktop notification
    if config.desktop_notifications:
        send_desktop_notification(
            title=f"SmartSheet: {name} wants to join",
            message=f"OTP: {otp_req.otp}",
        )

    # Broadcast OTP request to host via WebSocket
    sync_mgr = get_sync_manager()
    await sync_mgr.send_to_host("otp_request", {
        "request_id": otp_req.request_id,
        "name": name,
        "ip": ip,
        "otp": otp_req.otp,
        "expires_in": config.otp_expiry_seconds,
    })

    return {
        "request_id": otp_req.request_id,
        "status": "pending",
        "expires_in": config.otp_expiry_seconds,
    }


@app.post("/auth/verify", tags=["auth"], summary="Verify OTP and get session")
async def auth_verify(body: AuthVerifyBody, request: Request):
    ip = _get_client_ip(request)
    auth_mgr = get_auth_manager()

    # Rate limit
    if not auth_mgr.check_rate_limit(ip):
        raise HTTPException(status_code=429, detail="Too many requests.")

    # Check lockout
    locked, remaining = auth_mgr.is_locked_out(ip)
    if locked:
        return JSONResponse(
            status_code=403,
            content={"status": "locked_out", "retry_after": remaining},
        )

    request_id = body.request_id
    otp = body.otp

    result = auth_mgr.verify_otp(request_id, otp, ip)

    if isinstance(result, Session):
        # Success — set cookie and return session info
        response = JSONResponse(content={
            "status": "ok",
            "session_token": result.session_token,
            "display_name": result.display_name,
            "color": result.color,
            "user_id": result.user_id,
        })
        response.set_cookie(
            key="session_token",
            value=result.session_token,
            httponly=False,  # JS needs to read for WebSocket URL
            samesite="lax",
        )
        return response
    else:
        # Failure — return error info
        status_code = 403 if result.get("status") == "locked_out" else 400
        return JSONResponse(status_code=status_code, content=result)


@app.post("/auth/disconnect", tags=["auth"], summary="Disconnect a guest session (host only)")
async def auth_disconnect(body: AuthDisconnectBody, request: Request):
    ip = _get_client_ip(request)
    auth_mgr = get_auth_manager()

    if not auth_mgr.is_host(ip):
        raise HTTPException(status_code=403, detail="Host only")

    user_id = body.user_id

    if auth_mgr.disconnect_session(user_id):
        return {"status": "disconnected", "user_id": user_id}
    raise HTTPException(status_code=404, detail="Session not found")


@app.get("/auth/sessions", tags=["auth"], summary="List active guest sessions (host only)")
async def auth_sessions(request: Request):
    ip = _get_client_ip(request)
    auth_mgr = get_auth_manager()

    if not auth_mgr.is_host(ip):
        raise HTTPException(status_code=403, detail="Host only")

    return auth_mgr.get_active_sessions()


# ─── Sheet Endpoints ───────────────────────────────────────────────


@app.get("/api/sheets", tags=["sheets"], summary="List all sheets")
async def api_list_sheets():
    config = get_config()
    sheets = sm_list_sheets(config.data_dir)
    protected = set(config.protected_sheets)
    for s in sheets:
        s["protected"] = s["name"] in protected
    return sheets


@app.post("/api/sheets/create", tags=["sheets"], summary="Create a new empty sheet")
async def api_create_sheet(body: CreateSheetBody):
    config = get_config()
    name = body.name.strip()
    columns = body.columns

    if not name or len(name) < 1 or len(name) > 50:
        raise HTTPException(status_code=400, detail="Sheet name must be 1-50 characters")
    # Sanitize name
    import re
    if not re.match(r'^[\w\- ]+$', name):
        raise HTTPException(status_code=400, detail="Sheet name can only contain letters, numbers, spaces, hyphens, underscores")

    try:
        result = sm_create_sheet(config.data_dir, name, int(columns))
        return result
    except FileExistsError:
        raise HTTPException(status_code=409, detail=f"Sheet '{name}' already exists")


@app.get("/api/sheet/{name}", tags=["sheets"], summary="Load sheet data with evaluated formulas")
async def api_get_sheet(name: str):
    config = get_config()
    try:
        return sm_read_sheet(config.data_dir, name)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Sheet '{name}' not found")


@app.patch("/api/sheet/{name}/cell", tags=["cells"], summary="Update a single cell value or formula")
async def api_update_cell(name: str, body: UpdateCellBody, request: Request):
    config = get_config()
    row = body.row
    col = body.col
    value = body.value

    # Get session info for broadcast
    session_token = request.cookies.get("session_token", "")
    session = getattr(request.state, "session", None)
    user_id = session.user_id if session else "host"

    try:
        result = await sm_update_cell(config.data_dir, name, int(row), int(col), str(value))

        # Broadcast cell update to other clients
        sync_mgr = get_sync_manager()
        await sync_mgr.broadcast("cell_update", {
            "sheet": name,
            "row": int(row),
            "col": int(col),
            "value": str(value),
            "evaluated": result.get("evaluated", str(value)),
            "user_id": user_id,
        }, exclude_token=session_token)

        return result
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Sheet '{name}' not found")


@app.post("/api/sheet/{name}/rows", tags=["cells"], summary="Insert blank rows at a given index")
async def api_insert_rows(name: str, body: InsertRowsBody):
    config = get_config()
    index = body.index
    count = body.count

    try:
        result = await sm_insert_rows(config.data_dir, name, int(index), int(count))
        return result
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Sheet '{name}' not found")


@app.delete("/api/sheet/{name}/rows", tags=["cells"], summary="Delete rows by index")
async def api_delete_rows(name: str, body: DeleteRowsBody):
    config = get_config()
    indices = body.indices
    if not indices:
        raise HTTPException(status_code=400, detail="indices array is required")

    try:
        result = await sm_delete_rows(config.data_dir, name, [int(i) for i in indices])
        return result
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Sheet '{name}' not found")


# ─── Undo / Redo / Export ──────────────────────────────────────────


@app.post("/api/sheet/{name}/undo", tags=["cells"], summary="Undo the last change on this sheet")
async def api_undo(name: str):
    config = get_config()
    result = await sm_undo(config.data_dir, name)
    if result is None:
        return {"action": "undo", "changes": None}
    return result


@app.post("/api/sheet/{name}/redo", tags=["cells"], summary="Redo the last undone change")
async def api_redo(name: str):
    config = get_config()
    result = await sm_redo(config.data_dir, name)
    if result is None:
        return {"action": "redo", "changes": None}
    return result


@app.get("/api/sheet/{name}/export", tags=["sheets"], summary="Download sheet as CSV")
async def api_export(name: str):
    config = get_config()
    filepath = config.data_dir / f"{name}.csv"
    if not filepath.exists():
        raise HTTPException(status_code=404, detail=f"Sheet '{name}' not found")
    return FileResponse(
        path=str(filepath),
        filename=f"{name}.csv",
        media_type="text/csv",
    )


# ─── Cell Formatting / Meta Endpoints ──────────────────────────────


@app.get("/api/sheet/{name}/meta", tags=["cells"], summary="Get cell formatting and header aliases")
async def api_get_meta(name: str):
    config = get_config()
    filepath = config.data_dir / f"{name}.csv"
    if not filepath.exists():
        raise HTTPException(status_code=404, detail=f"Sheet '{name}' not found")
    return sm_read_meta(config.data_dir, name)


@app.patch("/api/sheet/{name}/format", tags=["cells"], summary="Set cell formatting (bold, italic, colours)")
async def api_update_format(name: str, body: UpdateFormatBody):
    config = get_config()
    return sm_update_cell_format(config.data_dir, name, body.row, body.col, body.format)


# ─── AI Endpoints ─────────────────────────────────────────────────


@app.post("/api/ai/query", tags=["ai"], summary="Stream Q&A answer as Server-Sent Events")
async def api_ai_query(body: AIQueryBody):
    config = get_config()
    ai = get_ai_engine()
    if not ai:
        raise HTTPException(status_code=503, detail="AI not configured — set openai_api_key in config.json or .env")

    question = body.question.strip()
    sheet_name = body.sheet
    selection = body.selection

    if not question:
        raise HTTPException(status_code=400, detail="question is required")
    if not sheet_name:
        raise HTTPException(status_code=400, detail="sheet is required")

    try:
        sheet_data = sm_read_sheet(config.data_dir, sheet_name)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Sheet '{sheet_name}' not found")

    async def sse_generator():
        try:
            async for chunk in ai.query(sheet_data, question, selection):
                yield f"data: {json.dumps({'chunk': chunk, 'done': False})}\n\n"
            yield f"data: {json.dumps({'chunk': '', 'done': True})}\n\n"
        except Exception as e:
            logger.error(f"[AI] Query error: {e}")
            yield f"data: {json.dumps({'error': str(e), 'done': True})}\n\n"

    return StreamingResponse(sse_generator(), media_type="text/event-stream")


@app.post("/api/ai/fill", tags=["ai"], summary="AI-generate values for an entire column")
async def api_ai_fill(body: AIFillBody):
    config = get_config()
    ai = get_ai_engine()
    if not ai:
        raise HTTPException(status_code=503, detail="AI not configured")

    sheet_name = body.sheet
    column_index = body.column_index
    column_name = body.column_name
    instruction = body.instruction.strip()
    target_rows = body.target_rows

    if not sheet_name or column_index is None or not instruction:
        raise HTTPException(status_code=400, detail="sheet, column_index, and instruction are required")

    try:
        sheet_data = sm_read_sheet(config.data_dir, sheet_name)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Sheet '{sheet_name}' not found")

    try:
        result = await ai.fill_column(sheet_data, int(column_index), column_name, instruction, target_rows)
        return result
    except Exception as e:
        logger.error(f"[AI] Fill error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/ai/dump", tags=["ai"], summary="Parse raw text into spreadsheet rows")
async def api_ai_dump(body: AIDumpBody):
    config = get_config()
    ai = get_ai_engine()
    if not ai:
        raise HTTPException(status_code=503, detail="AI not configured")

    sheet_name = body.sheet
    raw_text = body.raw_text.strip()

    if not sheet_name or not raw_text:
        raise HTTPException(status_code=400, detail="sheet and raw_text are required")

    try:
        sheet_data = sm_read_sheet(config.data_dir, sheet_name)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Sheet '{sheet_name}' not found")

    try:
        result = await ai.parse_dump(sheet_data, raw_text)
        return result
    except Exception as e:
        logger.error(f"[AI] Dump error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/ai/formula", tags=["ai"], summary="Generate a formula from a plain-English description")
async def api_ai_formula(body: AIFormulaBody):
    config = get_config()
    ai = get_ai_engine()
    if not ai:
        raise HTTPException(status_code=503, detail="AI not configured")

    sheet_name = body.sheet
    description = body.description.strip()
    target_cell = body.target_cell

    if not sheet_name or not description or not target_cell:
        raise HTTPException(status_code=400, detail="sheet, description, and target_cell are required")

    try:
        sheet_data = sm_read_sheet(config.data_dir, sheet_name)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Sheet '{sheet_name}' not found")

    try:
        result = await ai.generate_formula(sheet_data, description, target_cell)
        return result
    except Exception as e:
        logger.error(f"[AI] Formula error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/ai/edit", tags=["ai"], summary="Edit the sheet via AI tool use (returns preview for confirmation)")
async def api_ai_edit(body: AIEditBody):
    config = get_config()
    ai = get_ai_engine()
    if not ai:
        raise HTTPException(status_code=503, detail="AI not configured — add openai_api_key in settings")
    sheet = body.sheet
    instruction = body.instruction
    if not sheet or not instruction:
        raise HTTPException(status_code=400, detail="sheet and instruction are required")
    try:
        sheet_data = sm_read_sheet(config.data_dir, sheet)
        result = await ai.edit_sheet(sheet_data, instruction)
        return result
    except Exception as e:
        logger.error(f"[AI] Edit error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/ai/confirm", tags=["ai"], summary="Commit or cancel a pending AI change")
async def api_ai_confirm(body: AIConfirmBody, request: Request):
    config = get_config()
    confirm_id = body.confirm_id
    sheet_name = body.sheet

    if not confirm_id or not sheet_name:
        raise HTTPException(status_code=400, detail="confirm_id and sheet are required")

    ai = get_ai_engine()
    if not ai:
        raise HTTPException(status_code=503, detail="AI not configured")
    pending = ai.get_pending_result(confirm_id)
    if not pending:
        raise HTTPException(status_code=404, detail="No pending result for this confirm_id")

    # Create backup
    try:
        backup_path = ai.create_backup(config.data_dir, sheet_name)
    except Exception as e:
        logger.error(f"[AI] Backup error: {e}")
        raise HTTPException(status_code=500, detail=f"Backup failed: {e}")

    sync_mgr = get_sync_manager()
    session_token = request.cookies.get("session_token", "")

    try:
        if pending["type"] == "fill":
            for fill in pending["fills"]:
                await sm_update_cell(config.data_dir, sheet_name, fill["row"], fill["col"], fill["new_value"])
                await sync_mgr.broadcast("cell_update", {
                    "sheet": sheet_name,
                    "row": fill["row"],
                    "col": fill["col"],
                    "value": fill["new_value"],
                    "evaluated": fill["new_value"],
                    "user_id": "ai",
                }, exclude_token=session_token)

        elif pending["type"] == "dump":
            sheet_data = sm_read_sheet(config.data_dir, sheet_name)
            start_row = len(sheet_data["rows"])
            # Insert rows and fill them
            row_count = len(pending["rows"])
            if row_count > 0:
                await sm_insert_rows(config.data_dir, sheet_name, start_row, row_count)
                for i, row_data in enumerate(pending["rows"]):
                    for col_idx, value in enumerate(row_data):
                        await sm_update_cell(config.data_dir, sheet_name, start_row + i, col_idx, str(value))
                await sync_mgr.broadcast("sheet_reload", {"sheet": sheet_name}, exclude_token=session_token)

        elif pending["type"] == "formula":
            # Parse target_cell to row/col
            cell_ref = pending["target_cell"]
            col_str = ""
            row_str = ""
            for ch in cell_ref:
                if ch.isalpha():
                    col_str += ch
                else:
                    row_str += ch
            col = 0
            for ch in col_str.upper():
                col = col * 26 + (ord(ch) - ord('A') + 1)
            col -= 1  # 0-based
            row = int(row_str) - 2  # Excel row to DataFrame index (row 1 = header)

            result = await sm_update_cell(config.data_dir, sheet_name, row, col, pending["formula"])
            await sync_mgr.broadcast("cell_update", {
                "sheet": sheet_name,
                "row": row,
                "col": col,
                "value": pending["formula"],
                "evaluated": result.get("evaluated", pending["formula"]),
                "user_id": "ai",
            }, exclude_token=session_token)

        elif pending["type"] == "edit":
            # Apply cell changes
            for ch in pending.get("cell_changes", []):
                await sm_update_cell(config.data_dir, sheet_name, ch["row"], ch["col"], ch["new_value"])
            if pending.get("cell_changes"):
                await sync_mgr.broadcast("sheet_reload", {"sheet": sheet_name}, exclude_token=session_token)

            # Create new sheets
            for ns in pending.get("new_sheets", []):
                try:
                    sm_create_sheet(config.data_dir, ns["name"], custom_headers=ns.get("headers"))
                    # Pre-populate initial rows if provided
                    initial_rows = ns.get("initial_rows", [])
                    if initial_rows:
                        for i, row_data in enumerate(initial_rows):
                            for col_idx, value in enumerate(row_data):
                                await sm_update_cell(config.data_dir, ns["name"], i, col_idx, str(value))
                    await sync_mgr.broadcast("sheet_reload", {"sheet": ns["name"]}, exclude_token=session_token)
                except FileExistsError:
                    logger.warning(f"[AI] Sheet '{ns['name']}' already exists, skipping")

            # Append new rows to current sheet
            new_rows = pending.get("new_rows", [])
            if new_rows:
                current_sheet_data = sm_read_sheet(config.data_dir, sheet_name)
                start_row = len(current_sheet_data["rows"])
                await sm_insert_rows(config.data_dir, sheet_name, start_row, len(new_rows))
                for i, row_data in enumerate(new_rows):
                    for col_idx, value in enumerate(row_data):
                        await sm_update_cell(config.data_dir, sheet_name, start_row + i, col_idx, str(value))
                await sync_mgr.broadcast("sheet_reload", {"sheet": sheet_name}, exclude_token=session_token)

        ai.remove_pending_result(confirm_id)
        return {"status": "committed", "backup": backup_path}

    except Exception as e:
        logger.error(f"[AI] Confirm error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ─── Reading Log Endpoints ─────────────────────────────────────────


@app.post("/api/reading/log", tags=["reading"], summary="Append a reading session to the Reading Log sheet")
async def api_reading_log(body: ReadingLogBody):
    from datetime import datetime, timezone

    config = get_config()
    sheet = sm_read_sheet(config.data_dir, READING_SHEET_NAME)
    headers = sheet["headers"]
    new_row_idx = sheet["row_count"]

    # Append a blank row, then patch each known column.
    await sm_insert_rows(config.data_dir, READING_SHEET_NAME, new_row_idx, 1)

    # Format: "04-May-2026 : 17:19:22" (DD-MMM-YYYY : HH:MM:SS, local time).
    now_local = datetime.now(timezone.utc).astimezone()
    formatted_date = now_local.strftime("%d-%b-%Y : %H:%M:%S")
    values = {
        "Title": body.title,
        "URL": body.url,
        "Word Count": str(body.word_count),
        "Time (s)": str(body.time_seconds),
        "WPM": f"{body.wpm:.2f}",
        "Date": formatted_date,
    }

    for col_name, val in values.items():
        if col_name in headers:
            await sm_update_cell(
                config.data_dir, READING_SHEET_NAME,
                new_row_idx, headers.index(col_name), val,
            )

    await get_sync_manager().broadcast("sheet_reload", {"sheet": READING_SHEET_NAME})

    return {"row": new_row_idx, "date": formatted_date}


@app.get("/api/reading/check", tags=["reading"], summary="Check if an article was already logged")
async def api_reading_check(query: str):
    if not query or not query.strip():
        raise HTTPException(status_code=400, detail="query is required")

    config = get_config()
    sheet = sm_read_sheet(config.data_dir, READING_SHEET_NAME)
    matches = find_matches(sheet["rows"], sheet["headers"], query)
    return {"found": len(matches) > 0, "matches": matches}


@app.post("/api/reading/wordcount", tags=["reading"], summary="Fetch a URL and return its word count")
async def api_reading_wordcount(body: ReadingWordCountBody):
    try:
        return await fetch_word_count(body.url)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"[READING] wordcount error: {e}")
        raise HTTPException(status_code=502, detail=f"Could not fetch URL: {e}")


# ─── Share Info ────────────────────────────────────────────────────


@app.get("/api/share-info", tags=["share"], summary="Get LAN URL and QR code SVG for sharing")
async def api_share_info():
    import socket
    import io
    try:
        import qrcode
        import qrcode.image.svg
    except ImportError:
        raise HTTPException(status_code=503, detail="qrcode library not installed")

    config = get_config()

    # Get LAN IP
    lan_ip = "127.0.0.1"
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        lan_ip = s.getsockname()[0]
        s.close()
    except Exception:
        pass

    lan_url = f"http://{lan_ip}:{config.port}"

    # Generate QR SVG
    factory = qrcode.image.svg.SvgImage
    qr = qrcode.make(lan_url, image_factory=factory, box_size=8, border=2)
    buf = io.BytesIO()
    qr.save(buf)
    qr_svg = buf.getvalue().decode("utf-8")

    return {"lan_url": lan_url, "qr_svg": qr_svg}


# ─── Settings ──────────────────────────────────────────────────────


@app.get("/api/settings", tags=["settings"], summary="Get current configuration")
async def api_get_settings():
    config = get_config()
    return {
        "openai_api_key": config.openai_api_key,
        "base_url": config.base_url,
        "ai_model": config.ai_model,
        "max_context_rows": config.max_context_rows,
        "undo_depth": config.undo_depth,
        "open_browser": config.open_browser,
        "desktop_notifications": config.desktop_notifications,
        "otp_expiry_seconds": config.otp_expiry_seconds,
        "require_guest_auth": config.require_guest_auth,
        "port": config.port,
    }


@app.patch("/api/settings", tags=["settings"], summary="Update configuration (live, no restart needed)")
async def api_patch_settings(body: SettingsPatchBody):
    # Build updates dict — skip None values
    updates = {k: v for k, v in body.model_dump().items() if v is not None}

    try:
        new_config = save_config(updates)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    # Re-init AI engine if key/model/base_url changed
    if any(k in updates for k in ("openai_api_key", "ai_model", "base_url", "max_context_rows")):
        if new_config.openai_api_key:
            init_ai_engine(new_config.openai_api_key, new_config.ai_model, new_config.max_context_rows, new_config.base_url)

    return {"status": "saved"}


# ─── Column / Rename / Alias Endpoints ────────────────────────────


@app.post("/api/sheet/{name}/columns", tags=["sheets"], summary="Append columns to a sheet")
async def api_add_column(name: str, body: AddColumnsBody):
    config = get_config()
    count = body.count
    try:
        result = sm_add_column(config.data_dir, name, int(count))
        sync_mgr = get_sync_manager()
        await sync_mgr.broadcast("sheet_reload", {"sheet": name})
        return result
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Sheet '{name}' not found")


@app.patch("/api/sheet/{name}/rename", tags=["sheets"], summary="Rename a sheet")
async def api_rename_sheet(name: str, body: RenameSheetBody):
    config = get_config()
    import re
    new_name = body.new_name.strip()
    if not re.match(r'^[\w\- ]+$', new_name):
        raise HTTPException(status_code=400, detail="Invalid sheet name")

    try:
        result = sm_rename_sheet(config.data_dir, name, new_name)
        sync_mgr = get_sync_manager()
        await sync_mgr.broadcast("sheet_renamed", {"old_name": name, "new_name": new_name})
        return result
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Sheet '{name}' not found")
    except FileExistsError:
        raise HTTPException(status_code=409, detail=f"Sheet '{new_name}' already exists")


@app.delete("/api/sheet/{name}", tags=["sheets"], summary="Delete a sheet (forbidden for protected sheets)")
async def api_delete_sheet(name: str):
    config = get_config()
    if name in config.protected_sheets:
        raise HTTPException(
            status_code=403,
            detail=f"Sheet '{name}' is protected and cannot be deleted through the UI. "
                   "Remove the file directly from the data/ folder to delete it."
        )
    sheets = sm_list_sheets(config.data_dir)
    if len(sheets) <= 1:
        raise HTTPException(status_code=400, detail="Cannot delete the last remaining sheet.")
    try:
        result = sm_delete_sheet(config.data_dir, name)
        sync_mgr = get_sync_manager()
        await sync_mgr.broadcast("sheet_deleted", {"name": name})
        return result
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Sheet '{name}' not found")


@app.patch("/api/sheet/{name}/protect", tags=["sheets"], summary="Toggle sheet protection (prevent UI deletion)")
async def api_protect_sheet(name: str):
    config = get_config()
    protected = list(config.protected_sheets)
    if name in protected:
        protected.remove(name)
        now_protected = False
    else:
        protected.append(name)
        now_protected = True
    save_config({"protected_sheets": protected})
    sync_mgr = get_sync_manager()
    await sync_mgr.broadcast("sheet_protected", {"name": name, "protected": now_protected})
    return {"name": name, "protected": now_protected}


@app.patch("/api/sheet/{name}/alias", tags=["cells"], summary="Set a display alias for a column or row header")
async def api_update_alias(name: str, body: UpdateAliasBody):
    config = get_config()
    axis = body.axis
    index = body.index
    label = body.label

    if axis not in ("col", "row") or index is None:
        raise HTTPException(status_code=400, detail="axis (col/row) and index are required")

    try:
        result = sm_update_header_alias(config.data_dir, name, axis, int(index), label)
        return result
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Sheet '{name}' not found")


# ─── WebSocket Endpoint ────────────────────────────────────────────


@app.websocket("/ws/{session_token}")  # tags=["realtime"] — WebSocket endpoints are not tagged in OpenAPI
async def websocket_endpoint(websocket: WebSocket, session_token: str):
    auth_mgr = get_auth_manager()
    sync_mgr = get_sync_manager()
    config = get_config()

    # Validate session (or accept host)
    ip = websocket.client.host if websocket.client else "127.0.0.1"
    is_host = auth_mgr.is_host(ip)

    if is_host and not auth_mgr.validate_session(session_token):
        # Auto-create host session
        session = auth_mgr.create_host_session(ip)
        session_token = session.session_token
    elif not config.require_guest_auth and not auth_mgr.validate_session(session_token):
        # Open LAN mode — auto-create a guest session
        session = auth_mgr.create_open_session(ip, session_token)
        session_token = session.session_token
    else:
        session = auth_mgr.validate_session(session_token)

    if not session and not is_host:
        await websocket.close(code=4001, reason="Invalid session")
        return

    user_id = session.user_id if session else "host"
    display_name = session.display_name if session else "Host"
    color = session.color if session else "#6c8cff"

    client = await sync_mgr.connect(
        websocket, session_token, user_id, display_name, color, is_host
    )

    try:
        while True:
            data = await websocket.receive_json()
            event = data.get("event", "")
            payload = data.get("data", {})

            if event == "cell_lock":
                sheet = payload.get("sheet", "")
                row = payload.get("row", 0)
                col = payload.get("col", 0)
                if sync_mgr.lock_cell(sheet, row, col, user_id):
                    await sync_mgr.broadcast("cell_lock", {
                        "sheet": sheet,
                        "row": row,
                        "col": col,
                        "user_id": user_id,
                        "color": color,
                        "display_name": display_name,
                    }, exclude_token=session_token)

            elif event == "cell_unlock":
                sheet = payload.get("sheet", "")
                row = payload.get("row", 0)
                col = payload.get("col", 0)
                if sync_mgr.unlock_cell(sheet, row, col, user_id):
                    await sync_mgr.broadcast("cell_unlock", {
                        "sheet": sheet,
                        "row": row,
                        "col": col,
                        "user_id": user_id,
                    }, exclude_token=session_token)

    except WebSocketDisconnect:
        await sync_mgr.disconnect(session_token)
    except Exception as e:
        logger.error(f"[WS] Error: {e}")
        await sync_mgr.disconnect(session_token)


# ─── Static File Serving (must be LAST) ────────────────────────────

import hashlib
import subprocess


_frontend_dir = Path(__file__).resolve().parent.parent / "frontend"


def _asset_hash(filename: str) -> str:
    """SHA-1 (first 8 chars) of a frontend file. Used as a cache-busting
    query string so the browser is forced to re-fetch (and re-parse the
    ES module) whenever the file content changes. Re-computed per request
    so edits-while-running show up immediately."""
    p = _frontend_dir / filename
    try:
        return hashlib.sha1(p.read_bytes()).hexdigest()[:8]
    except FileNotFoundError:
        return "missing"


def _git_short_commit() -> str:
    """Return short commit SHA, or 'dev' if not in a git checkout."""
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=str(_frontend_dir.parent),
            stderr=subprocess.DEVNULL,
        )
        return out.decode().strip()
    except Exception:
        return "dev"


_FRONTEND_ASSETS = ["grid.js", "style.css", "ai_panel.js", "auth.js"]


@app.get("/api/build-info", tags=["share"], summary="Frontend build hashes for stale-tab detection")
async def api_build_info():
    """Returns the current SHA-1 of every frontend asset plus the git
    commit. The web UI polls this every 30 s to detect when a tab is
    running stale code and prompt for a reload."""
    return {
        "commit": _git_short_commit(),
        "asset_hashes": {name: _asset_hash(name) for name in _FRONTEND_ASSETS},
    }


def _serve_rewritten_index() -> "Response":
    """Read index.html from disk and rewrite `<script src="/grid.js">` (etc.)
    to `<script src="/grid.js?v=<sha>">`. Each unique content gets a unique
    URL, which forces the browser to discard its parsed-module cache and
    re-fetch on every change. HTTP `Cache-Control: no-cache` alone is NOT
    enough — V8 / JavaScriptCore keep parsed module bytecode keyed by URL
    until the URL itself changes."""
    from starlette.responses import Response as _Resp
    html = (_frontend_dir / "index.html").read_text(encoding="utf-8")
    for name in _FRONTEND_ASSETS:
        h = _asset_hash(name)
        html = html.replace(f'src="/{name}"', f'src="/{name}?v={h}"')
        html = html.replace(f'href="/{name}"', f'href="/{name}?v={h}"')
        # ES-module imports use the same URL form
        html = html.replace(f"from '/{name}'", f"from '/{name}?v={h}'")
    return _Resp(
        content=html,
        media_type="text/html",
        headers={"Cache-Control": "no-cache, must-revalidate"},
    )


# Explicit GET / and GET /index.html so the rewrite ALWAYS runs, regardless
# of starlette's internal html=True path resolution.
@app.get("/", include_in_schema=False)
async def root_index():
    return _serve_rewritten_index()


@app.get("/index.html", include_in_schema=False)
async def explicit_index():
    return _serve_rewritten_index()


class NoCacheStaticFiles(StaticFiles):
    """StaticFiles that forces revalidation on every static asset response."""

    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache, must-revalidate"
        return response


app.mount("/", NoCacheStaticFiles(directory=str(_frontend_dir), html=True), name="frontend")
