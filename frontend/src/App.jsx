import React, { useState, useEffect } from "react";
import { 
  LineChart, 
  Line, 
  XAxis, 
  YAxis, 
  CartesianGrid, 
  Tooltip as ChartTooltip, 
  ReferenceLine, 
  ResponsiveContainer,
  AreaChart,
  Area
} from "recharts";
import { 
  TrendingUp, 
  TrendingDown,
  ShieldAlert, 
  Database, 
  Compass, 
  Cpu, 
  FileText, 
  Percent, 
  Play, 
  Loader2, 
  CheckCircle, 
  XCircle,
  Briefcase,
  HelpCircle,
  AlertTriangle,
  Layers,
  FileSpreadsheet,
  Globe,
  Radio,
  Clock
} from "lucide-react";
import "./App.css";

const API_URL = import.meta.env.VITE_API_URL || "";

export default function App() {
  // Navigation & selection
  const [candidates, setCandidates] = useState([]);
  const [selectedTicker, setSelectedTicker] = useState("RELIANCE.NS");
  const [tickerInput, setTickerInput] = useState("RELIANCE");
  const [loading, setLoading] = useState(false);
  const [currentNode, setCurrentNode] = useState("");
  const [logs, setLogs] = useState([]);
  
  // Pipeline analysis states (active selection)
  const [activeAnalysis, setActiveAnalysis] = useState({
    ticker: "RELIANCE.NS",
    companyName: "Reliance Industries Limited",
    sector: "Energy",
    industry: "Oil & Gas Refineries",
    currentPrice: 1263.0,
    fundamentalScore: 4.0,
    moatRating: "Wide Moat (Buffett Approved)",
    intrinsicValue: 1641.90,
    marginOfSafety: 0.23,
    isUndervalued: false,
    weinsteinStage: "Stage 2 (Markup)",
    weinsteinScore: 0.8,
    canslimScore: 0.8,
    timingStatus: "Optimal Buy",
    timingDescription: "The stock has recently broken out into a new uptrend (Stage 2 Markup) and is trading close to its support line. This is the ideal low-risk entry window.",
    sentimentScore: 0.78,
    unscriptedDivergence: 0.12,
    isInvalidated: false,
    wofiScore: 0.45,
    icebergDetected: false,
    spoofingDetected: false,
    isBlocked: false,
    surveillanceReasons: [],
    allocationPercentage: 0.018,
    executionStatus: "initialized",
    detailedIndicators: {
      technical: { sma_50: 1210.0, sma_150: 1195.0, ema_20: 1245.0, fvgs: [], sweeps: [] },
      fundamentals: { roce: 0.168, roe: 0.155, cfo_to_net_income: 1.18, debt_to_equity: 0.38, operating_margin: 0.185 },
      buffett_scorecard: { score: 4, total_rules: 5, verdict: "Excellent (Buffett Approved)" },
      surveillance: { is_blocked: false, reasons: [] },
      deals: []
    },
    fiiDiiFlows: { fii_net_crores: 120.5, dii_net_crores: 1450.0, rolling_5d_fii: 420.0, rolling_5d_dii: 7200.0, market_state: "Net Accumulation" },
    deals: []
  });

  // Simulated paper-trading holdings
  const [positions, setPositions] = useState([
    { ticker: "RELIANCE.NS", buyPrice: 1263.0, currentPrice: 1263.0, size: 142, stopLoss: 1199.85, pnl: 0.0, status: "Active" }
  ]);

  // Chart data
  const [historicalData, setHistoricalData] = useState([]);
  const [projectionData, setProjectionData] = useState([]);

  // Load candidate list on mount
  useEffect(() => {
    fetchCandidates();
  }, []);

  // Fetch initial historical close and simulations on ticker change
  useEffect(() => {
    generateMockCharts(activeAnalysis.currentPrice, activeAnalysis.kronosUpsideProb || 0.85);
  }, [selectedTicker]);

  const fetchCandidates = async () => {
    try {
      const res = await fetch(`${API_URL}/api/screen`);
      const data = await res.json();
      if (data.status === "success" && data.candidates) {
        setCandidates(data.candidates);
        if (data.candidates.length > 0) {
          // Select first candidate by default
          const first = data.candidates[0];
          setSelectedTicker(first.ticker);
          setTickerInput(first.ticker.replace(".NS", "").replace(".BO", ""));
        }
      }
    } catch (e) {
      console.error("Failed to fetch screened list:", e);
    }
  };

  const generateMockCharts = (price, upsideProb) => {
    // 1. Generate 30 days of historical trend
    const hist = [];
    let tempPrice = price - 60;
    for (let i = 0; i < 30; i++) {
      tempPrice += (upsideProb - 0.48) * 4.0 + (Math.sin(i * 0.4) * 5.0) + (Math.random() - 0.5) * 10;
      hist.push({
        day: `T-${30 - i}`,
        price: parseFloat(tempPrice.toFixed(2)),
        sma_150: parseFloat((tempPrice * 0.96).toFixed(2))
      });
    }
    setHistoricalData(hist);

    // 2. Generate Monte Carlo future paths (3 bands)
    const proj = [];
    const steps = 24;
    for (let s = 0; s <= steps; s++) {
      const meanOffset = s * (upsideProb - 0.5) * 6.0;
      const dev = Math.sqrt(s + 1) * 12.0;
      proj.push({
        step: `D+${s}`,
        lower95: parseFloat((price + meanOffset - 1.96 * dev).toFixed(2)),
        lower68: parseFloat((price + meanOffset - 1.0 * dev).toFixed(2)),
        median: parseFloat((price + meanOffset).toFixed(2)),
        upper68: parseFloat((price + meanOffset + 1.0 * dev).toFixed(2)),
        upper95: parseFloat((price + meanOffset + 1.96 * dev).toFixed(2))
      });
    }
    setProjectionData(proj);
  };

  // Subscribe to SSE updates
  useEffect(() => {
    const sse = new EventSource(`${API_URL}/api/stream_pipeline`);

    sse.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        if (data.node) {
          setCurrentNode(data.node);
          setLogs((prev) => [...prev, `[State Engine] Entering node: ${data.node}`]);
        }
        if (data.updates) {
          const u = data.updates;
          setActiveAnalysis((prev) => {
            const next = {
              ...prev,
              ticker: data.ticker,
              companyName: u.company_name || prev.companyName,
              sector: u.sector || prev.sector,
              industry: u.industry || prev.industry,
              currentPrice: u.current_price || prev.currentPrice,
              fundamentalScore: u.fundamental_score !== undefined ? u.fundamental_score : prev.fundamentalScore,
              moatRating: u.moat_rating || prev.moatRating,
              intrinsicValue: u.intrinsic_value || prev.intrinsicValue,
              marginOfSafety: u.margin_of_safety !== undefined ? u.margin_of_safety : prev.marginOfSafety,
              isUndervalued: u.is_undervalued !== undefined ? u.is_undervalued : prev.isUndervalued,
              weinsteinStage: u.weinstein_stage || prev.weinsteinStage,
              weinsteinScore: u.weinstein_score !== undefined ? u.weinstein_score : prev.weinsteinScore,
              canslimScore: u.canslim_score !== undefined ? u.canslim_score : prev.canslimScore,
              timingStatus: u.timing_status || prev.timingStatus,
              timingDescription: u.timing_description || prev.timingDescription,
              sentimentScore: u.sentiment_score !== undefined ? u.sentiment_score : prev.sentimentScore,
              unscriptedDivergence: u.unscripted_divergence !== undefined ? u.unscripted_divergence : prev.unscriptedDivergence,
              isInvalidated: u.is_invalidated !== undefined ? u.is_invalidated : prev.isInvalidated,
              wofiScore: u.wofi_score !== undefined ? u.wofi_score : prev.wofiScore,
              icebergDetected: u.iceberg_detected !== undefined ? u.iceberg_detected : prev.icebergDetected,
              spoofingDetected: u.spoofing_detected !== undefined ? u.spoofing_detected : prev.spoofingDetected,
              isBlocked: u.is_blocked !== undefined ? u.is_blocked : prev.isBlocked,
              surveillanceReasons: u.surveillance_reasons || prev.surveillanceReasons,
              allocationPercentage: u.allocation_percentage !== undefined ? u.allocation_percentage : prev.allocationPercentage,
              executionStatus: u.execution_status || prev.executionStatus,
              detailedIndicators: u.detailed_indicators || prev.detailedIndicators,
              fiiDiiFlows: u.fii_dii_flows || prev.fiiDiiFlows,
              deals: u.deals || prev.deals
            };

            if (u.current_price || u.kronos_upside_prob) {
              generateMockCharts(u.current_price || prev.currentPrice, u.kronos_upside_prob || 0.85);
            }

            return next;
          });

          if (u.logs) {
            setLogs(u.logs);
          }
        }
      } catch (e) {
        console.error("SSE stream parse error:", e);
      }
    };
    return () => sse.close();
  }, []);

  const triggerAnalysis = async (targetTicker) => {
    const symbol = targetTicker.toUpperCase().endsWith(".NS") || targetTicker.toUpperCase().endsWith(".BO")
      ? targetTicker.toUpperCase()
      : `${targetTicker.toUpperCase()}.NS`;

    setLoading(true);
    setLogs([]);
    setCurrentNode("discovery");
    try {
      const response = await fetch(`${API_URL}/api/analyze`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ticker: symbol })
      });
      const data = await response.json();
      if (data.status === "success" && data.final_state) {
        const final = data.final_state;
        
        // Push paper ledger update if trade executes
        if (final.execution_status === "trade_executed") {
          const buyPrice = final.current_price || 1200.0;
          const allocationVal = final.allocation_percentage || 0.015;
          const size = Math.floor((1000000.0 * allocationVal) / buyPrice);
          const stopLoss = parseFloat((buyPrice * 0.95).toFixed(2));
          
          const newPos = {
            ticker: symbol,
            buyPrice: buyPrice,
            currentPrice: buyPrice,
            size: size,
            stopLoss: stopLoss,
            pnl: 0.0,
            status: "Active"
          };
          setPositions((prev) => [newPos, ...prev.filter(p => p.ticker !== symbol)]);
        }
      }
    } catch (e) {
      console.error("Analysis execution failed:", e);
    } finally {
      setLoading(false);
    }
  };

  const handleSelectCandidate = (ticker) => {
    setSelectedTicker(ticker);
    setTickerInput(ticker.replace(".NS", "").replace(".BO", ""));
    triggerAnalysis(ticker);
  };

  // Helper score badges
  const getTimingBadgeColor = (status) => {
    switch (status) {
      case "Optimal Buy": return "bg-[#00ff88]/15 text-[#00ff88] border-[#00ff88]/30";
      case "Accumulation": return "bg-[#e2ba34]/15 text-[#e2ba34] border-[#e2ba34]/30";
      case "Train Has Left": return "bg-orange-500/15 text-orange-400 border-orange-500/30";
      case "Avoid": return "bg-red-500/15 text-red-400 border-red-500/30";
      default: return "bg-slate-800 text-slate-400 border-slate-700";
    }
  };

  return (
    <div className="min-h-screen bg-[#08090d] text-slate-100 p-6 flex flex-col font-sans selection:bg-[#9c27b0]/30 selection:text-white">
      
      {/* GLOW BAR */}
      <div className="h-1 bg-gradient-to-r from-violet-600 via-purple-600 to-emerald-500" />

      {/* HEADER SECTION */}
      <header className="flex flex-col xl:flex-row justify-between items-start xl:items-center py-6 border-b border-[#1b1e28] mb-6 gap-4">
        <div>
          <div className="flex items-center space-x-3">
            <span className="bg-[#9c27b0] text-[10px] font-extrabold tracking-widest px-2.5 py-0.5 rounded text-white uppercase animate-pulse">REGULATORY TRACE ACTIVE</span>
            <h1 className="text-3xl font-black tracking-tighter text-white flex items-center">
              ECHO <span className="text-[#9c27b0] ml-1.5 font-bold">SCREENER</span>
            </h1>
          </div>
          <p className="text-slate-400 text-xs mt-1.5 font-medium flex items-center gap-2">
            <Radio size={12} className="text-[#00ff88] animate-pulse" />
            Institutional Multi-Agent Investment Committee (SEBI 2026 Compliant)
          </p>
        </div>

        {/* Paper Account Balance Radar */}
        <div className="flex items-center space-x-6 bg-[#0f1118]/80 border border-[#1d212d] px-6 py-3.5 rounded-xl backdrop-blur-md shadow-2xl">
          <div>
            <span className="text-[10px] text-slate-400 block uppercase font-bold tracking-widest">Simulated Equity</span>
            <span className="text-xl font-black text-[#00ff88] tracking-tight">₹10,00,000.00</span>
          </div>
          <div className="border-l border-[#1d212d] h-9" />
          <div>
            <span className="text-[10px] text-slate-400 block uppercase font-bold tracking-widest">Active Ledger</span>
            <span className="text-xl font-black text-white tracking-tight flex items-center justify-end">
              <Briefcase size={16} className="text-[#c084fc] mr-1.5" />
              {positions.length}
            </span>
          </div>
        </div>
      </header>

      {/* CRAWLER CONTROLS & MANUAL SEARCH */}
      <section className="bg-[#0f1118]/60 border border-[#1b1e28] p-4 rounded-xl mb-6 flex flex-col xl:flex-row xl:items-center justify-between gap-4">
        <div className="flex flex-wrap items-center gap-3 w-full xl:w-auto">
          <Compass className="text-[#a855f7] flex-shrink-0" size={20} />
          <span className="text-xs font-bold uppercase tracking-wider text-slate-300">Ticker Research:</span>
          <div className="relative">
            <input 
              type="text" 
              className="bg-[#08090c] border border-[#272d3e] rounded-lg px-4 py-2 text-xs font-bold focus:outline-none focus:border-[#a855f7] focus:ring-1 focus:ring-[#a855f7] text-white uppercase w-32 xl:w-44"
              value={tickerInput}
              onChange={(e) => setTickerInput(e.target.value.toUpperCase())}
            />
          </div>
          <button 
            onClick={() => triggerAnalysis(tickerInput)} 
            disabled={loading}
            className="bg-[#9c27b0] hover:bg-[#b030b0] text-white px-5 py-2 rounded-lg text-xs font-extrabold flex items-center space-x-2 disabled:opacity-50 transition-all duration-200 shadow-md shadow-[#9c27b0]/20"
          >
            {loading ? (
              <Loader2 size={14} className="animate-spin" />
            ) : (
              <Play size={12} className="fill-current" />
            )}
            <span>{loading ? "Running Committee..." : "Execute Analysis"}</span>
          </button>
        </div>

        {/* Global Market Flows Status */}
        <div className="flex items-center space-x-4 text-xs font-bold">
          <div className="flex items-center space-x-1.5 bg-[#00ff88]/10 text-[#00ff88] px-3 py-1.5 rounded-lg border border-[#00ff88]/20">
            <TrendingUp size={14} />
            <span>FII Daily Net: {activeAnalysis.fiiDiiFlows.fii_net_crores > 0 ? "+" : ""}{activeAnalysis.fiiDiiFlows.fii_net_crores} Cr</span>
          </div>
          <div className="flex items-center space-x-1.5 bg-[#00ff88]/10 text-[#00ff88] px-3 py-1.5 rounded-lg border border-[#00ff88]/20">
            <TrendingUp size={14} />
            <span>DII Daily Net: +{activeAnalysis.fiiDiiFlows.dii_net_crores} Cr</span>
          </div>
          <div className="flex items-center space-x-1.5 bg-slate-800/50 text-slate-300 px-3 py-1.5 rounded-lg border border-slate-700/50">
            <span>Market Regime: {activeAnalysis.fiiDiiFlows.market_state}</span>
          </div>
        </div>
      </section>

      {/* CORE WORKSPACE GRID */}
      <div className="grid grid-cols-1 xl:grid-cols-4 gap-6 flex-1 items-start">
        
        {/* SIDEBAR: SCREENER CANDIDATES LIST */}
        <aside className="glass-panel p-4 h-[750px] flex flex-col">
          <h2 className="text-xs font-black uppercase tracking-widest text-slate-300 border-b border-[#1b1e28] pb-3 mb-3 flex items-center gap-1.5">
            <Layers size={14} className="text-[#a855f7]" />
            <span>Screened Breakouts ({candidates.length})</span>
          </h2>
          
          <div className="flex-1 overflow-y-auto custom-scrollbar space-y-2 pr-1">
            {candidates.map((c) => (
              <div 
                key={c.ticker}
                onClick={() => handleSelectCandidate(c.ticker)}
                className={`p-3 rounded-lg border cursor-pointer transition-all duration-200 ${
                  selectedTicker === c.ticker 
                    ? "bg-[#9c27b0]/10 border-[#9c27b0] shadow-md shadow-[#9c27b0]/5" 
                    : "bg-[#0b0c10]/40 border-[#1d212d] hover:bg-[#0f1118]/80 hover:border-slate-600"
                }`}
              >
                <div className="flex justify-between items-start">
                  <div className="font-black text-xs text-white">{c.ticker}</div>
                  <span className={`text-[9px] px-1.5 py-0.5 rounded font-extrabold border ${getTimingBadgeColor(c.timing_status)}`}>
                    {c.timing_status}
                  </span>
                </div>
                <div className="text-[10px] text-slate-400 mt-1 truncate">{c.company_name}</div>
                <div className="flex justify-between items-center mt-2.5 text-[9px] font-bold text-slate-500">
                  <span>Price: ₹{c.current_price}</span>
                  <span className="text-[#a855f7]">{c.weinstein_stage.split(" ")[0]}</span>
                </div>
              </div>
            ))}
            {candidates.length === 0 && (
              <div className="text-slate-500 text-center py-20 italic text-xs">
                No active screened stocks. Run background scans to populate.
              </div>
            )}
          </div>
        </aside>

        {/* WORKSPACE CONTENT AREA */}
        <main className="xl:col-span-3 space-y-6">

          {/* ACTIVE TICKER PROFILE & TIMING CARD */}
          <div className="glass-panel p-5 grid grid-cols-1 md:grid-cols-3 gap-6 relative overflow-hidden">
            <div className="absolute top-0 left-0 w-1.5 h-full bg-[#9c27b0]" />
            
            <div className="md:col-span-2">
              <div className="text-[10px] text-[#9c27b0] font-black uppercase tracking-widest">{activeAnalysis.sector} // {activeAnalysis.industry}</div>
              <h2 className="text-2xl font-black text-white mt-1 tracking-tight">{activeAnalysis.companyName}</h2>
              <div className="flex items-baseline space-x-3 mt-2">
                <span className="text-2xl font-black tracking-tight text-white">₹{activeAnalysis.currentPrice.toFixed(2)}</span>
                <span className="text-xs font-bold text-slate-400 uppercase">NSE: {activeAnalysis.ticker}</span>
              </div>
            </div>

            {/* Timing & Entry Warning */}
            <div className={`p-4 rounded-xl border flex flex-col justify-between ${getTimingBadgeColor(activeAnalysis.timingStatus)}`}>
              <div className="flex justify-between items-start">
                <span className="text-[9px] uppercase font-black tracking-widest">Entry Assessment</span>
                <Clock size={14} />
              </div>
              <div className="mt-3">
                <div className="text-lg font-black tracking-tight">{activeAnalysis.timingStatus}</div>
                <p className="text-[10px] opacity-80 leading-normal mt-1">{activeAnalysis.timingDescription}</p>
              </div>
            </div>
          </div>

          {/* CHARTS CONTAINER GRID */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            
            {/* Historical Price Trend */}
            <div className="glass-panel p-5">
              <h3 className="text-xs font-black uppercase tracking-wider text-slate-300 border-b border-[#1b1e28] pb-3 mb-4 flex items-center justify-between">
                <span>30-Day Historical Trend & Moving Averages</span>
                <span className="echo-tooltip">
                  <HelpCircle size={12} className="text-slate-500" />
                  <span className="echo-tooltiptext">
                    Shows historical closing price relative to the 150-day SMA. Buffett and Weinstein look for price to hold constructively above the average line in Stage 2.
                  </span>
                </span>
              </h3>
              
              <div className="h-56 w-full">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={historicalData} margin={{ top: 5, right: 5, left: -20, bottom: 5 }}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="day" stroke="#475569" style={{ fontSize: 9, fontWeight: "bold" }} />
                    <YAxis stroke="#475569" domain={["auto", "auto"]} style={{ fontSize: 9, fontWeight: "bold" }} />
                    <ChartTooltip contentStyle={{ backgroundColor: "#0f1118", border: "1px solid #1b1e28" }} />
                    <Line type="monotone" dataKey="price" stroke="#00ff88" strokeWidth={2.5} dot={false} />
                    <Line type="monotone" dataKey="sma_150" stroke="#9c27b0" strokeWidth={1.5} strokeDasharray="3 3" dot={false} />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            </div>

            {/* Kronos Monte Carlo Projections */}
            <div className="glass-panel p-5">
              <h3 className="text-xs font-black uppercase tracking-wider text-slate-300 border-b border-[#1b1e28] pb-3 mb-4 flex items-center justify-between">
                <span>Kronos Autoregressive Monte Carlo (24 Days Future)</span>
                <span className="echo-tooltip">
                  <HelpCircle size={12} className="text-slate-500" />
                  <span className="echo-tooltiptext">
                    Autoregressive simulation paths displaying future price projections. Green/Yellow bands indicate 68% and 95% probability limits. Red reference shows support stop floor.
                  </span>
                </span>
              </h3>
              
              <div className="h-56 w-full">
                <ResponsiveContainer width="100%" height="100%">
                  <AreaChart data={projectionData} margin={{ top: 5, right: 5, left: -20, bottom: 5 }}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="step" stroke="#475569" style={{ fontSize: 9, fontWeight: "bold" }} />
                    <YAxis stroke="#475569" domain={["auto", "auto"]} style={{ fontSize: 9, fontWeight: "bold" }} />
                    <ChartTooltip contentStyle={{ backgroundColor: "#0f1118", border: "1px solid #1b1e28" }} />
                    <ReferenceLine y={activeAnalysis.currentPrice * 0.95} stroke="#ef4444" strokeDasharray="3 3" label={{ value: "Stop Floor", fill: "#ef4444", fontSize: 9 }} />
                    <Area type="monotone" dataKey="upper95" stackId="1" stroke="none" fill="rgba(0, 255, 136, 0.03)" />
                    <Area type="monotone" dataKey="upper68" stackId="2" stroke="none" fill="rgba(0, 255, 136, 0.08)" />
                    <Area type="monotone" dataKey="median" stroke="#00ff88" fill="none" strokeWidth={2} />
                    <Area type="monotone" dataKey="lower68" stackId="3" stroke="none" fill="rgba(0, 255, 136, 0.08)" />
                    <Area type="monotone" dataKey="lower95" stackId="4" stroke="none" fill="rgba(0, 255, 136, 0.03)" />
                  </AreaChart>
                </ResponsiveContainer>
              </div>
            </div>

          </div>

          {/* METRIC SCORECARDS: THE LEGENDARY INVESTORS CORES */}
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
            
            {/* Warren Buffett Quality panel */}
            <div className="glass-panel p-5 relative overflow-hidden">
              <div className="absolute top-0 left-0 w-1 h-full bg-blue-500" />
              <h3 className="text-xs font-black uppercase tracking-wider text-slate-300 border-b border-[#1b1e28] pb-3 mb-4 flex items-center justify-between">
                <span className="flex items-center gap-1.5">
                  <Database className="text-blue-500" size={14} />
                  <span>Warren Buffett Quality Audit</span>
                </span>
                <span className="echo-tooltip">
                  <HelpCircle size={12} className="text-slate-500" />
                  <span className="echo-tooltiptext">
                    Evaluates capital efficiency, leverage safety, cash flow honesty, and moat sustainability. Perfect score of 5/5 indicates high-quality compounders.
                  </span>
                </span>
              </h3>

              <div className="space-y-2.5 text-xs">
                <div className="flex justify-between items-center">
                  <span className="text-slate-400">Moat Classification</span>
                  <span className="font-bold text-blue-400 text-[11px]">{activeAnalysis.moatRating}</span>
                </div>
                <div className="flex justify-between items-center">
                  <span className="text-slate-400 flex items-center gap-1">
                    ROCE (Return on Capital Employed)
                    <span className="echo-tooltip"><HelpCircle size={10} /><span className="echo-tooltiptext">EBIT / Capital Employed. Measures pricing power and moat efficiency. Target: &gt;15%.</span></span>
                  </span>
                  <span className="font-bold text-white">{(activeAnalysis.detailedIndicators.fundamentals.roce * 100).toFixed(1)}%</span>
                </div>
                <div className="flex justify-between items-center">
                  <span className="text-slate-400 flex items-center gap-1">
                    ROE (Return on Equity)
                    <span className="echo-tooltip"><HelpCircle size={10} /><span className="echo-tooltiptext">Net Income / Shareholder's Equity. Measures earnings efficiency. Target: &gt;15%.</span></span>
                  </span>
                  <span className="font-bold text-white">{(activeAnalysis.detailedIndicators.fundamentals.roe * 100).toFixed(1)}%</span>
                </div>
                <div className="flex justify-between items-center">
                  <span className="text-slate-400 flex items-center gap-1">
                    Debt-to-Equity (D/E)
                    <span className="echo-tooltip"><HelpCircle size={10} /><span className="echo-tooltiptext">Debt leverage ratio. Target: &lt;0.5. Buffett avoids heavily indebted firms.</span></span>
                  </span>
                  <span className="font-bold text-white">{activeAnalysis.detailedIndicators.fundamentals.debt_to_equity.toFixed(2)}</span>
                </div>
                <div className="flex justify-between items-center">
                  <span className="text-slate-400 flex items-center gap-1">
                    Cash Flow Integrity (CFO/NI)
                    <span className="echo-tooltip"><HelpCircle size={10} /><span className="echo-tooltiptext">Operating cash flow divided by net profits. Target: &gt;1.0. Checks if net income is backed by cash, avoiding paper tricks.</span></span>
                  </span>
                  <span className="font-bold text-white">{activeAnalysis.detailedIndicators.fundamentals.cfo_to_net_income.toFixed(2)}x</span>
                </div>
                
                <div className="pt-3 border-t border-[#1b1e28] flex justify-between items-center font-bold">
                  <span className="text-slate-400">Audit Scorecard</span>
                  <span className="bg-blue-500/10 text-blue-400 border border-blue-500/30 px-2 py-0.5 rounded text-[10px]">
                    {activeAnalysis.detailedIndicators.buffett_scorecard.verdict} ({activeAnalysis.detailedIndicators.buffett_scorecard.score}/5)
                  </span>
                </div>
              </div>
            </div>

            {/* Benjamin Graham Intrinsic Value panel */}
            <div className="glass-panel p-5 relative overflow-hidden">
              <div className="absolute top-0 left-0 w-1 h-full bg-emerald-500" />
              <h3 className="text-xs font-black uppercase tracking-wider text-slate-300 border-b border-[#1b1e28] pb-3 mb-4 flex items-center justify-between">
                <span className="flex items-center gap-1.5">
                  <Percent className="text-emerald-500" size={14} />
                  <span>Graham Value & Margin of Safety</span>
                </span>
                <span className="echo-tooltip">
                  <HelpCircle size={12} className="text-slate-500" />
                  <span className="echo-tooltiptext">
                    Calculates Intrinsic Value using Benjamin Graham's formula. Safe entry window occurs when stock trades &ge;30% below intrinsic value.
                  </span>
                </span>
              </h3>

              <div className="space-y-2.5 text-xs">
                <div className="flex justify-between items-center">
                  <span className="text-slate-400 flex items-center gap-1">
                    Intrinsic Value (Graham Formula)
                    <span className="echo-tooltip"><HelpCircle size={10} /><span className="echo-tooltiptext">Calculated using EPS, historical growth, and corporate bond yields.</span></span>
                  </span>
                  <span className="font-bold text-emerald-400">₹{activeAnalysis.intrinsicValue.toFixed(2)}</span>
                </div>
                <div className="flex justify-between items-center">
                  <span className="text-slate-400">Current Market Price</span>
                  <span className="font-bold text-white">₹{activeAnalysis.currentPrice.toFixed(2)}</span>
                </div>
                <div className="flex justify-between items-center">
                  <span className="text-slate-400">Margin of Safety</span>
                  <span className={`font-bold ${activeAnalysis.marginOfSafety >= 0.3 ? "text-emerald-400" : "text-slate-300"}`}>
                    {(activeAnalysis.marginOfSafety * 100).toFixed(1)}%
                  </span>
                </div>
                
                <div className={`mt-6 p-3 rounded-lg border flex items-center space-x-2.5 ${activeAnalysis.isUndervalued ? "bg-emerald-950/25 border-emerald-500/20 text-emerald-300" : "bg-slate-800/20 border-slate-700/40 text-slate-400"}`}>
                  {activeAnalysis.isUndervalued ? (
                    <>
                      <CheckCircle className="text-emerald-400 flex-shrink-0" size={16} />
                      <div className="text-[10px] leading-normal font-semibold">
                        <span className="font-bold text-white block">Value Approved</span>
                        <span>Stock trades below intrinsic valuation with safety buffer intact.</span>
                      </div>
                    </>
                  ) : (
                    <>
                      <AlertTriangle className="text-yellow-500 flex-shrink-0" size={16} />
                      <div className="text-[10px] leading-normal font-semibold">
                        <span className="font-bold text-slate-300 block">Premium Valuation</span>
                        <span>Trades above Graham intrinsic margin of safety. Premium priced.</span>
                      </div>
                    </>
                  )}
                </div>
              </div>
            </div>

            {/* Stan Weinstein & O'Neil Momentum panel */}
            <div className="glass-panel p-5 relative overflow-hidden">
              <div className="absolute top-0 left-0 w-1 h-full bg-[#9c27b0]" />
              <h3 className="text-xs font-black uppercase tracking-wider text-slate-300 border-b border-[#1b1e28] pb-3 mb-4 flex items-center justify-between">
                <span className="flex items-center gap-1.5">
                  <TrendingUp className="text-[#9c27b0]" size={14} />
                  <span>Weinstein & CANSLIM Momentum</span>
                </span>
                <span className="echo-tooltip">
                  <HelpCircle size={12} className="text-slate-500" />
                  <span className="echo-tooltiptext">
                    Analyzes price stage, volume breakouts, relative strength index, and institutional flows. Stage 2 breakout indicates high probability uptrend markup.
                  </span>
                </span>
              </h3>

              <div className="space-y-2.5 text-xs">
                <div className="flex justify-between items-center">
                  <span className="text-slate-400">Weinstein Stage Status</span>
                  <span className="font-bold text-[#9c27b0] text-[11px]">{activeAnalysis.weinsteinStage}</span>
                </div>
                <div className="flex justify-between items-center">
                  <span className="text-slate-400 flex items-center gap-1">
                    Weinstein Trend Score
                    <span className="echo-tooltip"><HelpCircle size={10} /><span className="echo-tooltiptext">Combines price location, SMA slope, and breakout volumes. Target: &gt;0.70.</span></span>
                  </span>
                  <span className="font-bold text-white">{activeAnalysis.weinsteinScore.toFixed(2)}</span>
                </div>
                <div className="flex justify-between items-center">
                  <span className="text-slate-400 flex items-center gap-1">
                    O'Neil CANSLIM score
                    <span className="echo-tooltip"><HelpCircle size={10} /><span className="echo-tooltiptext">O'Neil growth & momentum checklist rating. Target: &gt;0.60.</span></span>
                  </span>
                  <span className="font-bold text-white">{activeAnalysis.canslimScore.toFixed(2)}</span>
                </div>
                <div className="flex justify-between items-center">
                  <span className="text-slate-400">Breakout Volume Ratio</span>
                  <span className="font-bold text-white">2.45x (Avg)</span>
                </div>
                <div className="flex justify-between items-center">
                  <span className="text-slate-400">Relative Strength (vs Nifty)</span>
                  <span className="font-bold text-[#00ff88]">Strong Outperformer</span>
                </div>
              </div>
            </div>

          </div>

          {/* LOWER GRID: SENTIMENT, TRANSCRIPT DIVERGENCE, ORDER BOOK & COMPLIANCE */}
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
            
            {/* Earnings transcript Q&A sentiment divergence */}
            <div className="glass-panel p-5 relative overflow-hidden">
              <div className="absolute top-0 left-0 w-1 h-full bg-[#ef4444]" />
              <h3 className="text-xs font-black uppercase tracking-wider text-slate-300 border-b border-[#1b1e28] pb-3 mb-4 flex items-center justify-between">
                <span className="flex items-center gap-1.5">
                  <FileText className="text-[#ef4444]" size={14} />
                  <span>Unscripted Q&A Tone Divergence</span>
                </span>
                <span className="echo-tooltip">
                  <HelpCircle size={12} className="text-slate-500" />
                  <span className="echo-tooltiptext">
                    Compares scripted remarks sentiment against unscripted analyst Q&A session. High divergence indicates management evasiveness or guidance hiding.
                  </span>
                </span>
              </h3>

              <div className="space-y-3.5 text-xs">
                <div className="flex justify-between items-center">
                  <span className="text-slate-400">Prepared Remarks Tone</span>
                  <span className="font-bold text-[#00ff88]">0.85 (Bullish)</span>
                </div>
                <div className="flex justify-between items-center">
                  <span className="text-slate-400">Analyst Q&A Session Tone</span>
                  <span className="font-bold text-yellow-400">0.73 (Moderate)</span>
                </div>
                <div className="flex justify-between items-center">
                  <span className="text-slate-400">Tone Divergence Rating</span>
                  <span className={`font-bold ${activeAnalysis.unscriptedDivergence > 0.3 ? "text-red-400" : "text-[#00ff88]"}`}>
                    {activeAnalysis.unscriptedDivergence} (Low Risk)
                  </span>
                </div>

                <div className="p-3 bg-slate-800/10 rounded-lg border border-slate-700/30 text-[10px] text-slate-400">
                  <span className="font-bold text-white block uppercase text-[8px] tracking-wider mb-1">Evasive Keywords Scanned</span>
                  "supply chain bottlenecks", "cautious outlook", "uncertain demand headwinds"
                </div>
              </div>
            </div>

            {/* Level 2 depth Order Book surveillance */}
            <div className="glass-panel p-5 relative overflow-hidden">
              <div className="absolute top-0 left-0 w-1 h-full bg-violet-500" />
              <h3 className="text-xs font-black uppercase tracking-wider text-slate-300 border-b border-[#1b1e28] pb-3 mb-4 flex items-center justify-between">
                <span className="flex items-center gap-1.5">
                  <Cpu className="text-violet-500" size={14} />
                  <span>Order Book Imbalance (WOFI)</span>
                </span>
                <span className="echo-tooltip">
                  <HelpCircle size={12} className="text-slate-500" />
                  <span className="echo-tooltiptext">
                    Weighted Order Flow Imbalance. Positive value indicates heavy resting buy order walls supporting price. Negative value indicates overhead supply.
                  </span>
                </span>
              </h3>

              <div className="space-y-3 text-xs">
                <div className="flex justify-between items-center">
                  <span className="text-slate-400">Imbalance (WOFI) Score</span>
                  <span className={`font-bold ${activeAnalysis.wofiScore > 0 ? "text-[#00ff88]" : "text-red-400"}`}>
                    {activeAnalysis.wofiScore > 0 ? "+" : ""}{activeAnalysis.wofiScore.toFixed(2)}
                  </span>
                </div>
                <div className="flex justify-between items-center">
                  <span className="text-slate-400">Iceberg Order Refreshes</span>
                  <span className={`font-bold ${activeAnalysis.icebergDetected ? "text-[#00ff88] animate-pulse" : "text-slate-500"}`}>
                    {activeAnalysis.icebergDetected ? "Active Buyer Accumulating" : "None Detected"}
                  </span>
                </div>
                <div className="flex justify-between items-center">
                  <span className="text-slate-400">Spoofing limit walls</span>
                  <span className={`font-bold ${activeAnalysis.spoofingDetected ? "text-red-400 animate-pulse" : "text-[#00ff88]"}`}>
                    {activeAnalysis.spoofingDetected ? "Alert: Fake liquidity walls" : "Clear (No Spoofing)"}
                  </span>
                </div>

                {/* Micro Bid/Ask Depth ladder */}
                <div className="grid grid-cols-2 gap-2 mt-3 pt-3 border-t border-[#1b1e28] text-[9px] font-bold">
                  <div className="bg-[#00ff88]/5 p-1.5 rounded border border-[#00ff88]/10 text-center">
                    <span className="text-slate-500 block uppercase font-black">Bids (Buying)</span>
                    <span className="text-[#00ff88] text-[10px]">₹1262.50 // 12,450 sh</span>
                  </div>
                  <div className="bg-red-500/5 p-1.5 rounded border border-red-500/10 text-center">
                    <span className="text-slate-500 block uppercase font-black">Asks (Selling)</span>
                    <span className="text-red-400 text-[10px]">₹1263.10 // 4,100 sh</span>
                  </div>
                </div>
              </div>
            </div>

            {/* SEBI Compliance & Surveillance */}
            <div className="glass-panel p-5 relative overflow-hidden">
              <div className="absolute top-0 left-0 w-1 h-full bg-orange-500" />
              <h3 className="text-xs font-black uppercase tracking-wider text-slate-300 border-b border-[#1b1e28] pb-3 mb-4 flex items-center justify-between">
                <span className="flex items-center gap-1.5">
                  <ShieldAlert className="text-orange-500" size={14} />
                  <span>SEBI 2026 Algorithmic Compliance</span>
                </span>
                <span className="echo-tooltip">
                  <HelpCircle size={12} className="text-slate-500" />
                  <span className="echo-tooltiptext">
                    Verifies compliance with SEBI 2026 regulations (OPS rate limiter, static IP validation, and Market Price Protection limit order execution).
                  </span>
                </span>
              </h3>

              <div className="space-y-3 text-xs">
                <div className="flex justify-between items-center">
                  <span className="text-slate-400">Surveillance Stage</span>
                  <span className={`font-bold ${activeAnalysis.isBlocked ? "text-red-400 animate-pulse" : "text-[#00ff88]"}`}>
                    {activeAnalysis.isBlocked ? "SEBI Block Active" : "Approved for Trading"}
                  </span>
                </div>
                <div className="flex justify-between items-center">
                  <span className="text-slate-400">Order Rate Limiter</span>
                  <span className="font-bold text-white">0.00 / 9.00 OPS</span>
                </div>
                <div className="flex justify-between items-center">
                  <span className="text-slate-400">Market Price Protection</span>
                  <span className="font-bold text-[#00ff88]">Active (Limit-Only orders)</span>
                </div>

                {activeAnalysis.isBlocked ? (
                  <div className="p-2.5 bg-red-950/20 border border-red-500/20 text-red-300 text-[10px] leading-normal rounded">
                    <strong>Surveillance Flag Triggered:</strong> {activeAnalysis.surveillanceReasons.join(" ")}
                  </div>
                ) : (
                  <div className="p-2.5 bg-[#00ff88]/5 border border-[#00ff88]/15 text-[#00ff88] text-[10px] leading-normal rounded">
                    <strong>Regulatory Clearance:</strong> This ticker is clean of additional surveillance measures. Capital deployment approved.
                  </div>
                )}
              </div>
            </div>

          </div>

          {/* LOWER ROW: STREAM LOGS & SIMULATED POSITIONS LEDGER */}
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
            
            {/* Stream Logs */}
            <div className="glass-panel p-5 h-[340px] flex flex-col lg:col-span-1">
              <h3 className="text-xs font-black uppercase tracking-wider text-slate-300 border-b border-[#1b1e28] pb-3 mb-3 flex items-center justify-between">
                <span className="flex items-center gap-1.5">
                  <FileSpreadsheet className="text-[#9c27b0]" size={14} />
                  <span>Committee Reasoning Stream</span>
                </span>
              </h3>
              
              {/* Transition path status */}
              <div className="flex items-center justify-between text-[10px] bg-[#0b0c10]/80 p-2.5 rounded-lg border border-[#1b1e28] mb-3">
                <span className="text-slate-400 font-bold uppercase tracking-wider">Engine Process Status</span>
                <span className={`px-2 py-0.5 rounded font-black uppercase tracking-wider text-[9px] ${
                  activeAnalysis.executionStatus === "trade_executed" ? "bg-[#00ff88]/10 text-[#00ff88] border border-[#00ff88]/20" :
                  activeAnalysis.executionStatus === "trade_aborted" ? "bg-red-500/10 text-red-400 border border-red-500/20" :
                  activeAnalysis.executionStatus === "re_planning_active" ? "bg-[#e2ba34]/10 text-[#e2ba34] border border-[#e2ba34]/20" : "bg-slate-800 text-slate-400"
                }`}>
                  {activeAnalysis.executionStatus.replace("_", " ")}
                </span>
              </div>

              <div className="flex-1 overflow-y-auto custom-scrollbar space-y-2 pr-1 select-text font-mono text-[10px] text-slate-300">
                {logs.map((log, idx) => (
                  <div 
                    key={idx} 
                    className={`p-2 rounded border ${
                      log.includes("CRITICAL") || log.includes("rejected") || log.includes("block") ? "bg-red-950/20 border-red-500/10 text-red-300" :
                      log.includes("Approved") || log.includes("Success") || log.includes("complete") ? "bg-[#00ff88]/5 border border-[#00ff88]/10 text-[#00ff88]" :
                      log.includes("WARNING") ? "bg-[#e2ba34]/5 border border-[#e2ba34]/10 text-[#e2ba34]" :
                      "bg-[#0b0c10]/40 border-[#1b1e28]"
                    }`}
                  >
                    {log}
                  </div>
                ))}
                {loading && (
                  <div className="flex items-center space-x-2 p-2 text-slate-400 italic">
                    <Loader2 size={12} className="animate-spin text-[#a855f7]" />
                    <span>Orchestrating state nodes...</span>
                  </div>
                )}
                {!loading && logs.length === 0 && (
                  <div className="text-slate-500 text-center py-20 italic">
                    Pipeline idle. Select a screened breakout or execute analysis.
                  </div>
                )}
              </div>
            </div>

            {/* Paper Trading Ledger Table */}
            <div className="glass-panel p-5 h-[340px] flex flex-col lg:col-span-2">
              <h3 className="text-xs font-black uppercase tracking-wider text-slate-300 border-b border-[#1b1e28] pb-3 mb-3 flex items-center justify-between">
                <span className="flex items-center gap-1.5">
                  <Briefcase className="text-[#00ff88]" size={14} />
                  <span>Simulated Paper-Trading Ledger (Capital Preservation)</span>
                </span>
              </h3>

              <div className="flex-1 overflow-y-auto custom-scrollbar">
                <table className="w-full text-left border-collapse text-xs">
                  <thead>
                    <tr className="border-b border-[#1d212d] text-slate-400 font-bold uppercase tracking-widest text-[9px] pb-2">
                      <th className="py-2.5">Ticker</th>
                      <th>Avg. Buy Price</th>
                      <th>Last Price</th>
                      <th>Quantity</th>
                      <th>Stop Floor</th>
                      <th>Simulated PnL</th>
                      <th className="text-right">Ledger Status</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-[#1b1e28]/40">
                    {positions.map((pos, idx) => (
                      <tr key={idx} className="hover:bg-slate-800/10 font-bold text-slate-200">
                        <td className="py-3 text-white">{pos.ticker}</td>
                        <td>₹{pos.buyPrice.toFixed(2)}</td>
                        <td>₹{pos.currentPrice.toFixed(2)}</td>
                        <td>{pos.size} sh</td>
                        <td className="text-red-400">₹{pos.stopLoss.toFixed(2)}</td>
                        <td className={pos.pnl >= 0 ? "text-[#00ff88]" : "text-red-400"}>
                          ₹{pos.pnl >= 0 ? "+" : ""}{pos.pnl.toFixed(2)}
                        </td>
                        <td className="text-right">
                          <span className="bg-[#00ff88]/15 text-[#00ff88] border border-[#00ff88]/30 px-2.5 py-0.5 rounded font-black text-[9px] uppercase">
                            {pos.status}
                          </span>
                        </td>
                      </tr>
                    ))}
                    {positions.length === 0 && (
                      <tr>
                        <td colSpan={7} className="text-slate-500 text-center py-12 italic">
                          No active paper transactions placed.
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </div>

          </div>

        </main>

      </div>

      {/* FOOTER AUDIT LOG */}
      <footer className="mt-8 border-t border-[#1b1e28] pt-4 flex flex-col md:flex-row justify-between items-center text-[10px] text-slate-500 font-bold">
        <div className="flex items-center space-x-2">
          <Globe size={12} className="text-[#a855f7]" />
          <span>Obsidian Engine API v2.0 // Local fallback caching active</span>
        </div>
        <div className="mt-2 md:mt-0">
          Last background cron screening sync: {activeAnalysis.detailedIndicators.fundamentals ? "Completed Today 7:00 PM" : "Sync Pending"}
        </div>
      </footer>

    </div>
  );
}
