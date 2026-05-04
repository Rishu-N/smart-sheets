"""Reading Log helpers — sheet bootstrap, URL normalization, dedupe matching, word-count fetch."""

import logging
import re
import string
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx
from bs4 import BeautifulSoup

from backend.sheet_manager import create_sheet as sm_create_sheet

logger = logging.getLogger("smartsheet.reading")


READING_SHEET_NAME = "Reading Log"
READING_HEADERS = ["Title", "URL", "Word Count", "Time (s)", "WPM", "Date"]
TITLE_MATCH_THRESHOLD = 0.85

_TRACKING_PARAMS = {"gclid", "fbclid", "ref", "ref_src", "mc_cid", "mc_eid"}
_MAX_HTML_BYTES = 5 * 1024 * 1024  # 5 MB


def ensure_reading_sheet(data_dir: Path) -> None:
    """Create the Reading Log sheet on first run. Idempotent."""
    csv_path = data_dir / f"{READING_SHEET_NAME}.csv"
    if csv_path.exists():
        return
    try:
        sm_create_sheet(data_dir, READING_SHEET_NAME, custom_headers=READING_HEADERS)
        logger.info(f"[READING] Bootstrapped sheet: {READING_SHEET_NAME}")
    except FileExistsError:
        # Race or stale state — fine.
        pass


def normalize_url(url: str) -> str:
    """Lowercase scheme/host, drop fragment + tracking params, drop trailing slash, sort params."""
    if not url:
        return ""
    url = url.strip()
    try:
        parts = urlsplit(url)
    except ValueError:
        return url.lower()

    if not parts.scheme:
        return url.strip().lower()

    scheme = parts.scheme.lower()
    netloc = parts.netloc.lower()
    # Strip default ports
    if netloc.endswith(":80") and scheme == "http":
        netloc = netloc[:-3]
    elif netloc.endswith(":443") and scheme == "https":
        netloc = netloc[:-4]

    path = parts.path or ""
    if path == "/":
        path = ""
    elif path.endswith("/"):
        path = path.rstrip("/")

    # Filter and sort query params
    kept = [
        (k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if not k.lower().startswith("utm_") and k.lower() not in _TRACKING_PARAMS
    ]
    kept.sort(key=lambda kv: kv[0])
    query = urlencode(kept)

    return urlunsplit((scheme, netloc, path, query, ""))


def _norm_title(text: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace."""
    text = text.lower()
    text = text.translate(str.maketrans("", "", string.punctuation))
    text = re.sub(r"\s+", " ", text).strip()
    return text


def title_similarity(a: str, b: str) -> float:
    """Fuzzy similarity (0..1) between two titles."""
    na, nb = _norm_title(a), _norm_title(b)
    if not na or not nb:
        return 0.0
    return SequenceMatcher(None, na, nb).ratio()


def _looks_like_url(query: str) -> bool:
    q = query.strip().lower()
    if "://" in q:
        return True
    if q.startswith("www."):
        return True
    # Naive TLD-ish heuristic: contains a dot and no spaces
    if "." in q and " " not in q and len(q) > 3:
        return True
    return False


def find_matches(rows: list[list[Any]], headers: list[str], query: str) -> list[dict]:
    """Return matching log rows. URL exact (normalized) OR title fuzzy >= threshold."""
    query = (query or "").strip()
    if not query:
        return []

    def col_idx(name: str) -> int:
        return headers.index(name) if name in headers else -1

    title_i = col_idx("Title")
    url_i = col_idx("URL")
    date_i = col_idx("Date")
    wpm_i = col_idx("WPM")
    wc_i = col_idx("Word Count")
    ts_i = col_idx("Time (s)")

    def cell(row: list, i: int) -> str:
        return str(row[i]) if 0 <= i < len(row) else ""

    is_url_query = _looks_like_url(query)
    target_url = normalize_url(query) if is_url_query else ""

    matches: list[dict] = []
    for r_idx, row in enumerate(rows):
        title = cell(row, title_i)
        row_url = cell(row, url_i)
        date_v = cell(row, date_i)
        wpm_v = cell(row, wpm_i)
        wc_v = cell(row, wc_i)
        ts_v = cell(row, ts_i)

        # Skip blank rows (no title and no url)
        if not title.strip() and not row_url.strip():
            continue

        score = 0.0
        matched = False

        if is_url_query and row_url:
            if normalize_url(row_url) == target_url:
                score = 1.0
                matched = True

        if not matched and title:
            sim = title_similarity(query, title)
            if sim >= TITLE_MATCH_THRESHOLD:
                score = sim
                matched = True

        if matched:
            matches.append({
                "row": r_idx,
                "title": title,
                "url": row_url,
                "date": date_v,
                "wpm": wpm_v,
                "word_count": wc_v,
                "time_seconds": ts_v,
                "score": round(score, 3),
            })

    matches.sort(key=lambda m: m["score"], reverse=True)
    return matches


async def fetch_word_count(url: str, timeout: float = 10.0) -> dict:
    """Fetch URL, extract readable text, return word count + page title.

    Some CDNs (notably Akamai) refuse browser-shaped User-Agents and 403 us;
    others reject obviously-non-browser UAs. We try a small ladder of UAs and
    return the first 2xx response.
    """
    if not url or not url.strip():
        raise ValueError("URL is required")
    parts = urlsplit(url.strip())
    if parts.scheme not in ("http", "https"):
        raise ValueError("Only http(s) URLs are supported")

    ua_ladder = [
        # Default — readable, identifies us. Works for most sites.
        "ReadingTracker/1.0 (+local)",
        # Akamai-friendly: curl-style UAs are categorised as "tools" and
        # bypass the bot challenge that 403s browser-shaped UAs.
        "curl/8.7.1",
        # Modern desktop Chrome — last resort for sites that reject anything
        # not browser-shaped.
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    ]

    last_error: Exception | None = None
    resp = None
    async with httpx.AsyncClient(follow_redirects=True, timeout=timeout) as client:
        for ua in ua_ladder:
            headers = {
                "User-Agent": ua,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
            }
            try:
                r = await client.get(url, headers=headers)
            except httpx.HTTPError as e:
                last_error = e
                continue
            if r.status_code < 400:
                resp = r
                break
            # 401/403/406/429/451 ⇒ try the next UA. Any other 4xx/5xx ⇒ stop.
            if r.status_code in (401, 403, 406, 429, 451):
                last_error = httpx.HTTPStatusError(
                    f"{r.status_code} from {url} with UA={ua!r}",
                    request=r.request, response=r,
                )
                continue
            r.raise_for_status()
            resp = r
            break

        if resp is None:
            if isinstance(last_error, httpx.HTTPStatusError):
                code = last_error.response.status_code
                raise ValueError(
                    f"Site blocked the fetch (HTTP {code}). The page may require JavaScript "
                    f"or a real browser session — open it in your browser and enter the word "
                    f"count manually."
                )
            raise ValueError(f"Could not reach URL: {last_error}")

        ctype = resp.headers.get("content-type", "").lower()
        if "html" not in ctype and "xml" not in ctype:
            raise ValueError(f"Unsupported content-type: {ctype or 'unknown'}")

        # Cap response size
        content = resp.content
        if len(content) > _MAX_HTML_BYTES:
            content = content[:_MAX_HTML_BYTES]

        try:
            html = content.decode(resp.encoding or "utf-8", errors="replace")
        except (LookupError, TypeError):
            html = content.decode("utf-8", errors="replace")

    soup = BeautifulSoup(html, "html.parser")

    # Strip non-content tags
    for tag in soup(["script", "style", "noscript", "nav", "footer", "header", "aside", "form", "iframe"]):
        tag.decompose()

    # Prefer <article> or <main> if present
    main_node = soup.find("article") or soup.find("main") or soup.body or soup
    text = main_node.get_text(" ", strip=True) if main_node else ""

    tokens = re.findall(r"\b[\w'\-]+\b", text)
    word_count = len(tokens)

    title = None
    if soup.title and soup.title.string:
        title = soup.title.string.strip() or None

    return {"url": url, "word_count": word_count, "title": title}
