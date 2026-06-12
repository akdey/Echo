"""
scraper_utils.py
================
curl-cffi powered NSE scraping utilities.

Replaces the entire Playwright dependency for data collection:
- FII/DII institutional flows  →  NSE internal JSON API
- ASM / GSM / T2T lists        →  NSE archive CSV downloads
- General NSE JSON endpoints   →  curl-cffi Chrome-impersonation session

Why curl-cffi instead of Playwright:
  Playwright launches a full Chromium browser (~200-400 MB RAM) which causes
  OOM crashes on Hugging Face Spaces free tier.  curl-cffi impersonates the
  Chrome TLS/JA3 fingerprint at the TCP handshake level (zero extra RAM),
  bypassing Cloudflare WAF while running as fast as a normal `requests` call.
"""

import asyncio
import csv
import io
import logging
import datetime
import re
from typing import Dict, Any, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ── curl-cffi availability guard ──────────────────────────────────────────────
try:
    from curl_cffi import requests as cf_requests
    HAS_CURL_CFFI = True
    logger.info("[Scraper] curl-cffi available — NSE Chrome impersonation enabled.")
except ImportError:
    import requests as cf_requests          # fallback to plain requests
    HAS_CURL_CFFI = False
    logger.warning(
        "[Scraper] curl-cffi not installed. Falling back to standard requests "
        "(Cloudflare bypass disabled). Install with: pip install curl-cffi"
    )

# ── NSE base URLs ─────────────────────────────────────────────────────────────
NSE_HOME   = "https://www.nseindia.com"
NSE_API    = f"{NSE_HOME}/api"

# Shared browser headers (mimic a real Chrome visit)
_CHROME_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept":          "application/json, text/html, */*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer":         "https://www.nseindia.com/",
    "DNT":             "1",
    "Connection":      "keep-alive",
}


# ══════════════════════════════════════════════════════════════════════════════
# Session factory
# ══════════════════════════════════════════════════════════════════════════════

def _make_session() -> Any:
    """
    Creates a curl-cffi session impersonating Chrome 125 (or plain requests).
    A brief GET to the NSE homepage seeds the session with required cookies.
    """
    if HAS_CURL_CFFI:
        session = cf_requests.Session(impersonate="chrome125")
    else:
        import requests
        session = requests.Session()

    session.headers.update(_CHROME_HEADERS)

    # Seed cookies — NSE requires this before hitting internal APIs
    try:
        session.get(NSE_HOME, timeout=8)
    except Exception as e:
        logger.debug("[Scraper] NSE homepage seed warning (ignored): %s", e)

    return session


def _get_nse_session() -> Any:
    """Synchronous session factory (called from run_in_executor)."""
    return _make_session()


# ══════════════════════════════════════════════════════════════════════════════
# FII / DII Institutional Flow Scraper
# ══════════════════════════════════════════════════════════════════════════════

def _fetch_fii_dii_sync() -> Dict[str, Any]:
    """
    Hits NSE's internal FII/DII JSON API directly — no HTML table parsing,
    no Playwright, no fragile column index guessing.

    NSE endpoint: /api/fiidiiTradeReact
    Returns a list of rows for the last few trading days.  We take the most
    recent (today's or last available) row for FII and DII categories.
    """
    session = _make_session()
    url = f"{NSE_API}/fiidiiTradeReact"

    try:
        resp = session.get(url, timeout=12)
        if resp.status_code != 200:
            logger.warning("[FII/DII] NSE API returned HTTP %d", resp.status_code)
            return {}

        data = resp.json()
        if not isinstance(data, list) or not data:
            logger.warning("[FII/DII] Unexpected response structure from NSE.")
            return {}

        # The API returns rows grouped by date then category.
        # Build a lookup: {date: {category: row}}
        by_date: Dict[str, Dict[str, Any]] = {}
        for row in data:
            date_key = row.get("date", "")
            cat      = row.get("category", "").upper()
            if date_key not in by_date:
                by_date[date_key] = {}
            by_date[date_key][cat] = row

        # Pick the most recent date that has both FII/FPI and DII rows
        fii_row: Optional[Dict] = None
        dii_row: Optional[Dict] = None
        latest_date = ""

        for date_str in sorted(by_date.keys(), reverse=True):
            cats = by_date[date_str]
            fii_candidate = cats.get("FII/FPI") or cats.get("FII") or cats.get("FPI")
            dii_candidate = cats.get("DII")
            if fii_candidate and dii_candidate:
                fii_row    = fii_candidate
                dii_row    = dii_candidate
                latest_date = date_str
                break

        if not fii_row or not dii_row:
            logger.warning("[FII/DII] Could not find complete FII+DII row in NSE data.")
            return {}

        def _parse(v: Any) -> float:
            """Parse crore values that may be string or float."""
            try:
                return float(str(v).replace(",", "").strip())
            except (ValueError, TypeError):
                return 0.0

        # NSE API key names vary — try multiple known names
        fii_net = _parse(fii_row.get("netValue") or fii_row.get("net") or
                         fii_row.get("netPurchasesSales") or 0)
        dii_net = _parse(dii_row.get("netValue") or dii_row.get("net") or
                         dii_row.get("netPurchasesSales") or 0)

        logger.info(
            "[FII/DII] NSE API — date=%s | FII=%.2f Cr | DII=%.2f Cr",
            latest_date, fii_net, dii_net
        )
        return {
            "timestamp":      datetime.datetime.now().isoformat(),
            "fii_net_crores": fii_net,
            "dii_net_crores": dii_net,
            "rolling_5d_fii": fii_net,       # updated by caller from history
            "rolling_5d_dii": dii_net,
            "market_state":   "Net Accumulation" if (fii_net + dii_net) > 0 else "Net Distribution",
            "source":         "NSE-API (curl-cffi)",
            "date":           latest_date,
        }

    except Exception as e:
        logger.error("[FII/DII] NSE API fetch failed: %s", e)
        return {}


async def fetch_fii_dii_flows() -> Dict[str, Any]:
    """Async wrapper — runs synchronous NSE API call in thread executor."""
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, _fetch_fii_dii_sync)
    return result


# ══════════════════════════════════════════════════════════════════════════════
# ASM / GSM / T2T Surveillance List Scraper
# ══════════════════════════════════════════════════════════════════════════════

def _fetch_asm_csv_sync() -> List[str]:
    """
    Downloads the NSE Additional Surveillance Measure (ASM) short-term list.
    Tries the archive CSV URL pattern (most reliable), then the API endpoint.
    Returns list of NSE bare symbols (no .NS suffix).
    """
    # NSE publishes this as a dated CSV — try last 3 business days
    symbols: List[str] = []
    session = _make_session()

    target_date = datetime.date.today()
    for _ in range(5):
        date_str = target_date.strftime("%Y%m%d")
        url = f"https://archives.nseindia.com/surveillance/ann/asm_securities_{date_str}.csv"
        try:
            resp = session.get(url, timeout=12)
            if resp.status_code == 200 and len(resp.text) > 100 and "<html" not in resp.text[:80].lower():
                reader = csv.reader(io.StringIO(resp.text))
                next(reader, None)  # skip header
                for row in reader:
                    if row:
                        sym = row[0].strip().upper()
                        if sym and sym.isalnum():
                            symbols.append(sym)
                logger.info("[ASM] Downloaded %d symbols from archive %s", len(symbols), date_str)
                return symbols
        except Exception as e:
            logger.debug("[ASM] Archive not found for %s: %s", date_str, e)
        target_date -= datetime.timedelta(days=1)

    # Fallback: NSE internal API
    try:
        resp = session.get(f"{NSE_API}/additional-surveillance-measure", timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            if isinstance(data, dict):
                data = data.get("data") or data.get("ASM_securities") or []
            for item in (data or []):
                sym = (item.get("symbol") or item.get("SYMBOL") or "").strip().upper()
                if sym:
                    symbols.append(sym)
            logger.info("[ASM] NSE API fallback returned %d symbols.", len(symbols))
    except Exception as e:
        logger.warning("[ASM] NSE API fallback also failed: %s", e)

    return symbols


def _fetch_gsm_csv_sync() -> List[str]:
    """
    Downloads NSE Graded Surveillance Measure (GSM) list.
    Returns list of NSE bare symbols (no .NS suffix).
    """
    symbols: List[str] = []
    session = _make_session()

    target_date = datetime.date.today()
    for _ in range(5):
        date_str = target_date.strftime("%Y%m%d")
        url = f"https://archives.nseindia.com/surveillance/ann/gsm_securities_{date_str}.csv"
        try:
            resp = session.get(url, timeout=12)
            if resp.status_code == 200 and len(resp.text) > 100 and "<html" not in resp.text[:80].lower():
                reader = csv.reader(io.StringIO(resp.text))
                next(reader, None)
                for row in reader:
                    if row:
                        sym = row[0].strip().upper()
                        if sym and sym.isalnum():
                            symbols.append(sym)
                logger.info("[GSM] Downloaded %d symbols from archive %s", len(symbols), date_str)
                return symbols
        except Exception as e:
            logger.debug("[GSM] Archive not found for %s: %s", date_str, e)
        target_date -= datetime.timedelta(days=1)

    # Fallback: NSE API
    try:
        resp = session.get(f"{NSE_API}/graded-surveillance-measure", timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            if isinstance(data, dict):
                data = data.get("data") or data.get("GSM_securities") or []
            for item in (data or []):
                sym = (item.get("symbol") or item.get("SYMBOL") or "").strip().upper()
                if sym:
                    symbols.append(sym)
            logger.info("[GSM] NSE API fallback returned %d symbols.", len(symbols))
    except Exception as e:
        logger.warning("[GSM] NSE API fallback failed: %s", e)

    return symbols


async def fetch_surveillance_lists() -> Dict[str, List[str]]:
    """
    Async wrapper that concurrently downloads ASM and GSM lists.
    Returns: {"asm": [...], "gsm": [...], "t2t": []}
    """
    loop = asyncio.get_event_loop()
    asm_symbols, gsm_symbols = await asyncio.gather(
        loop.run_in_executor(None, _fetch_asm_csv_sync),
        loop.run_in_executor(None, _fetch_gsm_csv_sync),
    )

    return {
        "asm": list(set(asm_symbols)),
        "gsm": list(set(gsm_symbols)),
        "t2t": [],  # T2T is a trading restriction, not a separate downloadable list
    }


# ══════════════════════════════════════════════════════════════════════════════
# General-purpose NSE JSON API helper
# ══════════════════════════════════════════════════════════════════════════════

async def fetch_nse_json(endpoint_path: str, params: Optional[Dict] = None) -> Any:
    """
    Fetches any NSE internal JSON API endpoint using a seeded curl-cffi session.

    Args:
        endpoint_path: Path after /api/  (e.g. "equity-stockIndices?index=NIFTY+50")
        params: Optional query parameters dict.

    Returns:
        Parsed JSON response (dict or list), or None on failure.
    """
    url = f"{NSE_API}/{endpoint_path.lstrip('/')}"

    def _sync():
        session = _make_session()
        try:
            resp = session.get(url, params=params, timeout=12)
            if resp.status_code == 200:
                return resp.json()
        except Exception as e:
            logger.error("[NSE-JSON] %s failed: %s", url, e)
        return None

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _sync)
