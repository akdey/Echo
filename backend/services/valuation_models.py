import pandas as pd
import numpy as np
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

class ValuationEvaluator:
    """
    Fundamental Valuation and Corporate Governance Auditor.
    Implements Warren Buffett Moat & Quality metrics and Benjamin Graham's Intrinsic Value.
    """
    
    @staticmethod
    def calculate_valuation(
        info: Dict[str, Any],
        financials_df: Optional[pd.DataFrame] = None,
        balance_sheet_df: Optional[pd.DataFrame] = None,
        cashflow_df: Optional[pd.DataFrame] = None
    ) -> Dict[str, Any]:
        """
        Calculates Warren Buffett quality metrics and Benjamin Graham's intrinsic value.
        Safely falls back if historical statement DataFrames are missing or incomplete.
        """
        # --- 1. Warren Buffett / Quality Metrics ---
        # ROCE (Return on Capital Employed) = EBIT / (Total Assets - Current Liabilities)
        # EBIT = Operating Income or Gross Profit - SG&A. Fallback to info['ebitda'] or info['operatingProfitMargins'] * Revenues
        
        roce_3yr = []
        roe_3yr = []
        cfo_to_ni_3yr = []
        margin_stability = 0.0
        margins = []
        
        # Pull values from history DataFrames if available
        has_statements = (
            financials_df is not None and not financials_df.empty and
            balance_sheet_df is not None and not balance_sheet_df.empty and
            cashflow_df is not None and not cashflow_df.empty
        )
        
        if has_statements:
            try:
                # Transpose if indices are metrics and columns are years
                fin = financials_df.copy()
                bs = balance_sheet_df.copy()
                cf = cashflow_df.copy()
                
                # Align columns (years)
                common_years = list(set(fin.columns).intersection(set(bs.columns)).intersection(set(cf.columns)))
                common_years.sort(reverse=True) # newest to oldest
                
                for yr in common_years[:3]: # last 3 years
                    ebit = None
                    # Try different naming conventions for EBIT
                    for ebit_name in ["EBIT", "Operating Income", "OperatingIncome"]:
                        if ebit_name in fin.index:
                            ebit = float(fin.loc[ebit_name, yr])
                            break
                    if ebit is None:
                        # Fallback: Revenues * OperatingMargin
                        rev_name = ["Total Revenue", "TotalRevenue", "Revenues"]
                        rev = None
                        for rn in rev_name:
                            if rn in fin.index:
                                rev = float(fin.loc[rn, yr])
                                break
                        op_margin = info.get("operatingMargins", 0.1)
                        if rev:
                            ebit = rev * op_margin
                            
                    total_assets = None
                    for ta_name in ["Total Assets", "TotalAssets"]:
                        if ta_name in bs.index:
                            total_assets = float(bs.loc[ta_name, yr])
                            break
                            
                    curr_liab = 0.0
                    for cl_name in ["Total Current Liabilities", "TotalCurrentLiabilities", "Current Liabilities"]:
                        if cl_name in bs.index:
                            curr_liab = float(bs.loc[cl_name, yr])
                            break
                            
                    net_inc = None
                    for ni_name in ["Net Income", "NetIncome", "Net Income Common Stockholders"]:
                        if ni_name in fin.index:
                            net_inc = float(fin.loc[ni_name, yr])
                            break
                            
                    equity = None
                    for eq_name in ["Stockholders Equity", "Total Stockholders Equity", "TotalEquity"]:
                        if eq_name in bs.index:
                            equity = float(bs.loc[eq_name, yr])
                            break
                            
                    cfo = None
                    for cfo_name in ["Cash Flow From Operating Activities", "Operating Cash Flow", "OperatingCashFlow"]:
                        if cfo_name in cf.index:
                            cfo = float(cf.loc[cfo_name, yr])
                            break
                            
                    # Calculate ROCE
                    if ebit and total_assets and total_assets > curr_liab:
                        capital_employed = total_assets - curr_liab
                        roce_3yr.append(ebit / capital_employed)
                        
                    # Calculate ROE
                    if net_inc and equity and equity > 0:
                        roe_3yr.append(net_inc / equity)
                        
                    # Calculate CFO to Net Income
                    if cfo and net_inc and net_inc != 0:
                        cfo_to_ni_3yr.append(cfo / net_inc)
                        
                    # Operating Margin
                    rev_name = ["Total Revenue", "TotalRevenue", "Revenues"]
                    rev = None
                    for rn in rev_name:
                        if rn in fin.index:
                            rev = float(fin.loc[rn, yr])
                            break
                    if rev and ebit:
                        margins.append(ebit / rev)
                        
                if margins:
                    margin_stability = float(np.std(margins))
            except Exception as e:
                logger.warning("Error calculating statements fundamentals: %s. Falling back to info dictionary.", str(e))
                
        # Fallbacks to info dict if historical lists are empty
        roce = float(np.mean(roce_3yr)) if roce_3yr else info.get("returnOnAssets", 0.10) * 1.5 # proxy
        roe = float(np.mean(roe_3yr)) if roe_3yr else info.get("returnOnEquity", 0.12)
        cfo_ni = float(np.mean(cfo_to_ni_3yr)) if cfo_to_ni_3yr else 1.1 # proxy default
        
        # Debt-to-Equity
        debt_to_equity = info.get("debtToEquity", 0.0)
        # yfinance reports debtToEquity in percent (e.g. 80.0 meaning 0.80) or ratio. Let's normalize it.
        if debt_to_equity > 10.0:
            debt_to_equity = debt_to_equity / 100.0
            
        # EBITDA Margin / Operating Margin Moat
        op_margin = info.get("operatingMargins", 0.1)
        ebitda_margin = info.get("ebitdaMargins", 0.15)
        
        # Moat Classification
        # High Moat: ROCE > 15%, stable margins, low debt
        is_financial = "bank" in info.get("industry", "").lower() or "financial services" in info.get("sector", "").lower()
        
        moat_score = 0
        if roce >= 0.15: moat_score += 2
        if roe >= 0.15: moat_score += 1
        if op_margin >= 0.15: moat_score += 1
        if debt_to_equity < 0.5 or is_financial: moat_score += 1
        
        moat_rating = "None"
        if moat_score >= 4:
            moat_rating = "Wide Moat (Buffett Approved)"
        elif moat_score >= 2:
            moat_rating = "Narrow Moat"
        else:
            moat_rating = "No Moat"

        # --- 2. Benjamin Graham Intrinsic Value & Margin of Safety ---
        # V* = (EPS * (8.5 + 2g) * 4.4) / Y
        # EPS = trailing EPS or forward EPS
        # g = expected 5-year growth rate (default to historical growth or 7%)
        # Y = AAA corporate bond yield (default to 7.5% for India)
        
        eps = info.get("trailingEps") or info.get("forwardEps") or 1.0
        g = info.get("earningsGrowth", 0.08)
        if g:
            g = max(1.0, g * 100) # Convert to percent e.g. 0.08 -> 8.0
        else:
            g = 8.0 # conservative growth rate
            
        bond_yield = 7.5 # 7.5% AAA yield in India
        
        intrinsic_value = 0.0
        margin_of_safety = 0.0
        is_undervalued = False
        
        current_price = info.get("currentPrice") or info.get("previousClose") or 100.0
        
        if eps > 0:
            # Graham formula
            intrinsic_value = (eps * (8.5 + 2 * g) * 4.4) / bond_yield
            # Let's caps check
            intrinsic_value = max(0.0, intrinsic_value)
            
            # Margin of safety = (Intrinsic Value - Price) / Intrinsic Value
            if intrinsic_value > 0:
                margin_of_safety = (intrinsic_value - current_price) / intrinsic_value
                # If margin of safety is positive and greater than 30% (Graham's rule)
                is_undervalued = margin_of_safety >= 0.30
                
        return {
            "roce": round(roce, 4),
            "roe": round(roe, 4),
            "cfo_to_net_income": round(cfo_ni, 4),
            "debt_to_equity": round(debt_to_equity, 4),
            "operating_margin": round(op_margin, 4),
            "ebitda_margin": round(ebitda_margin, 4),
            "margin_stability_std": round(margin_stability, 4),
            "moat_rating": moat_rating,
            "eps": round(eps, 2),
            "growth_rate_assumed": round(g, 2),
            "intrinsic_value": round(intrinsic_value, 2),
            "margin_of_safety": round(margin_of_safety, 4),
            "is_undervalued": is_undervalued,
            "current_price": current_price
        }
        
    @staticmethod
    def generate_buffett_scorecard(val_results: Dict[str, Any], is_financial: bool = False) -> Dict[str, Any]:
        """
        Creates a beginner-friendly quality scorecard checklist.
        """
        scorecard = {}
        
        # ROCE check
        roce = val_results["roce"]
        scorecard["roce_check"] = {
            "value": f"{roce*100:.1f}%",
            "pass": roce >= 0.15,
            "tooltip": "Return on Capital Employed: Measures how efficiently the company uses both debt and equity. Buffett looks for >15%. Higher means high pricing power (Moat)."
        }
        
        # ROE check
        roe = val_results["roe"]
        scorecard["roe_check"] = {
            "value": f"{roe*100:.1f}%",
            "pass": roe >= 0.15,
            "tooltip": "Return on Equity: Measures the return generated on shareholders' capital. Target is >15%. Indicates management's ability to compounding investor money."
        }
        
        # Leverage check
        debt = val_results["debt_to_equity"]
        scorecard["debt_check"] = {
            "value": f"{debt:.2f}" if not is_financial else "N/A (Financials)",
            "pass": debt <= 0.5 or is_financial,
            "tooltip": "Debt-to-Equity: Measures financial risk. Target is <0.5. Buffett avoids heavily leveraged firms because interest expenses drain cash during bad times."
        }
        
        # Cash Flow integrity check
        cfo_ni = val_results["cfo_to_net_income"]
        scorecard["cash_check"] = {
            "value": f"{cfo_ni:.2f}x",
            "pass": cfo_ni >= 1.0,
            "tooltip": "Cash Flow Integrity: Ratio of Operating Cash Flow to Net Income. Should be >1.0. Checks if net profit is actual cash in hand, not accounting paper tricks."
        }
        
        # Operating Margin check
        margin = val_results["operating_margin"]
        scorecard["margin_check"] = {
            "value": f"{margin*100:.1f}%",
            "pass": margin >= 0.15,
            "tooltip": "Operating Margin: Percentage of revenue left after paying variable costs of production. Target is >15%. High margins protect the company from raw material spikes."
        }
        
        passes = sum([1 for k, v in scorecard.items() if v["pass"] or (k == "debt_check" and is_financial)])
        total = len(scorecard)
        scorecard["score"] = passes
        scorecard["total_rules"] = total
        scorecard["verdict"] = "Excellent (Buffett Approved)" if passes >= 4 else "Moderate" if passes >= 2 else "Weak Quality"
        
        return scorecard
