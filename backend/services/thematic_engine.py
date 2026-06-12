import os
import re
import json
import logging
import asyncio
import time
import email.utils
import pandas as pd
import numpy as np
import yfinance as yf
from typing import Dict, Any, List, Optional

from backend.services.llm_gateway import query_llm
from backend.services.trend_models import TrendEvaluator
from backend.services.redis_pipeline import RedisPipeline
from backend.services.thematic_db import (
    init_db,
    add_node_async,
    add_edge_async,
    get_suppliers_for_theme_async,
    prune_expired_catalysts_async
)

logger = logging.getLogger(__name__)

class ThematicCatalystAnalyzer:
    """
    Analyzes policy documents / budget updates (Catalyst Ingestion),
    maps them to supply chain suppliers (via SQLite Graph Database),
    evaluates institutional accumulation (Smart Money Verification with OBV),
    and filters out overextended distribution plays (Catalyst Exhaustion Filter).
    """
    def __init__(self, redis_pipeline: RedisPipeline):
        self.redis_pipeline = redis_pipeline
        # Ensure database and schemas are initialized
        init_db()

    async def ingest_and_categorize(self, catalyst_text: str) -> Dict[str, Any]:
        """
        Use local Gemma model to parse unstructured policy text and return theme category,
        relevant materials/products, and estimated budget size.
        """
        system_instruction = (
            "You are an expert thematic investing engine. Categorize the provided policy or budget catalyst "
            "into exactly one of these sectors: DEFENSE, RAILWAYS, RENEWABLE_ENERGY, SEMICONDUCTORS, or OTHER. "
            "Identify key products or materials mentioned, and extract any budget allocation (in Crore Rupees). "
            "Return STRICTLY valid JSON with no markdown tags."
        )
        
        prompt = (
            f"Catalyst Update Text: \"{catalyst_text}\"\n\n"
            "Format the output strictly as a JSON object:\n"
            "{\n"
            "  \"theme\": \"DEFENSE\"|\"RAILWAYS\"|\"RENEWABLE_ENERGY\"|\"SEMICONDUCTORS\"|\"OTHER\",\n"
            "  \"products_or_materials\": [\"list of materials/products\"],\n"
            "  \"estimated_budget_cr\": float_or_null\n"
            "}"
        )
        
        try:
            raw_res = await query_llm(prompt=prompt, system_instruction=system_instruction)
            if not raw_res:
                return {"theme": "OTHER", "products_or_materials": [], "estimated_budget_cr": None}
                
            # Clean and parse JSON
            cleaned = raw_res.strip()
            json_match = re.search(r'(\{.*\})', cleaned, re.DOTALL)
            if json_match:
                cleaned = json_match.group(1).strip()
            
            parsed = json.loads(cleaned)
            logger.info("Successfully ingested catalyst and categorized theme: %s", parsed.get("theme"))
            return parsed
        except Exception as e:
            logger.error("Failed to parse catalyst ingestion response: %s. Response: %s", str(e), raw_res if 'raw_res' in locals() else '')
            return {"theme": "OTHER", "products_or_materials": [], "estimated_budget_cr": None}

    def _resolve_company_ticker(self, name: str, nifty500: List[Dict[str, str]]) -> Optional[str]:
        """Resolves a raw company name to a Nifty 500 symbol using clean substring matching."""
        if not name:
            return None
            
        name_clean = re.sub(
            r'\b(ltd|limited|india|corp|corporation|industries|systems|tech|technology|engineering|holdings|group)\b', 
            '', 
            name.lower()
        ).strip()
        name_tokens = set(name_clean.split())
        
        best_match = None
        best_score = 0.0
        
        for item in nifty500:
            c_name = item["name"]
            c_symbol = item["symbol"]
            
            c_clean = re.sub(
                r'\b(ltd|limited|india|corp|corporation|industries|systems|tech|technology|engineering|holdings|group)\b', 
                '', 
                c_name.lower()
            ).strip()
            
            if name_clean == c_clean:
                return c_symbol
                
            if name_clean in c_clean or c_clean in name_clean:
                score = len(name_clean) / len(c_clean) if len(c_clean) > len(name_clean) else len(c_clean) / len(name_clean)
                if score > best_score:
                    best_score = score
                    best_match = c_symbol
                    
            c_tokens = set(c_clean.split())
            common = name_tokens.intersection(c_tokens)
            if common:
                score = len(common) / max(len(name_tokens), len(c_tokens))
                if score > best_score:
                    best_score = score
                    best_match = c_symbol
                    
        if best_score >= 0.4:
            return best_match
            
        return None

    async def crawl_and_extract_news_catalysts(self) -> Dict[str, Any]:
        """
        Crawls Google News search RSS feed for Indian corporate contract/order wins,
        uses local Gemma-4 to parse the details, and updates the SQLite graph database.
        """
        logger.info("Starting thematic order win news RSS crawler...")
        
        from backend.services.data_fetcher import fetch_nifty500_metadata
        nifty500 = fetch_nifty500_metadata()
        
        import urllib.request
        import xml.etree.ElementTree as ET
        
        url = "https://news.google.com/rss/search?q=site:moneycontrol.com+OR+site:economictimes.indiatimes.com+%22order+win%22+OR+%22wins+contract%22+OR+%22awarded+contract%22+OR+%22wins+order%22&hl=en-IN&gl=IN&ceid=IN:en"
        headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
        
        articles = []
        try:
            req = urllib.request.Request(url, headers=headers)
            loop = asyncio.get_event_loop()
            xml_data = await loop.run_in_executor(
                None,
                lambda: urllib.request.urlopen(req, timeout=15).read()
            )
            
            root = ET.fromstring(xml_data)
            items = root.findall(".//item")
            logger.info("Found %d articles in Google News RSS feed.", len(items))
            
            for item in items[:10]:
                title = item.find("title").text if item.find("title") is not None else ""
                link = item.find("link").text if item.find("link") is not None else ""
                desc = item.find("description").text if item.find("description") is not None else ""
                pub_date = item.find("pubDate").text if item.find("pubDate") is not None else ""
                
                keywords = ["order", "contract", "win", "secures", "awarded", "deal", "crore", "allocation"]
                if any(kw in title.lower() or kw in desc.lower() for kw in keywords):
                    articles.append({
                        "title": title,
                        "description": re.sub(r'<[^>]*>', '', desc),
                        "link": link,
                        "pub_date": pub_date
                    })
        except Exception as e:
            logger.error("Failed to fetch/parse Google News RSS: %s", str(e))
            return {"status": "error", "message": f"Failed to fetch RSS: {e}", "processed": 0}
            
        logger.info("Filtering down to %d relevant news articles to evaluate with LLM", len(articles))
        added_relations = []
        
        for art in articles:
            try:
                system_instruction = (
                    "You are an expert news classifier for Indian stock markets. Extract order wins and contract details from the news article. "
                    "Theme MUST be one of: DEFENSE, RAILWAYS, RENEWABLE_ENERGY, SEMICONDUCTORS, or OTHER. "
                    "Return STRICTLY valid JSON with no markdown tags."
                )
                
                prompt = (
                    f"Article Title: \"{art['title']}\"\n"
                    f"Summary: \"{art['description']}\"\n\n"
                    "Format the output strictly as a JSON object:\n"
                    "{\n"
                    "  \"is_order_win\": true|false,\n"
                    "  \"company_name\": \"Cleaned official name of the company winning the order (or null)\",\n"
                    "  \"theme\": \"DEFENSE\"|\"RAILWAYS\"|\"RENEWABLE_ENERGY\"|\"SEMICONDUCTORS\"|\"OTHER\",\n"
                    "  \"products_or_materials\": [\"list of materials/products\"],\n"
                    "  \"estimated_budget_cr\": float_or_null\n"
                    "}"
                )
                
                raw_res = await query_llm(prompt=prompt, system_instruction=system_instruction)
                if not raw_res:
                    continue
                    
                cleaned = raw_res.strip()
                json_match = re.search(r'(\{.*\})', cleaned, re.DOTALL)
                if json_match:
                    cleaned = json_match.group(1).strip()
                    
                parsed = json.loads(cleaned)
                
                if parsed.get("is_order_win") and parsed.get("company_name"):
                    company_name = parsed["company_name"]
                    theme = parsed["theme"].upper()
                    products = parsed.get("products_or_materials", [])
                    budget_cr = parsed.get("estimated_budget_cr") or 1.0
                    
                    resolved_symbol = self._resolve_company_ticker(company_name, nifty500)
                    if resolved_symbol:
                        logger.info("Resolved company '%s' to ticker: %s", company_name, resolved_symbol)
                        
                        await add_node_async(
                            id=resolved_symbol,
                            type="COMPANY",
                            label=company_name,
                            description=f"Discovered from announcement: {art['title']}"
                        )
                        
                        pub_ts = int(time.time())
                        try:
                            if art["pub_date"]:
                                parsed_time = email.utils.parsedate_to_datetime(art["pub_date"])
                                pub_ts = int(parsed_time.timestamp())
                        except Exception:
                            pass
                            
                        role_str = f"Won order for {', '.join(products)}: {art['title']}" if products else art['title']
                        
                        success = await add_edge_async(
                            source_id=resolved_symbol,
                            target_id=theme,
                            relation_type="CONTRACT_WIN",
                            weight=float(budget_cr),
                            role=role_str,
                            pricing_power="Medium (Auto-crawled)",
                            catalyst_relevance=f"Budget value: {budget_cr} Cr",
                            timestamp=pub_ts
                        )
                        
                        if success:
                            added_relations.append({
                                "symbol": resolved_symbol,
                                "company": company_name,
                                "theme": theme,
                                "budget_cr": budget_cr,
                                "details": role_str
                            })
                            
            except Exception as e:
                logger.error("Failed parsing article '%s' with Gemma: %s", art['title'], str(e))
                continue
                
        # Prune expired contract wins (> 180 days)
        pruned_count = await prune_expired_catalysts_async(ttl_days=180)
        
        return {
            "status": "success",
            "crawled_count": len(articles),
            "added_count": len(added_relations),
            "added_relations": added_relations,
            "pruned_expired_count": pruned_count
        }

    async def analyze_thematic_chain(self, catalyst_text: str) -> Dict[str, Any]:
        """
        Runs the full 4-stage thematic supply chain arbitrage analysis using SQLite graph data.
        """
        # Stage 1: Ingestion
        ingestion_results = await self.ingest_and_categorize(catalyst_text)
        theme = ingestion_results.get("theme", "OTHER").upper()
        products_materials = ingestion_results.get("products_or_materials", [])
        budget_cr = ingestion_results.get("estimated_budget_cr")

        # Stage 2: SQLite Graph Lookup
        suppliers = await get_suppliers_for_theme_async(theme)
        if not suppliers:
            return {
                "status": "ignored",
                "reason": f"No knowledge graph mappings available for sector/theme: {theme}.",
                "ingestion": ingestion_results
            }

        logger.info("Retrieved %d supply chain suppliers for theme: %s", len(suppliers), theme)
        arbitrage_candidates = []

        # Connect to Redis
        await self.redis_pipeline.connect()

        # Process each supplier
        for supplier in suppliers:
            symbol = supplier["symbol"]
            try:
                # Retrieve price candles from cache
                candles = await self.redis_pipeline.fetch_ohlcva(symbol, "1d")
                
                # Resilient fallback: fetch directly from Yahoo Finance if not cached
                if not candles or len(candles) < 90:
                    logger.info("Cache miss or short history for %s. Fetching live history from yfinance...", symbol)
                    loop = asyncio.get_event_loop()
                    hist_df = await loop.run_in_executor(
                        None,
                        lambda: yf.Ticker(symbol).history(period="250d")
                    )
                    if hist_df.empty:
                        logger.warning("No price data returned from yfinance for %s.", symbol)
                        continue
                    
                    hist_df = hist_df.reset_index()
                    hist_df.rename(columns={
                        "Date": "timestamp",
                        "Open": "open",
                        "High": "high",
                        "Low": "low",
                        "Close": "close",
                        "Volume": "volume"
                    }, inplace=True)
                    hist_df["timestamp"] = hist_df["timestamp"].astype(str)
                    candles = hist_df.to_dict(orient="records")
                    
                    # Cache to Redis for subsequent lookups
                    await self.redis_pipeline.cache_ohlcva(symbol, "1d", candles)

                df = pd.DataFrame(candles)
                
                # Data Anomaly Filters (Sanity Checks)
                if df.empty or "close" not in df.columns or "volume" not in df.columns:
                    logger.warning("Empty or invalid dataframe for %s. Skipping.", symbol)
                    continue
                    
                # 1. Zero/Negative Price filter
                df = df[df["close"] > 0]
                if len(df) < 10:
                    logger.warning("Insufficient valid price candles for %s after filtering non-positive prices.", symbol)
                    continue
                    
                # 2. Outlier Price check (> 100% daily shift)
                pct_change = df["close"].pct_change().abs()
                has_outlier_spike = (pct_change > 1.0).any()
                if has_outlier_spike:
                    logger.warning("Data anomaly: Outlier daily price change (>100%%) detected for %s.", symbol)
                
                # 3. Volume Anomaly Check
                zero_vol_days = int((df["volume"] == 0).sum())
                if zero_vol_days > 0:
                    logger.warning("Volume anomaly: %d days with 0 volume found for %s.", zero_vol_days, symbol)

                df = TrendEvaluator.calculate_indicators(df)

                # Stage 3: Smart Money Verification (OBV & Technical checks)
                current_price = float(df["close"].iloc[-1])
                
                # Check OBV trend
                last_obv = float(df["obv"].iloc[-1])
                last_obv_ema = float(df["obv_ema20"].iloc[-1])
                obv_status = "ACCUMULATION" if last_obv > last_obv_ema else "DISTRIBUTION"
                
                # Check if OBV is rising over the last 10 days
                obv_diff_10d = float(df["obv"].iloc[-1] - df["obv"].iloc[-10]) if len(df) >= 10 else 0.0
                obv_rising = obv_diff_10d > 0.0

                # Weinstein stage evaluation
                weinstein_result = TrendEvaluator.evaluate_weinstein(df)
                stage = weinstein_result.get("stage", "Unknown")

                # Get Live Market Cap
                loop = asyncio.get_event_loop()
                info = await loop.run_in_executor(
                    None,
                    lambda: yf.Ticker(symbol).info
                )
                market_cap = info.get("marketCap", 0)
                
                # Estimate contract impact ratio
                impact_pct = 0.0
                if budget_cr and market_cap > 0:
                    market_cap_cr = market_cap / 10000000.0 # 1 Crore = 10,000,000
                    impact_pct = (budget_cr / market_cap_cr) * 100.0

                # Stage 4: Risk & Trap Filter (Catalyst Exhaustion Check)
                last_90d_df = df.iloc[-90:]
                min_90d_price = last_90d_df["low"].min()
                run_up_pct = (current_price - min_90d_price) / min_90d_price if min_90d_price > 0 else 0.0

                # Flag as Catalyst Exhausted if stock has rallied > 50% in the last 90 trading days
                is_exhausted = run_up_pct >= 0.50
                
                # Derive Recommendation Action
                if is_exhausted:
                    recommendation = "Do Not Buy - Catalyst Exhausted"
                    rec_color = "rose"
                elif "Stage 4" in stage or "Stage 3" in stage:
                    recommendation = "Avoid - Negative Trend Structure"
                    rec_color = "rose"
                elif obv_status == "DISTRIBUTION" or not obv_rising:
                    recommendation = "Watchlist - Institutional Selling/Weak Volume Support"
                    rec_color = "yellow"
                else:
                    timing = TrendEvaluator.get_entry_timing_assessment(df, weinstein_result, [])
                    timing_status = timing.get("status", "Neutral")
                    if timing_status in ["Avoid", "Train Has Left"]:
                        recommendation = f"Hold / Watchlist ({timing_status})"
                        rec_color = "yellow"
                    else:
                        recommendation = f"Buy Accumulation ({timing_status})"
                        rec_color = "emerald"

                arbitrage_candidates.append({
                    "symbol": symbol,
                    "name": supplier["name"],
                    "role": supplier.get("role") or supplier.get("node_desc") or "",
                    "pricing_power": supplier.get("pricing_power") or "Medium",
                    "catalyst_relevance": supplier.get("catalyst_relevance") or "",
                    "market_data": {
                        "current_price": round(current_price, 2),
                        "market_cap_cr": round(market_cap / 10000000.0, 2) if market_cap else None,
                        "contract_impact_pct": round(impact_pct, 2),
                        "run_up_90d_pct": round(run_up_pct * 100.0, 2)
                    },
                    "technical_verification": {
                        "weinstein_stage": stage,
                        "obv_status": obv_status,
                        "obv_accumulation_90d": obv_rising,
                        "is_overextended": is_exhausted,
                        "data_anomalies": {
                            "has_price_spike": bool(has_outlier_spike),
                            "zero_volume_days": int(zero_vol_days)
                        }
                    },
                    "actionable_recommendation": {
                        "verdict": recommendation,
                        "color": rec_color
                    }
                })
            except Exception as e:
                logger.error("Error analyzing thematic candidate %s: %s", symbol, str(e))
                continue

        await self.redis_pipeline.disconnect()

        # Sort candidates so that those with actionable "Buy" ratings and higher pricing power come first
        arbitrage_candidates.sort(
            key=lambda x: (
                0 if "Buy" in x["actionable_recommendation"]["verdict"] else 1,
                0 if "High" in x["pricing_power"] else 1,
                -x["market_data"]["contract_impact_pct"]
            )
        )

        return {
            "status": "success",
            "catalyst_ingested": {
                "text": catalyst_text,
                "theme": theme,
                "products_materials": products_materials,
                "budget_cr": budget_cr
            },
            "candidates_count": len(arbitrage_candidates),
            "candidates": arbitrage_candidates
        }
