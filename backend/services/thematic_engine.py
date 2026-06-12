import os
import re
import json
import logging
import asyncio
import pandas as pd
import numpy as np
import yfinance as yf
from typing import Dict, Any, List, Optional

from backend.services.llm_gateway import query_llm
from backend.services.trend_models import TrendEvaluator
from backend.services.redis_pipeline import RedisPipeline

logger = logging.getLogger(__name__)

class ThematicCatalystAnalyzer:
    """
    Analyzes policy documents / budget updates (Catalyst Ingestion),
    maps them to supply chain suppliers (Knowledge Graph),
    evaluates institutional accumulation (Smart Money Verification with OBV),
    and filters out overextended distribution plays (Catalyst Exhaustion Filter).
    """
    def __init__(self, redis_pipeline: RedisPipeline):
        self.redis_pipeline = redis_pipeline
        
        # Locate local data_store directory for the knowledge graph file
        services_dir = os.path.dirname(os.path.abspath(__file__))
        backend_dir = os.path.dirname(services_dir)
        self.graph_path = os.path.abspath(os.path.join(backend_dir, "data_store", "thematic_knowledge_graph.json"))
        self.knowledge_graph = self._load_knowledge_graph()

    def _load_knowledge_graph(self) -> Dict[str, Any]:
        """Loads the thematic knowledge graph from the local JSON database file."""
        if os.path.exists(self.graph_path):
            try:
                with open(self.graph_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Failed to read knowledge graph JSON at {self.graph_path}: {e}")
                
        # Fallback default knowledge graph
        default_graph = {
            "DEFENSE": {
                "description": "Defense acquisition, military upgrades, and indigenization",
                "suppliers": [
                    {
                        "symbol": "SOLARINDS.NS",
                        "name": "Solar Industries India",
                        "role": "Propellants and High-Energy Explosives supplier for missiles/rockets",
                        "pricing_power": "High (Monopoly/Duopoly)",
                        "catalyst_relevance": "Procurement of missiles, ammunition, and explosives"
                    },
                    {
                        "symbol": "PREMEXPLOS.NS",
                        "name": "Premier Explosives",
                        "role": "Solid Propellants and missile explosive material supplier",
                        "pricing_power": "High (Specialized monopoly)",
                        "catalyst_relevance": "Solid rocket motors, propellants"
                    },
                    {
                        "symbol": "MIDHANI.NS",
                        "name": "Mishra Dhatu Nigam",
                        "role": "Specialty steel, titanium alloys, and superalloys",
                        "pricing_power": "High (Strategic PSU monopoly)",
                        "catalyst_relevance": "Armor plates, missile casings, fighter jets, submarines"
                    },
                    {
                        "symbol": "BEL.NS",
                        "name": "Bharat Electronics",
                        "role": "Military radar, sonar, and avionics communication systems",
                        "pricing_power": "High (Defense electronics giant)",
                        "catalyst_relevance": "Electronics, systems integration, avionics"
                    },
                    {
                        "symbol": "HAL.NS",
                        "name": "Hindustan Aeronautics",
                        "role": "Fighter jets, helicopters, gas turbines, and structural aerospace components",
                        "pricing_power": "High (National aerospace monopoly)",
                        "catalyst_relevance": "Combat aircraft, helicopters, aerospace indigenization"
                    },
                    {
                        "symbol": "MAZDOCK.NS",
                        "name": "Mazagon Dock Shipbuilders",
                        "role": "Submarines, destroyers, and naval warships",
                        "pricing_power": "High (Naval PSU monopoly)",
                        "catalyst_relevance": "Warships, submarines, naval defense acquisition"
                    },
                    {
                        "symbol": "BEML.NS",
                        "name": "BEML Limited",
                        "role": "Heavy military trucks, missile launchers, and bulldozers",
                        "pricing_power": "High (Specialized defense PSU supplier)",
                        "catalyst_relevance": "Missile launchers, military transports, heavy ground systems"
                    }
                ]
            },
            "RAILWAYS": {
                "description": "Railway modernization, high-speed rail, wagon procurement, and metro lines",
                "suppliers": [
                    {
                        "symbol": "TITAGARH.NS",
                        "name": "Titagarh Rail Systems",
                        "role": "Railway wagons, passenger coaches, and metro trainsets",
                        "pricing_power": "High (Wagon major)",
                        "catalyst_relevance": "Freight wagons, passenger coaches, high-speed bogies"
                    },
                    {
                        "symbol": "TEXRAIL.NS",
                        "name": "Texmaco Rail & Engineering",
                        "role": "Railway wagons, steel castings, and track EPC",
                        "pricing_power": "Medium",
                        "catalyst_relevance": "Freight wagons, track electrification, signals"
                    },
                    {
                        "symbol": "RAMKRISHN.NS",
                        "name": "Ramkrishna Forgings",
                        "role": "Railway wheelsets, axles, and heavy forged components",
                        "pricing_power": "High (Global forging exporter)",
                        "catalyst_relevance": "Wheel and axle assemblies, structural forgings"
                    },
                    {
                        "symbol": "RVNL.NS",
                        "name": "Rail Vikas Nagar",
                        "role": "Railway infrastructure project execution and line doubling",
                        "pricing_power": "Medium (EPC execution)",
                        "catalyst_relevance": "Infrastructure, track laying, new lines"
                    },
                    {
                        "symbol": "IRCON.NS",
                        "name": "IRCON International",
                        "role": "Specialized railway tunnels, bridges, and international rail EPC",
                        "pricing_power": "Medium (PSU builder)",
                        "catalyst_relevance": "Bridges, tunnels, railway electrification"
                    }
                ]
            },
            "RENEWABLE_ENERGY": {
                "description": "Solar power expansion, wind energy projects, grid transmission, green hydrogen",
                "suppliers": [
                    {
                        "symbol": "BORORENEW.NS",
                        "name": "Borosil Renewables",
                        "role": "Solar tempered glass manufacturing",
                        "pricing_power": "High (Sole domestic solar glass manufacturer)",
                        "catalyst_relevance": "Solar glass modules, photovoltaic cell covers"
                    },
                    {
                        "symbol": "SUZLON.NS",
                        "name": "Suzlon Energy",
                        "role": "Wind turbine generators and wind farm construction",
                        "pricing_power": "High (Wind turbine major)",
                        "catalyst_relevance": "Wind turbines, wind farm capacity additions"
                    },
                    {
                        "symbol": "KPIGREEN.NS",
                        "name": "KPI Green Energy",
                        "role": "Solar power developer and IPP (Independent Power Producer)",
                        "pricing_power": "Medium",
                        "catalyst_relevance": "Solar power capacity, captive solar parks"
                    },
                    {
                        "symbol": "GEPIL.NS",
                        "name": "GE Power India",
                        "role": "Thermal and renewable grid transmission, boilers, and transformers",
                        "pricing_power": "High (Utility engineering)",
                        "catalyst_relevance": "Power transmission, grid substation transformers"
                    }
                ]
            },
            "SEMICONDUCTORS": {
                "description": "Semiconductor manufacturing, silicon wafers, testing, and packaging (OSAT)",
                "suppliers": [
                    {
                        "symbol": "CGPOWER.NS",
                        "name": "CG Power and Industrial Solutions",
                        "role": "Joint-venture OSAT assembly and testing plant",
                        "pricing_power": "High (Early mover OSAT)",
                        "catalyst_relevance": "OSAT, chip packaging and testing facilities"
                    },
                    {
                        "symbol": "KAYNES.NS",
                        "name": "Kaynes Technology",
                        "role": "Electronic Manufacturing Services (EMS) and semiconductor OSAT packaging",
                        "pricing_power": "High (EMS leader)",
                        "catalyst_relevance": "OSAT facility setup, electronic board sub-assembly"
                    },
                    {
                        "symbol": "LINDEINDIA.NS",
                        "name": "Linde India",
                        "role": "Specialty ultra-pure gases (argon, helium, nitrogen) for cleanrooms",
                        "pricing_power": "High (Industrial gases monopoly)",
                        "catalyst_relevance": "Silicon wafer cleaning, semiconductor process gases"
                    }
                ]
            }
        }
        
        try:
            os.makedirs(os.path.dirname(self.graph_path), exist_ok=True)
            with open(self.graph_path, 'w', encoding='utf-8') as f:
                json.dump(default_graph, f, indent=2)
            logger.info(f"Initialized default knowledge graph database at {self.graph_path}")
        except Exception as e:
            logger.error(f"Failed to initialize default knowledge graph file: {e}")
            
        return default_graph

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

    async def analyze_thematic_chain(self, catalyst_text: str) -> Dict[str, Any]:
        """
        Runs the full 4-stage thematic supply chain arbitrage analysis.
        """
        # Stage 1: Ingestion
        ingestion_results = await self.ingest_and_categorize(catalyst_text)
        theme = ingestion_results.get("theme", "OTHER").upper()
        products_materials = ingestion_results.get("products_or_materials", [])
        budget_cr = ingestion_results.get("estimated_budget_cr")

        if theme not in self.knowledge_graph:
            return {
                "status": "ignored",
                "reason": f"No knowledge graph mappings available for sector/theme: {theme}.",
                "ingestion": ingestion_results
            }

        # Stage 2: Knowledge Graph Lookup
        sector_details = self.knowledge_graph[theme]
        suppliers = sector_details["suppliers"]
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
                    "role": supplier["role"],
                    "pricing_power": supplier["pricing_power"],
                    "catalyst_relevance": supplier["catalyst_relevance"],
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
                        "is_overextended": is_exhausted
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
