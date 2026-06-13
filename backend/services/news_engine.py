"""
news_engine.py
==============
Three-Tier News Ingestion Engine for Echo.

The core insight: you cannot search all 500 Nifty stocks every morning —
that burns free-tier API limits and misses the most important signals anyway.
Corporate events are disclosed to exchanges first (regulatory requirement).
The LLM's job is not to *find* news, it's to *triage* it.

──────────────────────────────────────────────────────────────────────────────
TIER 1 — Global Macro Engine (8:30 AM IST)
  Runs 7 targeted DuckDuckGo News queries covering macro themes that affect
  broad Indian market sectors.  The LLM classifies each result into a typed
  MacroSignal schema and derives sector-level boost/veto adjustments.
  Results are stored in `news_signals` and applied to conviction scoring.

  Zero API cost — uses the free `duckduckgo-search` library.

TIER 2 — Corporate Announcement Crawler (Every 4 Hours)
  Fetches the latest 50 corporate filings directly from NSE's internal
  announcements API.  Listed companies are legally required to file material
  events (order wins, earnings, FDA results) with the exchange before any
  media release.  This catches the TCS-deal scenario before Reuters does.

  The LLM triages 50 headlines in a single pass using the CorporateEvent
  Pydantic schema.  Only `is_material_catalyst = True` items trigger a
  temporary +/- Conviction Override in Supabase.

TIER 3 — Watchlist-Targeted Search (On-Demand / Nightly)
  Queries Supabase for: (a) all open journal positions and (b) all stocks
  with conviction_score >= 50.  Narrows to at most 15 symbols to stay
  within DuckDuckGo rate limits.  Runs one DDGS news query per symbol and
  extracts a directional sentiment score.
──────────────────────────────────────────────────────────────────────────────
"""

import asyncio
import logging
import datetime
import time
from typing import Dict, Any, List, Optional, Literal

from pydantic import BaseModel

from backend.services.llm_gateway import query_llm_structured
from backend.services.scraper_utils import _make_session, fetch_nse_json
from backend.services.db_handler import (
    query_db,
    upsert_db,
    IS_DB_CONFIGURED,
)

logger = logging.getLogger(__name__)

# ── DuckDuckGo search availability guard ──────────────────────────────────────
try:
    from duckduckgo_search import DDGS
    HAS_DDGS = True
    logger.info("[NewsEngine] duckduckgo-search available.")
except ImportError:
    HAS_DDGS = False
    logger.warning(
        "[NewsEngine] duckduckgo-search not installed. "
        "Install with: uv add duckduckgo-search"
    )

# ── Indian market sector taxonomy ─────────────────────────────────────────────
NSE_SECTORS = [
    "IT", "BANKING", "AUTO", "PHARMA", "OIL_GAS", "FMCG",
    "METALS", "REALTY", "INFRA", "POWER", "DEFENSE", "TELECOM",
    "CHEMICALS", "CAPITAL_GOODS", "CONSUMER_DISCRETIONARY",
]

# ── Tier 1 macro query topics ─────────────────────────────────────────────────
TIER1_MACRO_QUERIES = [
    ("US Federal Reserve interest rate decision monetary policy",   "FED_RATE"),
    ("India RBI Reserve Bank monetary policy repo rate",            "RBI_POLICY"),
    ("crude oil price OPEC geopolitical supply disruption",         "OIL_PRICE"),
    ("US dollar Indian rupee USD INR exchange rate",                "CURRENCY"),
    ("FII FPI foreign institutional investor India capital flows",  "FII_FLOW"),
    ("China economic slowdown global demand recession risk",        "GLOBAL_RISK"),
    ("India government budget infrastructure capex spending",       "INDIA_POLICY"),
]

# ── DDGS rate-limit safe delay ─────────────────────────────────────────────────
DDGS_INTER_QUERY_DELAY_SEC = 2.0   # seconds between DDGS queries
DDGS_MAX_RETRIES           = 2
TIER3_MAX_SYMBOLS          = 15    # hard cap to stay within rate limits


# ══════════════════════════════════════════════════════════════════════════════
# Pydantic Schemas
# ══════════════════════════════════════════════════════════════════════════════

class MacroSignal(BaseModel):
    """Structured output for Tier 1 macro news analysis."""
    theme:                str                       # FED_RATE | RBI_POLICY | OIL_PRICE | CURRENCY | FII_FLOW | GLOBAL_RISK | INDIA_POLICY | OTHER
    sentiment:            Literal["BULLISH", "BEARISH", "NEUTRAL"]
    magnitude:            int                       # 1 (minor) | 2 (moderate) | 3 (major)
    affected_sectors:     List[str]                 # subset of NSE_SECTORS
    conviction_adjustment: int                      # -20 to +20 (applied to each affected sector's stocks)
    one_line_summary:     str                       # ≤ 100 characters


class CorporateEvent(BaseModel):
    """
    Structured triage output for Tier 2 NSE corporate announcements.
    The LLM reads one announcement headline and classifies it.
    """
    is_material_catalyst: bool
    company_name:         str
    nse_symbol:           Optional[str] = None      # Resolved ticker (if LLM knows it)
    event_type:           Literal[
                              "Order Win",
                              "Earnings Surprise",
                              "Regulatory Issue",
                              "Merger/Acquisition",
                              "Management Change",
                              "Debt Restructuring",
                              "Regulatory Approval",
                              "Noise"
                          ]
    sentiment_shift:      Literal["Bullish", "Bearish", "Neutral"]
    conviction_override:  int           # Points to add to conviction score: -30 to +30
    one_line_reason:      str           # Why this is / isn't material


class WatchlistSentiment(BaseModel):
    """Structured output for Tier 3 watchlist-targeted search."""
    symbol:           str
    company_name:     str
    sentiment:        Literal["BULLISH", "BEARISH", "NEUTRAL"]
    conviction_delta: int       # -15 to +15 (smaller range than corporate events)
    key_headlines:    List[str]  # Top 2 relevant headlines found
    one_line_summary: str


# ══════════════════════════════════════════════════════════════════════════════
# DDGS Helper
# ══════════════════════════════════════════════════════════════════════════════

def _ddgs_news_sync(
    keywords:    str,
    max_results: int = 5,
    timelimit:   str = "d",     # "d" = last 24h, "w" = week
    region:      str = "in-en", # India English
) -> List[Dict]:
    """
    Synchronous DDGS news fetch.  Returns list of result dicts:
        title, body, href, source, date
    Returns empty list if DDGS is unavailable or rate-limited.
    """
    if not HAS_DDGS:
        return []
    try:
        with DDGS() as ddgs:
            results = list(ddgs.news(
                keywords=keywords,
                region=region,
                safesearch="moderate",
                timelimit=timelimit,
                max_results=max_results,
            ))
        return results or []
    except Exception as e:
        logger.warning("[NewsEngine] DDGS query failed for '%s': %s", keywords[:50], e)
        return []


async def _ddgs_news(
    keywords:    str,
    max_results: int = 5,
    timelimit:   str = "d",
) -> List[Dict]:
    """Async wrapper around _ddgs_news_sync."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None, _ddgs_news_sync, keywords, max_results, timelimit
    )


def _format_snippets(results: List[Dict], max_chars: int = 1200) -> str:
    """
    Condenses DDGS results into a compact text block for LLM input.
    Keeps token count low so local Gemma inference stays under 2 seconds.
    """
    lines = []
    for i, r in enumerate(results, 1):
        title   = r.get("title", "").strip()
        snippet = r.get("body", "").strip()[:200]
        source  = r.get("source", "").strip()
        lines.append(f"{i}. [{source}] {title}: {snippet}")
    text = "\n".join(lines)
    return text[:max_chars]


# ══════════════════════════════════════════════════════════════════════════════
# TIER 1 — Global Macro Engine
# ══════════════════════════════════════════════════════════════════════════════

class MacroNewsEngine:
    """
    Runs 7 targeted DuckDuckGo News queries at 8:30 AM IST.
    Passes the top 5 headlines per query to the local Gemma model via
    query_llm_structured.  The LLM outputs a MacroSignal with sector impacts.
    Results are written to `news_signals` and used to adjust conviction scores
    for entire sector groups.
    """

    async def _process_single_query(
        self,
        query: str,
        theme: str,
    ) -> Optional[MacroSignal]:
        """Fetches news for one macro query and extracts a MacroSignal."""
        results = await _ddgs_news(query, max_results=5, timelimit="d")
        if not results:
            logger.info("[Tier1] No results for query: %s", query[:60])
            return None

        snippets = _format_snippets(results)

        system_instruction = (
            "You are an expert macro analyst specialising in Indian equity markets. "
            "Analyse the provided news headlines and determine their impact on Indian stock sectors. "
            f"Available sectors: {', '.join(NSE_SECTORS)}. "
            "Magnitude: 1=minor market noise, 2=moderate move expected, 3=significant sector-wide impact. "
            "conviction_adjustment range: -20 (strong veto) to +20 (strong boost). "
            "Only list affected_sectors that have a clear, direct relationship to this news."
        )

        prompt = (
            f"News headlines about: {theme.replace('_', ' ')}\n\n"
            f"{snippets}\n\n"
            f"Classify the macro impact on Indian equity market sectors."
        )

        signal = await query_llm_structured(
            prompt=prompt,
            schema=MacroSignal,
            system_instruction=system_instruction,
            max_retries=2,
        )

        if signal:
            # Clamp magnitude and adjustment to valid ranges
            signal.magnitude = max(1, min(3, signal.magnitude))
            signal.conviction_adjustment = max(-20, min(20, signal.conviction_adjustment))
            logger.info(
                "[Tier1] %s → %s | sectors: %s | adj: %+d",
                theme, signal.sentiment, signal.affected_sectors,
                signal.conviction_adjustment
            )

        return signal

    async def run(self) -> Dict[str, Any]:
        """
        Runs all 7 macro queries sequentially (rate limit safe) and persists results.
        Returns a sector-level override map: {"IT": +10, "BANKING": -15, ...}
        """
        sector_overrides: Dict[str, int] = {}
        signals_to_persist = []

        for query, theme in TIER1_MACRO_QUERIES:
            signal = await self._process_single_query(query, theme)

            if signal and signal.sentiment != "NEUTRAL" and signal.magnitude >= 2:
                for sector in signal.affected_sectors:
                    # Accumulate adjustments — multiple themes can affect same sector
                    sector_overrides[sector] = (
                        sector_overrides.get(sector, 0) + signal.conviction_adjustment
                    )

            if signal:
                signals_to_persist.append({
                    "tier":               1,
                    "query":              query,
                    "theme":              signal.theme,
                    "affected_sectors":   signal.affected_sectors,
                    "sentiment":          signal.sentiment,
                    "conviction_adjustment": signal.conviction_adjustment,
                    "llm_summary":        signal.one_line_summary,
                    "metadata":           {
                        "magnitude": signal.magnitude,
                        "source":    "duckduckgo-news",
                    },
                    "processed_at":       datetime.datetime.utcnow().isoformat(),
                })

            # Rate limit protection between DDGS queries
            await asyncio.sleep(DDGS_INTER_QUERY_DELAY_SEC)

        # Clamp each sector override to [-20, +20]
        sector_overrides = {k: max(-20, min(20, v)) for k, v in sector_overrides.items()}

        if signals_to_persist and IS_DB_CONFIGURED:
            try:
                await upsert_db("news_signals", signals_to_persist)
            except Exception as e:
                logger.warning("[Tier1] Failed to persist macro signals: %s", e)

        logger.info(
            "[Tier1] Macro scan complete — %d signals | sector overrides: %s",
            len(signals_to_persist), sector_overrides
        )
        return {
            "signals_count":   len(signals_to_persist),
            "sector_overrides": sector_overrides,
            "signals":          signals_to_persist,
        }


# ══════════════════════════════════════════════════════════════════════════════
# TIER 2 — Corporate Announcement Crawler
# ══════════════════════════════════════════════════════════════════════════════

class CorporateAnnouncementCrawler:
    """
    Fetches the 50 most recent corporate filings from NSE's internal API.
    Listed companies are legally required to disclose material events to the
    exchange BEFORE speaking to any media — so this source always leads Reuters.

    The LLM triages each filing headline in a single batch pass.
    `is_material_catalyst = True` items trigger a temporary Conviction Override
    in Supabase (expires after 3 trading days automatically).
    """

    NSE_ANNOUNCEMENTS_URL = (
        "https://www.nseindia.com/api/corporate-announcements"
        "?index=equities&from_date=&to_date=&symbol=&issuer=&limit=50"
    )

    def _fetch_announcements_sync(self) -> List[Dict]:
        """Downloads latest NSE corporate announcements using curl-cffi session."""
        session = _make_session()
        try:
            resp = session.get(self.NSE_ANNOUNCEMENTS_URL, timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                # NSE returns the list directly or nested under a key
                if isinstance(data, list):
                    return data[:50]
                if isinstance(data, dict):
                    for key in ("data", "announcements", "results"):
                        if isinstance(data.get(key), list):
                            return data[key][:50]
        except Exception as e:
            logger.error("[Tier2] NSE announcements fetch failed: %s", e)
        return []

    async def _fetch_announcements(self) -> List[Dict]:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._fetch_announcements_sync)

    def _resolve_symbol(self, nse_symbol_raw: str) -> str:
        """Normalises an NSE announcement symbol to the yfinance .NS format."""
        s = str(nse_symbol_raw).strip().upper()
        return f"{s}.NS" if not s.endswith(".NS") else s

    async def _triage_announcement(self, ann: Dict) -> Optional[CorporateEvent]:
        """Passes one announcement headline to the LLM for triage."""
        symbol  = str(ann.get("symbol", "")).strip()
        subject = str(ann.get("subject", ann.get("desc", ""))).strip()
        if not subject or len(subject) < 10:
            return None

        system_instruction = (
            "You are a SEBI-qualified corporate analyst specialising in Indian equity markets. "
            "Read one NSE corporate filing headline and classify it. "
            "is_material_catalyst = True ONLY for: large order wins (>₹100 Cr), "
            "earnings beats/misses >10%, FDA approvals/rejections, M&A above ₹500 Cr, "
            "management exits at board level, or debt restructuring. "
            "conviction_override range: -30 (disaster) to +30 (major positive catalyst). "
            "For 'Noise' events (address changes, dividend declarations <2%, routine filings), "
            "set conviction_override to 0 and is_material_catalyst to False."
        )

        prompt = (
            f"NSE Filing — Company: {symbol}\n"
            f"Headline: \"{subject}\"\n\n"
            "Classify this corporate announcement."
        )

        return await query_llm_structured(
            prompt=prompt,
            schema=CorporateEvent,
            system_instruction=system_instruction,
            max_retries=2,
        )

    async def run(self) -> Dict[str, Any]:
        """
        Fetches 50 latest NSE announcements, triages each with the LLM,
        and writes conviction overrides for material catalysts.
        """
        announcements = await self._fetch_announcements()
        if not announcements:
            return {"status": "no_data", "processed": 0, "material_catalysts": []}

        material_catalysts = []
        overrides_to_write = []
        signals_to_persist = []

        for ann in announcements:
            try:
                event = await self._triage_announcement(ann)
                if not event:
                    continue

                raw_symbol = ann.get("symbol", "")
                ticker = self._resolve_symbol(raw_symbol) if raw_symbol else ""
                if event.nse_symbol:
                    ticker = self._resolve_symbol(event.nse_symbol)

                signals_to_persist.append({
                    "tier":               2,
                    "query":              raw_symbol,
                    "source_title":       ann.get("subject", ""),
                    "symbol":             ticker,
                    "is_material_catalyst": event.is_material_catalyst,
                    "event_type":         event.event_type,
                    "sentiment":          event.sentiment_shift,
                    "conviction_adjustment": event.conviction_override,
                    "llm_summary":        event.one_line_reason,
                    "processed_at":       datetime.datetime.utcnow().isoformat(),
                })

                if event.is_material_catalyst and event.conviction_override != 0 and ticker:
                    material_catalysts.append({
                        "symbol":             ticker,
                        "company_name":       event.company_name,
                        "event_type":         event.event_type,
                        "sentiment":          event.sentiment_shift,
                        "conviction_override": event.conviction_override,
                        "reason":             event.one_line_reason,
                    })

                    expires_at = (
                        datetime.datetime.utcnow() + datetime.timedelta(days=3)
                    ).isoformat()

                    overrides_to_write.append({
                        "symbol":         ticker,
                        "override_points": event.conviction_override,
                        "reason":         event.one_line_reason,
                        "source":         "TIER2_CORPORATE",
                        "expires_at":     expires_at,
                    })

                    logger.info(
                        "[Tier2] MATERIAL: %s | %s | %s | %+d pts",
                        ticker, event.event_type, event.sentiment_shift,
                        event.conviction_override
                    )

                # Throttle to avoid hammering the LLM engine
                await asyncio.sleep(0.5)

            except Exception as e:
                logger.error("[Tier2] Error processing announcement: %s", e)
                continue

        # Persist to database
        if IS_DB_CONFIGURED:
            try:
                if signals_to_persist:
                    await upsert_db("news_signals", signals_to_persist)
                if overrides_to_write:
                    await upsert_db("conviction_overrides", overrides_to_write)
                    logger.info(
                        "[Tier2] Wrote %d conviction overrides to database.",
                        len(overrides_to_write)
                    )
            except Exception as e:
                logger.warning("[Tier2] Database persist failed: %s", e)

        return {
            "status":             "success",
            "announcements_fetched": len(announcements),
            "processed":          len(signals_to_persist),
            "material_catalysts": material_catalysts,
        }


# ══════════════════════════════════════════════════════════════════════════════
# TIER 3 — Watchlist-Targeted Search
# ══════════════════════════════════════════════════════════════════════════════

class WatchlistNewsScanner:
    """
    Dynamically searches the news ONLY for stocks that matter right now:
      (a) All open journal positions — protect what you hold.
      (b) All stocks with conviction_score >= 50 — near-breakout candidates.

    Caps at 15 symbols to stay within DuckDuckGo's unmonitored rate limits.
    Runs one targeted DDGS news query per symbol ("TCS recent news contract").
    The LLM extracts WatchlistSentiment with a -15 to +15 adjustment.
    """

    async def _get_watchlist_symbols(self) -> List[Dict[str, str]]:
        """
        Returns up to TIER3_MAX_SYMBOLS symbols with their company names.
        Priority: open positions > high-conviction watchlist.
        """
        symbols = []
        seen    = set()

        # 1. Open positions (highest priority — protect capital)
        if IS_DB_CONFIGURED:
            try:
                open_trades = await query_db("trade_journal", {
                    "select":    "symbol",
                    "exit_date": "is.null",
                    "limit":     "20",
                })
                for t in open_trades:
                    s = t["symbol"]
                    if s not in seen:
                        symbols.append({"symbol": s, "source": "OPEN_POSITION"})
                        seen.add(s)
            except Exception as e:
                logger.warning("[Tier3] Could not fetch open positions: %s", e)

        # 2. High-conviction watchlist (fill remaining slots)
        if IS_DB_CONFIGURED and len(symbols) < TIER3_MAX_SYMBOLS:
            try:
                watchlist = await query_db("conviction_matrix", {
                    "select":            "symbol",
                    "conviction_score":  f"gte.50",
                    "order":             "conviction_score.desc",
                    "limit":             str(TIER3_MAX_SYMBOLS - len(symbols)),
                })
                for w in watchlist:
                    s = w["symbol"]
                    if s not in seen and s != "__MARKET__":
                        symbols.append({"symbol": s, "source": "WATCHLIST"})
                        seen.add(s)
            except Exception as e:
                logger.warning("[Tier3] Could not fetch conviction watchlist: %s", e)

        return symbols[:TIER3_MAX_SYMBOLS]

    async def _scan_symbol(self, symbol: str) -> Optional[WatchlistSentiment]:
        """Searches news for one symbol and extracts WatchlistSentiment."""
        bare = symbol.replace(".NS", "").replace(".BO", "").upper()

        # Targeted query — company name + recent news keywords
        query = f"{bare} India stock news contract order earnings recent"
        results = await _ddgs_news(query, max_results=5, timelimit="w")  # last week

        if not results:
            return None

        snippets = _format_snippets(results, max_chars=800)

        system_instruction = (
            "You are a senior equity analyst. Read news search results for one Indian stock "
            "and determine whether recent news is net positive or negative for the stock price. "
            "conviction_delta range: -15 (clearly bad news) to +15 (major positive catalyst). "
            "0 means no actionable information found. Be conservative — noise stays at 0."
        )

        prompt = (
            f"Stock: {bare} (NSE: {symbol})\n\n"
            f"Recent news search results:\n{snippets}\n\n"
            "Assess the net sentiment impact on this stock's conviction score."
        )

        return await query_llm_structured(
            prompt=prompt,
            schema=WatchlistSentiment,
            system_instruction=system_instruction,
            max_retries=2,
        )

    async def run(self) -> Dict[str, Any]:
        """
        Scans news for all watchlist symbols and writes conviction overrides
        for any significant sentiment shift (|delta| >= 5).
        """
        symbols = await self._get_watchlist_symbols()
        if not symbols:
            return {"status": "no_watchlist", "scanned": 0, "overrides": []}

        results         = []
        overrides_written = []
        signals_to_persist = []

        for entry in symbols:
            symbol = entry["symbol"]
            try:
                sentiment = await self._scan_symbol(symbol)
                if sentiment:
                    results.append({
                        "symbol":        symbol,
                        "sentiment":     sentiment.sentiment,
                        "delta":         sentiment.conviction_delta,
                        "headlines":     sentiment.key_headlines,
                        "summary":       sentiment.one_line_summary,
                        "source":        entry["source"],
                    })

                    signals_to_persist.append({
                        "tier":               3,
                        "query":              symbol,
                        "symbol":             symbol,
                        "sentiment":          sentiment.sentiment,
                        "conviction_adjustment": sentiment.conviction_delta,
                        "llm_summary":        sentiment.one_line_summary,
                        "processed_at":       datetime.datetime.utcnow().isoformat(),
                    })

                    # Only write overrides for significant sentiment signals
                    if abs(sentiment.conviction_delta) >= 5 and IS_DB_CONFIGURED:
                        expires_at = (
                            datetime.datetime.utcnow() + datetime.timedelta(days=2)
                        ).isoformat()
                        override = {
                            "symbol":         symbol,
                            "override_points": sentiment.conviction_delta,
                            "reason":         sentiment.one_line_summary,
                            "source":         "TIER3_WATCHLIST",
                            "expires_at":     expires_at,
                        }
                        overrides_written.append(override)

                        logger.info(
                            "[Tier3] %s → %s | delta: %+d | %s",
                            symbol, sentiment.sentiment,
                            sentiment.conviction_delta, sentiment.one_line_summary[:60]
                        )

                # Rate limit protection between DDGS queries
                await asyncio.sleep(DDGS_INTER_QUERY_DELAY_SEC)

            except Exception as e:
                logger.error("[Tier3] Error scanning %s: %s", symbol, e)
                continue

        if IS_DB_CONFIGURED:
            try:
                if signals_to_persist:
                    await upsert_db("news_signals", signals_to_persist)
                if overrides_written:
                    await upsert_db("conviction_overrides", overrides_written)
            except Exception as e:
                logger.warning("[Tier3] Database persist failed: %s", e)

        return {
            "status":      "success",
            "scanned":     len(results),
            "overrides":   overrides_written,
            "results":     results,
        }


# ══════════════════════════════════════════════════════════════════════════════
# Active Conviction Override Reader
# ══════════════════════════════════════════════════════════════════════════════

async def fetch_active_overrides() -> Dict[str, int]:
    """
    Queries Supabase for all non-expired conviction overrides.
    Returns a symbol → net_override_points dict.

    This is called by conviction_engine.score_single_ticker() to apply
    news-driven score adjustments to the base technical/fundamental score.
    """
    if not IS_DB_CONFIGURED:
        return {}
    try:
        now_iso = datetime.datetime.utcnow().isoformat()
        rows = await query_db("conviction_overrides", {
            "select":     "symbol,override_points",
            "expires_at": f"gt.{now_iso}",
            "limit":      "500",
        })
        overrides: Dict[str, int] = {}
        for row in rows:
            sym = row["symbol"]
            pts = int(row.get("override_points") or 0)
            # Accumulate multiple overrides for the same stock
            overrides[sym] = overrides.get(sym, 0) + pts
        # Clamp to [-30, +30]
        return {k: max(-30, min(30, v)) for k, v in overrides.items()}
    except Exception as e:
        logger.warning("[NewsEngine] fetch_active_overrides failed: %s", e)
        return {}


async def fetch_active_sector_overrides() -> Dict[str, int]:
    """
    Returns active Tier 1 macro sector overrides from the most recent
    news_signals run.  Returns sector → adjustment_points dict.
    Used by conviction engine to apply broad sector adjustments.
    """
    if not IS_DB_CONFIGURED:
        return {}
    try:
        # Fetch Tier 1 signals from the last 8 hours
        cutoff = (datetime.datetime.utcnow() - datetime.timedelta(hours=8)).isoformat()
        rows = await query_db("news_signals", {
            "select":       "affected_sectors,conviction_adjustment",
            "tier":         "eq.1",
            "processed_at": f"gt.{cutoff}",
            "limit":        "50",
        })
        sector_map: Dict[str, int] = {}
        for row in rows:
            sectors = row.get("affected_sectors") or []
            adj     = int(row.get("conviction_adjustment") or 0)
            for s in sectors:
                sector_map[s] = max(-20, min(20, sector_map.get(s, 0) + adj))
        return sector_map
    except Exception as e:
        logger.warning("[NewsEngine] fetch_active_sector_overrides failed: %s", e)
        return {}


# ══════════════════════════════════════════════════════════════════════════════
# Convenience orchestrator — runs all three tiers sequentially
# ══════════════════════════════════════════════════════════════════════════════

async def run_full_news_pipeline() -> Dict[str, Any]:
    """
    Runs Tier 1 → Tier 2 → Tier 3 sequentially.
    Tier 1 first because its sector overrides feed into conviction scoring.
    Returns combined results from all three tiers.
    """
    logger.info("[NewsEngine] Starting full 3-tier news pipeline...")
    results: Dict[str, Any] = {}

    # Tier 1 — Macro (always run first)
    try:
        results["tier1_macro"] = await MacroNewsEngine().run()
    except Exception as e:
        logger.error("[NewsEngine] Tier 1 macro failed: %s", e)
        results["tier1_macro"] = {"status": "error", "detail": str(e)}

    # Tier 2 — Corporate announcements
    try:
        results["tier2_corporate"] = await CorporateAnnouncementCrawler().run()
    except Exception as e:
        logger.error("[NewsEngine] Tier 2 corporate failed: %s", e)
        results["tier2_corporate"] = {"status": "error", "detail": str(e)}

    # Tier 3 — Watchlist-targeted search
    try:
        results["tier3_watchlist"] = await WatchlistNewsScanner().run()
    except Exception as e:
        logger.error("[NewsEngine] Tier 3 watchlist failed: %s", e)
        results["tier3_watchlist"] = {"status": "error", "detail": str(e)}

    logger.info("[NewsEngine] Full pipeline complete.")
    return results
