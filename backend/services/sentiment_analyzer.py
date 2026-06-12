import logging
import urllib.request
import xml.etree.ElementTree as ET
import re
import json
from typing import List, Dict, Any

from backend.services.redis_pipeline import RedisPipeline
from backend.services.llm_gateway import query_llm

logger = logging.getLogger(__name__)

class SentimentAnalyzer:
    """
    Morning Sentiment Invalidation Desk. Aggregates news, runs local Gemma/Llama3 model
    or Gemini fallback via unified LLM gateway to extract professional-grade positive/negative ratios,
    and invalidates shortlists.
    """
    def __init__(self, redis_pipeline: RedisPipeline):
        self.redis_pipeline = redis_pipeline
        
        # Loughran-McDonald Professional Financial Sentiment Lexicon lists
        # (These are standard institutional word lists for financial documents)
        self.lm_positive = {
            "achieve", "attain", "beat", "benefit", "boost", "climb", "delight", "exceed",
            "excel", "expand", "gain", "grow", "growth", "improve", "improvement", "increase",
            "outperform", "profit", "profitable", "profitability", "rebound", "rise",
            "strong", "success", "successful", "surpass", "win", "winner", "upward"
        }
        self.lm_negative = {
            "adverse", "barrier", "catastrophe", "claim", "collapse", "concern", "decline",
            "decrease", "defect", "deficit", "depress", "deteriorate", "disappoint", "dispute",
            "downward", "drop", "fail", "failure", "fall", "fraud", "impair", "impairment",
            "investigation", "lawsuit", "litigation", "loss", "lose", "miss", "negative",
            "penalty", "problem", "recession", "shrink", "slump", "strike", "threat",
            "underperform", "warn", "warning", "weak", "worry"
        }

    def analyze_text_sentiment_lm(self, text: str) -> float:
        """
        Loughran-McDonald academic financial lexicon sentiment scorer.
        Returns score from 0.0 (bearish) to 1.0 (bullish).
        """
        words = re.findall(r'\b\w+\b', text.lower())
        pos = sum(1 for w in words if w in self.lm_positive)
        neg = sum(1 for w in words if w in self.lm_negative)
        
        if pos + neg == 0:
            return 0.5
        return 0.5 + 0.5 * ((pos - neg) / (pos + neg))

    async def aggregate_news_headlines(self, ticker: str) -> List[str]:
        """
        Gathers news headlines for a ticker from major RSS feeds.
        Returns empty list if feeds are unavailable.
        """
        headlines = []
        try:
            url = f"https://feeds.finance.yahoo.com/rss.2.0?s={ticker}"
            req = urllib.request.Request(
                url, 
                headers={'User-Agent': 'Mozilla/5.0'}
            )
            with urllib.request.urlopen(req, timeout=5) as response:
                xml_data = response.read()
                root = ET.fromstring(xml_data)
                for item in root.findall(".//item"):
                    title = item.find("title")
                    if title is not None and title.text:
                        headlines.append(title.text)
            
            logger.info("Scraped %d headlines from RSS for %s", len(headlines), ticker)
        except Exception as e:
            logger.warning("Scraper failed to pull news for %s: %s.", ticker, str(e))
            
        return headlines

    async def analyze_sentiment(self, ticker: str) -> Dict[str, Any]:
        """
        Fetches headlines, performs LLM or Loughran-McDonald sentiment analysis,
        checks circuit breakers, and caches results directly to Redis.
        """
        headlines = await self.aggregate_news_headlines(ticker)
        
        if not headlines:
            return {
                "ticker": ticker, 
                "sentiment_score": 0.5, 
                "positive_ratio": 0.0,
                "negative_ratio": 0.0,
                "is_bubble_mania": False,
                "critical_disclosure_triggered": False,
                "is_invalidated": False
            }

        critical_disclosure_triggered = False

        # Scan headlines for catastrophic corporate flags
        catastrophic_keywords = {"fraud", "investigation", "seizure", "insolvency", "default", "scam", "arrest", "sebi penalty"}
        
        for headline in headlines:
            low_headline = headline.lower()
            if any(k in low_headline for k in catastrophic_keywords):
                logger.warning("[Circuit Breaker] Catastrophic keyword detected in headline: %s", headline)
                critical_disclosure_triggered = True

        # Construct prompt for the LLM to perform sentiment extraction
        headlines_str = "\n".join(f"- {h}" for h in headlines)
        prompt = f"""
        You are an elite financial analyst. Analyze the sentiment of the following news headlines for {ticker}:
        ---
        {headlines_str}
        ---
        
        Classify the sentiment of each headline and calculate:
        1. An overall sentiment score on a scale from 0.0 (extremely bearish/negative) to 1.0 (extremely bullish/positive).
        2. The ratio of positive headlines.
        3. The ratio of negative headlines.
        
        Provide your response in JSON format:
        {{"sentiment_score": float, "positive_ratio": float, "negative_ratio": float}}
        """

        raw_response = await query_llm(prompt)
        
        flags = None
        if raw_response:
            try:
                start_idx = raw_response.find("{")
                end_idx = raw_response.rfind("}") + 1
                if start_idx != -1 and end_idx != -1:
                    flags = json.loads(raw_response[start_idx:end_idx])
            except Exception as e:
                logger.error("Failed to parse LLM sentiment response: %s", str(e))

        if flags:
            sentiment_score = flags.get("sentiment_score", 0.5)
            pos_ratio = flags.get("positive_ratio", 0.0)
            neg_ratio = flags.get("negative_ratio", 0.0)
            logger.info("LLM sentiment parsed for %s: Score = %.2f, Pos = %.2f, Neg = %.2f", ticker, sentiment_score, pos_ratio, neg_ratio)
        else:
            logger.info("Using local Loughran-McDonald dictionary fallback for headlines sentiment.")
            # Fallback evaluation
            scores = [self.analyze_text_sentiment_lm(h) for h in headlines]
            sentiment_score = sum(scores) / len(scores) if scores else 0.5
            
            pos_count = sum(1 for s in scores if s > 0.5)
            neg_count = sum(1 for s in scores if s < 0.5)
            pos_ratio = pos_count / len(headlines)
            neg_ratio = neg_count / len(headlines)

        # 1. Anti-Bubble Invalidation: Positive sentiment exceeds 95% (extreme retail mania / bubble peak)
        is_bubble = pos_ratio >= 0.95
        
        # 2. Circuit Breaker Invalidation: Negative critical keywords or negative sentiment ratio > 60%
        is_critical = critical_disclosure_triggered or neg_ratio >= 0.60
        
        is_invalidated = is_bubble or is_critical

        result = {
            "ticker": ticker,
            "sentiment_score": round(sentiment_score, 2),
            "positive_ratio": round(pos_ratio, 2),
            "negative_ratio": round(neg_ratio, 2),
            "is_bubble_mania": is_bubble,
            "critical_disclosure_triggered": critical_disclosure_triggered,
            "is_invalidated": is_invalidated
        }

        # Cache results in Redis under the ticker name
        await self.redis_pipeline.cache_indicator(ticker, "sentiment", result, expire_seconds=86400)
        logger.info("Successfully cached sentiment analysis for %s. Invalidated = %s", ticker, is_invalidated)

        return result
