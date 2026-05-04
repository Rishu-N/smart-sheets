"""Configuration loader for SmartSheet."""

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path


def _load_dotenv(root: Path) -> None:
    """Load .env file from root or backend/ directory into os.environ."""
    for candidate in [root / ".env", root / "backend" / ".env"]:
        if candidate.exists():
            with open(candidate) as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, _, val = line.partition("=")
                    os.environ.setdefault(key.strip(), val.strip())
            break


@dataclass
class Config:
    openai_api_key: str
    port: int
    data_dir: Path
    open_browser: bool
    otp_expiry_seconds: int
    otp_max_attempts: int
    otp_lockout_seconds: int
    desktop_notifications: bool
    undo_depth: int
    ai_model: str
    max_context_rows: int
    base_url: str
    require_guest_auth: bool
    protected_sheets: list


_config: Config | None = None
_config_path: Path | None = None


def load_config(path: str = "config.json") -> Config:
    global _config, _config_path

    config_path = Path(path)
    if not config_path.exists():
        print(f"[ERROR] Config file not found: {config_path.resolve()}")
        sys.exit(1)

    _config_path = config_path.resolve()
    root = _config_path.parent

    # Load .env so OPENAI_API_KEY etc. are available
    _load_dotenv(root)

    with open(config_path, "r", encoding="utf-8") as f:
        raw = json.load(f)

    # Resolve data_dir relative to config file location
    data_dir = (root / raw.get("data_dir", "./data")).resolve()

    # API key: prefer config.json value, fall back to env var
    api_key = (
        raw.get("openai_api_key", "")
        or raw.get("anthropic_api_key", "")   # backward compat
        or os.environ.get("OPENAI_API_KEY", "")
    )

    _config = Config(
        openai_api_key=api_key,
        port=raw.get("port", 8000),
        data_dir=data_dir,
        open_browser=raw.get("open_browser", True),
        otp_expiry_seconds=raw.get("otp_expiry_seconds", 300),
        otp_max_attempts=raw.get("otp_max_attempts", 3),
        otp_lockout_seconds=raw.get("otp_lockout_seconds", 120),
        desktop_notifications=raw.get("desktop_notifications", True),
        undo_depth=raw.get("undo_depth", 50),
        ai_model=raw.get("ai_model", "gpt-4.1"),
        max_context_rows=raw.get("max_context_rows", 200),
        base_url=raw.get("base_url", ""),
        require_guest_auth=raw.get("require_guest_auth", False),
        protected_sheets=raw.get("protected_sheets", []),
    )
    return _config


def save_config(updates: dict) -> Config:
    """Apply updates dict to config.json and return updated Config."""
    global _config, _config_path

    if _config_path is None or not _config_path.exists():
        raise RuntimeError("Config path not set — call load_config() first.")

    with open(_config_path, "r", encoding="utf-8") as f:
        raw = json.load(f)

    for k, v in updates.items():
        raw[k] = v

    with open(_config_path, "w", encoding="utf-8") as f:
        json.dump(raw, f, indent=2)

    return load_config(str(_config_path))


def get_config() -> Config:
    if _config is None:
        raise RuntimeError("Config not loaded. Call load_config() first.")
    return _config
