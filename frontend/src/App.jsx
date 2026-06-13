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
  Area,
  BarChart,
  Bar,
  Legend
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
  Clock,
  Plus,
  Trash2,
  Newspaper,
  ShieldCheck,
  Flame,
  Activity,
  Settings
} from "lucide-react";
import "./App.css";

const API_URL = import.meta.env.VITE_API_URL || "http://127.0.0.1:8000";

export default function App() {
  // Navigation & tabs
  const [activeTab, setActiveTab] = useState("committee"); // committee | conviction | news | sectors | journal | operations
  const [candidates, setCandidates] = useState([]);
  const [selectedTicker, setSelectedTicker] = useState("RELIANCE.NS");
  const [tickerInput, setTickerInput] = useState("RELIANCE");
  const [loading, setLoading] = useState(false);
  const [currentNode, setCurrentNode] = useState("");
  const [logs, setLogs] = useState([]);
  
  // Real historical and simulation data states
  const [historicalData, setHistoricalData] = useState([]);
  const [projectionData, setProjectionData] = useState([]);
  const [simulationStats, setSimulationStats] = useState({ upsideProb: 0.5, volRisk: 0.0, isSafe: false });
  const [historyLoading, setHistoryLoading] = useState(false);
  const [simLoading, setSimLoading] = useState(false);

  // Conviction list & overrides
  const [convictionList, setConvictionList] = useState([]);
  const [activeOverrides, setActiveOverrides] = useState([]);
  const [convictionLoading, setConvictionLoading] = useState(false);

  // News signals & material catalysts
  const [newsSignals, setNewsSignals] = useState([]);
  const [materialCatalysts, setMaterialCatalysts] = useState([]);
  const [newsLoading, setNewsLoading] = useState(false);

  // Sector rotation & Insiders
  const [sectorHeatmap, setSectorHeatmap] = useState([]);
  const [insiderFeed, setInsiderFeed] = useState([]);
  const [sectorsLoading, setSectorsLoading] = useState(false);
  const [insiderLoading, setInsiderLoading] = useState(false);

  // Trade journal ledger
  const [journalEntries, setJournalEntries] = useState([]);
  const [journalLoading, setJournalLoading] = useState(false);
  const [journalForm, setJournalForm] = useState({
    symbol: "",
    entry_date: new Date().toISOString().split("T")[0],
    entry_price: "",
    quantity: "",
    conviction_score: 75,
    catalyst: "",
    stop_loss: "",
    target_price: ""
  });
  const [exitForm, setExitForm] = useState({
    trade_id: "",
    exit_date: new Date().toISOString().split("T")[0],
    exit_price: "",
    outcome_notes: ""
  });
  const [showExitModal, setShowExitModal] = useState(false);

  // Operations panel execution logs
  const [operationLogs, setOperationLogs] = useState({});
  const [runningOperations, setRunningOperations] = useState({});

  // Active LangGraph analysis state
  const [activeAnalysis, setActiveAnalysis] = useState({
    ticker: "RELIANCE.NS",
    companyName: "Reliance Industries Limited",
    sector: "Energy",
    industry: "Oil & Gas Refineries",
    currentPrice: 1263.0,
    fundamentalScore: 0,
    moatRating: "N/A",
    intrinsicValue: 0,
    marginOfSafety: 0,
    isUndervalued: false,
    weinsteinStage: "N/A",
    weinsteinScore: 0,
    canslimScore: 0,
    timingStatus: "Neutral",
    timingDescription: "",
    sentimentScore: 0.5,
    unscriptedDivergence: 0,
    isInvalidated: false,
    wofiScore: 0,
    icebergDetected: false,
    spoofingDetected: false,
    isBlocked: false,
    surveillanceReasons: [],
    allocationPercentage: 0,
    executionStatus: "idle",
    detailedIndicators: {
      technical: { sma_50: 0, sma_150: 0, ema_20: 0, fvgs: [], sweeps: [] },
      fundamentals: { roce: 0, roe: 0, cfo_to_net_income: 0, debt_to_equity: 0, operating_margin: 0 },
      buffett_scorecard: { score: 0, total_rules: 5, verdict: "Pending Run" },
      surveillance: { is_blocked: false, reasons: [] },
      deals: []
    },
    fiiDiiFlows: { fii_net_crores: 0, dii_net_crores: 0, rolling_5d_fii: 0, rolling_5d_dii: 0, market_state: "N/A" }
  });

  // System general metrics
  const [simulatedBalance, setSimulatedBalance] = useState(1000000.0);

  // Synchronous initial fetches
  useEffect(() => {
    fetchCandidates();
    fetchJournal();
  }, []);

  // Fetch history and run simulations when ticker changes
  useEffect(() => {
    if (selectedTicker) {
      fetchHistory(selectedTicker);
      fetchSimulation(selectedTicker);
    }
  }, [selectedTicker]);

  // Fetch tab-specific data when active tab changes
  useEffect(() => {
    if (activeTab === "conviction") {
      fetchConviction();
      fetchOverrides();
    } else if (activeTab === "news") {
      fetchNewsSignals();
      fetchCatalysts();
    } else if (activeTab === "sectors") {
      fetchSectors();
      fetchInsiders();
    }
  }, [activeTab]);

  // Stream LangGraph SSE updates
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
              fiiDiiFlows: u.fii_dii_flows || prev.fiiDiiFlows
            };
            return next;
          });

          if (u.logs) {
            setLogs((prev) => [...prev, ...u.logs.filter(l => !prev.includes(l))]);
          }
        }
      } catch (e) {
        console.error("SSE stream parse error:", e);
      }
    };
    return () => sse.close();
  }, []);

  // API Call Helpers
  const fetchCandidates = async () => {
    try {
      const res = await fetch(`${API_URL}/api/screen`);
      const data = await res.json();
      if (data.status === "success" && data.candidates) {
        setCandidates(data.candidates);
        if (data.candidates.length > 0 && !selectedTicker) {
          setSelectedTicker(data.candidates[0].ticker);
        }
      }
    } catch (e) {
      console.error("Failed to fetch screened list:", e);
    }
  };

  const fetchHistory = async (symbol) => {
    setHistoryLoading(true);
    try {
      const res = await fetch(`${API_URL}/api/history/${symbol}`);
      const data = await res.json();
      if (data.status === "success" && data.history) {
        // Map keys to display names
        const formatted = data.history.map(item => ({
          day: item.trade_date,
          price: item.close,
          open: item.open,
          high: item.high,
          low: item.low,
          volume: item.volume,
          delivery_pct: item.delivery_pct * 100
        }));
        setHistoricalData(formatted);
      }
    } catch (e) {
      console.error("Failed to fetch history:", e);
    } finally {
      setHistoryLoading(false);
    }
  };

  const fetchSimulation = async (symbol) => {
    setSimLoading(true);
    try {
      const res = await fetch(`${API_URL}/api/simulate/${symbol}`);
      const data = await res.json();
      if (data.status === "success" && data.paths) {
        setSimulationStats({
          upsideProb: data.upside_probability,
          volRisk: data.volatility_amplification,
          isSafe: data.is_safe
        });
        
        // Convert paths list [ [ {close, volume...}, ...], ... ] into step-based recharts structure
        const stepsCount = data.paths[0].length;
        const formatted = [];
        for (let s = 0; s < stepsCount; s++) {
          formatted.push({
            step: `D+${s + 1}`,
            pathA: data.paths[0][s].close,
            pathB: data.paths[1][s].close,
            pathC: data.paths[2][s].close
          });
        }
        setProjectionData(formatted);
      }
    } catch (e) {
      console.error("Failed to fetch simulation:", e);
    } finally {
      setSimLoading(false);
    }
  };

  const fetchConviction = async () => {
    setConvictionLoading(true);
    try {
      const res = await fetch(`${API_URL}/api/conviction`);
      const data = await res.json();
      if (data.status === "success" && data.results) {
        setConvictionList(data.results);
      }
    } catch (e) {
      console.error("Failed to fetch conviction leaderboard:", e);
    } finally {
      setConvictionLoading(false);
    }
  };

  const fetchOverrides = async () => {
    try {
      const res = await fetch(`${API_URL}/api/news/overrides`);
      const data = await res.json();
      if (data.status === "success" && data.overrides) {
        setActiveOverrides(data.overrides);
      }
    } catch (e) {
      console.error("Failed to fetch active overrides:", e);
    }
  };

  const fetchNewsSignals = async () => {
    setNewsLoading(true);
    try {
      const res = await fetch(`${API_URL}/api/news/signals`);
      const data = await res.json();
      if (data.status === "success" && data.signals) {
        setNewsSignals(data.signals);
      }
    } catch (e) {
      console.error("Failed to fetch news signals:", e);
    } finally {
      setNewsLoading(false);
    }
  };

  const fetchCatalysts = async () => {
    try {
      const res = await fetch(`${API_URL}/api/news/catalysts`);
      const data = await res.json();
      if (data.status === "success" && data.catalysts) {
        setMaterialCatalysts(data.catalysts);
      }
    } catch (e) {
      console.error("Failed to fetch material catalysts:", e);
    }
  };

  const fetchSectors = async () => {
    setSectorsLoading(true);
    try {
      const res = await fetch(`${API_URL}/api/sectors`);
      const data = await res.json();
      if (data.status === "success" && data.sectors) {
        setSectorHeatmap(data.sectors);
      }
    } catch (e) {
      console.error("Failed to fetch sector heatmap:", e);
    } finally {
      setSectorsLoading(false);
    }
  };

  const fetchInsiders = async () => {
    setInsiderLoading(true);
    try {
      const res = await fetch(`${API_URL}/api/insiders`);
      const data = await res.json();
      if (data.status === "success" && data.disclosures) {
        setInsiderFeed(data.disclosures);
      }
    } catch (e) {
      console.error("Failed to fetch insider feed:", e);
    } finally {
      setInsiderLoading(false);
    }
  };

  const fetchJournal = async () => {
    setJournalLoading(true);
    try {
      const res = await fetch(`${API_URL}/api/journal`);
      const data = await res.json();
      if (data.status === "success" && data.entries) {
        setJournalEntries(data.entries);
        // Recalculate virtual balance based on realized PnL
        const closedRealized = data.entries
          .filter(e => e.exit_date !== null)
          .reduce((sum, item) => sum + parseFloat(item.pnl || 0), 0);
        setSimulatedBalance(1000000.0 + closedRealized);
      }
    } catch (e) {
      console.error("Failed to fetch journal entries:", e);
    } finally {
      setJournalLoading(false);
    }
  };

  // Execution actions
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
      if (data.status === "success") {
        fetchJournal();
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

  // Journal handlers
  const handleLogTrade = async (e) => {
    e.preventDefault();
    try {
      const response = await fetch(`${API_URL}/api/journal`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          symbol: journalForm.symbol.toUpperCase().endsWith(".NS") ? journalForm.symbol.toUpperCase() : `${journalForm.symbol.toUpperCase()}.NS`,
          entry_date: journalForm.entry_date,
          entry_price: parseFloat(journalForm.entry_price),
          quantity: parseInt(journalForm.quantity),
          conviction_score: parseInt(journalForm.conviction_score),
          catalyst: journalForm.catalyst,
          stop_loss: parseFloat(journalForm.stop_loss),
          target_price: journalForm.target_price ? parseFloat(journalForm.target_price) : null
        })
      });
      if (response.ok) {
        fetchJournal();
        setJournalForm({
          symbol: "",
          entry_date: new Date().toISOString().split("T")[0],
          entry_price: "",
          quantity: "",
          conviction_score: 75,
          catalyst: "",
          stop_loss: "",
          target_price: ""
        });
      } else {
        const error = await response.json();
        alert(`Error: ${error.detail}`);
      }
    } catch (e) {
      console.error("Failed to log trade:", e);
    }
  };

  const handleExitTrade = async (e) => {
    e.preventDefault();
    try {
      const response = await fetch(`${API_URL}/api/journal/exit`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          trade_id: exitForm.trade_id,
          exit_date: exitForm.exit_date,
          exit_price: parseFloat(exitForm.exit_price),
          outcome_notes: exitForm.outcome_notes
        })
      });
      if (response.ok) {
        setShowExitModal(false);
        fetchJournal();
      } else {
        const error = await response.json();
        alert(`Error: ${error.detail}`);
      }
    } catch (e) {
      console.error("Failed to exit trade:", e);
    }
  };

  const handleDeleteTrade = async (tradeId) => {
    if (!confirm("Are you sure you want to permanently delete this trade journal entry?")) return;
    try {
      const response = await fetch(`${API_URL}/api/journal/${tradeId}`, {
        method: "DELETE"
      });
      if (response.ok) {
        fetchJournal();
      }
    } catch (e) {
      console.error("Failed to delete trade:", e);
    }
  };

  // Operations Runner
  const runOperation = async (operationKey, endpoint, method = "POST") => {
    setRunningOperations(prev => ({ ...prev, [operationKey]: true }));
    setOperationLogs(prev => ({ ...prev, [operationKey]: "Running..." }));
    try {
      const res = await fetch(`${API_URL}${endpoint}`, { method });
      const data = await res.json();
      setOperationLogs(prev => ({ 
        ...prev, 
        [operationKey]: JSON.stringify(data, null, 2) 
      }));
      // Refresh general views if they are updated by these operations
      fetchCandidates();
      fetchJournal();
    } catch (e) {
      setOperationLogs(prev => ({ 
        ...prev, 
        [operationKey]: `Error executing job: ${e.toString()}` 
      }));
    } finally {
      setRunningOperations(prev => ({ ...prev, [operationKey]: false }));
    }
  };

  // Timing Color Badges
  const getTimingBadgeColor = (status) => {
    switch (status) {
      case "Optimal Buy": return "bg-emerald-500/10 text-emerald-400 border-emerald-500/20";
      case "Accumulation": return "bg-cyan-500/10 text-cyan-400 border-cyan-500/20";
      case "Train Has Left": return "bg-amber-500/10 text-amber-400 border-amber-500/20";
      case "Avoid": return "bg-red-500/10 text-red-400 border-red-500/20";
      default: return "bg-slate-800 text-slate-400 border-slate-700";
    }
  };

  const getRegimeBadgeColor = (regime) => {
    switch (regime) {
      case "LEAD": return "bg-emerald-500/15 text-emerald-400 border border-emerald-500/30";
      case "IMPROVE": return "bg-cyan-500/15 text-cyan-400 border border-cyan-500/30";
      case "WEAKEN": return "bg-amber-500/15 text-amber-400 border border-amber-500/30";
      case "LAG": return "bg-red-500/15 text-red-400 border border-red-500/30";
      default: return "bg-slate-800 text-slate-400";
    }
  };

  return (
    <div className="min-h-screen bg-[#07080a] text-slate-100 p-6 flex flex-col font-sans selection:bg-purple-600/30 selection:text-white">
      
      {/* HEADER SECTION */}
      <header className="flex flex-col xl:flex-row justify-between items-start xl:items-center py-5 border-b border-[#151922] mb-6 gap-4">
        <div>
          <div className="flex items-center space-x-3">
            <span className="bg-purple-600 text-[10px] font-extrabold tracking-widest px-2 py-0.5 rounded text-white uppercase animate-pulse">L2 PIPELINE STABLE</span>
            <h1 className="text-2xl font-black tracking-tight text-white flex items-center">
              ECHO <span className="text-purple-500 ml-1 font-bold">DASHBOARD</span>
            </h1>
          </div>
          <p className="text-slate-400 text-xs mt-1 font-medium flex items-center gap-2">
            <Radio size={12} className="text-emerald-400 animate-pulse" />
            Institutional Intelligence Platform for Indian Cash Equity
          </p>
        </div>

        {/* Balance Display */}
        <div className="flex items-center space-x-6 bg-[#0c0e14]/90 border border-[#1a1f2c] px-5 py-3 rounded-lg shadow-2xl">
          <div>
            <span className="text-[10px] text-slate-400 block uppercase font-bold tracking-widest">Paper Capital</span>
            <span className="text-lg font-black text-emerald-400 tracking-tight">₹{simulatedBalance.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</span>
          </div>
          <div className="border-l border-[#1a1f2c] h-8" />
          <div>
            <span className="text-[10px] text-slate-400 block uppercase font-bold tracking-widest">Active Trades</span>
            <span className="text-lg font-black text-white tracking-tight flex items-center justify-end">
              <Briefcase size={14} className="text-purple-400 mr-1.5" />
              {journalEntries.filter(e => e.exit_date === null).length}
            </span>
          </div>
        </div>
      </header>

      {/* TABS NAVIGATION */}
      <nav className="flex flex-wrap border-b border-[#151922] mb-6 gap-1.5">
        <button 
          onClick={() => setActiveTab("committee")}
          className={`px-5 py-3 text-xs font-bold transition-all duration-200 border-b-2 flex items-center gap-2 ${activeTab === "committee" ? "border-purple-500 text-purple-400 bg-purple-500/5" : "border-transparent text-slate-400 hover:text-white"}`}
        >
          <Cpu size={14} />
          Multi-Agent Committee
        </button>
        <button 
          onClick={() => setActiveTab("conviction")}
          className={`px-5 py-3 text-xs font-bold transition-all duration-200 border-b-2 flex items-center gap-2 ${activeTab === "conviction" ? "border-purple-500 text-purple-400 bg-purple-500/5" : "border-transparent text-slate-400 hover:text-white"}`}
        >
          <Flame size={14} />
          Conviction Matrix
        </button>
        <button 
          onClick={() => setActiveTab("news")}
          className={`px-5 py-3 text-xs font-bold transition-all duration-200 border-b-2 flex items-center gap-2 ${activeTab === "news" ? "border-purple-500 text-purple-400 bg-purple-500/5" : "border-transparent text-slate-400 hover:text-white"}`}
        >
          <Newspaper size={14} />
          Three-Tier News Signals
        </button>
        <button 
          onClick={() => setActiveTab("sectors")}
          className={`px-5 py-3 text-xs font-bold transition-all duration-200 border-b-2 flex items-center gap-2 ${activeTab === "sectors" ? "border-purple-500 text-purple-400 bg-purple-500/5" : "border-transparent text-slate-400 hover:text-white"}`}
        >
          <Globe size={14} />
          Sectors & Insiders
        </button>
        <button 
          onClick={() => setActiveTab("journal")}
          className={`px-5 py-3 text-xs font-bold transition-all duration-200 border-b-2 flex items-center gap-2 ${activeTab === "journal" ? "border-purple-500 text-purple-400 bg-purple-500/5" : "border-transparent text-slate-400 hover:text-white"}`}
        >
          <Briefcase size={14} />
          Trade Journal Ledger
        </button>
        <button 
          onClick={() => setActiveTab("operations")}
          className={`px-5 py-3 text-xs font-bold transition-all duration-200 border-b-2 flex items-center gap-2 ${activeTab === "operations" ? "border-purple-500 text-purple-400 bg-purple-500/5" : "border-transparent text-slate-400 hover:text-white"}`}
        >
          <Settings size={14} />
          System Operations
        </button>
      </nav>

      {/* CORE ACTIVE WORKSPACE */}
      <div className="flex-1 min-h-0">
        
        {/* TAB 1: MULTI-AGENT COMMITTEE (THE CORE STOCK DASHBOARD) */}
        {activeTab === "committee" && (
          <div className="grid grid-cols-1 xl:grid-cols-4 gap-6 items-start">
            
            {/* Sidebar list of screened breakout candidates */}
            <aside className="bg-[#0b0d12]/50 border border-[#161a23] p-4 rounded-lg flex flex-col h-[750px] backdrop-blur-md">
              <h2 className="text-xs font-black uppercase tracking-wider text-slate-300 border-b border-[#1b212f] pb-3 mb-3 flex items-center gap-1.5">
                <Layers size={14} className="text-purple-400" />
                <span>Screened Breakouts ({candidates.length})</span>
              </h2>
              
              <div className="flex-1 overflow-y-auto space-y-2 pr-1 custom-scrollbar">
                {candidates.map((c) => (
                  <div 
                    key={c.ticker}
                    onClick={() => handleSelectCandidate(c.ticker)}
                    className={`p-3 rounded border cursor-pointer transition-all duration-200 ${selectedTicker === c.ticker ? "bg-purple-900/10 border-purple-500" : "bg-[#07080a]/40 border-[#1c2230] hover:bg-[#0c0e14] hover:border-slate-500"}`}
                  >
                    <div className="flex justify-between items-start">
                      <div className="font-bold text-xs text-white">{c.ticker}</div>
                      <span className={`text-[9px] px-1.5 py-0.5 rounded font-black border ${getTimingBadgeColor(c.timing_status)}`}>
                        {c.timing_status}
                      </span>
                    </div>
                    <div className="text-[10px] text-slate-400 mt-1 truncate">{c.company_name}</div>
                    <div className="flex justify-between items-center mt-2 text-[9px] font-bold text-slate-500">
                      <span>Price: ₹{c.current_price}</span>
                      <span className="text-purple-400">{c.weinstein_stage}</span>
                    </div>
                  </div>
                ))}
                {candidates.length === 0 && (
                  <div className="text-slate-500 text-center py-20 italic text-xs">
                    No active screened breakouts. Trigger a screening run in the Operations tab.
                  </div>
                )}
              </div>
            </aside>

            {/* Main analysis workspace */}
            <main className="xl:col-span-3 space-y-6">
              
              {/* Header profile of selected stock */}
              <div className="bg-[#0b0d12]/50 border border-[#161a23] p-5 rounded-lg grid grid-cols-1 md:grid-cols-3 gap-6 relative overflow-hidden backdrop-blur-md">
                <div className="absolute top-0 left-0 w-1 h-full bg-purple-500" />
                <div className="md:col-span-2">
                  <div className="text-[9px] text-purple-400 font-bold uppercase tracking-widest">{activeAnalysis.sector} // {activeAnalysis.industry}</div>
                  <h2 className="text-xl font-black text-white mt-1 tracking-tight">{activeAnalysis.companyName}</h2>
                  
                  {/* SEARCH TOOL */}
                  <div className="flex items-center space-x-3 mt-3">
                    <input 
                      type="text" 
                      className="bg-[#07080a] border border-[#232b3c] rounded px-3 py-1.5 text-xs font-bold text-white uppercase w-32 focus:outline-none focus:border-purple-500 focus:ring-1 focus:ring-purple-500"
                      value={tickerInput}
                      onChange={(e) => setTickerInput(e.target.value.toUpperCase())}
                      placeholder="e.g. TCS"
                    />
                    <button 
                      onClick={() => triggerAnalysis(tickerInput)} 
                      disabled={loading}
                      className="bg-purple-600 hover:bg-purple-700 text-white px-4 py-1.5 rounded text-xs font-bold flex items-center space-x-1.5 disabled:opacity-50 transition-all duration-200"
                    >
                      {loading ? (
                        <Loader2 size={12} className="animate-spin" />
                      ) : (
                        <Play size={12} className="fill-current" />
                      )}
                      <span>{loading ? "Committee Running..." : "Run Analysis"}</span>
                    </button>
                    <span className="text-[10px] text-slate-500 font-medium">Symbol: {selectedTicker}</span>
                  </div>
                </div>

                <div className={`p-4 rounded border flex flex-col justify-between ${getTimingBadgeColor(activeAnalysis.timingStatus)}`}>
                  <div className="flex justify-between items-start">
                    <span className="text-[9px] uppercase font-bold tracking-wider">Entry Timing</span>
                    <Clock size={12} />
                  </div>
                  <div className="mt-2">
                    <div className="text-base font-black tracking-tight">{activeAnalysis.timingStatus}</div>
                    <p className="text-[10px] opacity-80 mt-1 leading-relaxed">{activeAnalysis.timingDescription || "Run a committee analysis to fetch fresh entry signals."}</p>
                  </div>
                </div>
              </div>

              {/* Real historical price and simulator charts */}
              <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                
                {/* Close Price + Delivery Volume */}
                <div className="bg-[#0b0d12]/50 border border-[#161a23] p-5 rounded-lg backdrop-blur-md">
                  <h3 className="text-xs font-black uppercase tracking-wider text-slate-300 border-b border-[#1b212f] pb-3 mb-4 flex items-center justify-between">
                    <span>100-Day Price & Delivery Volume (Unmocked)</span>
                    {historyLoading && <Loader2 size={12} className="animate-spin text-purple-400" />}
                  </h3>
                  
                  <div className="h-56 w-full">
                    {historicalData.length > 0 ? (
                      <ResponsiveContainer width="100%" height="100%">
                        <AreaChart data={historicalData} margin={{ top: 5, right: 5, left: -20, bottom: 5 }}>
                          <defs>
                            <linearGradient id="colorPrice" x1="0" y1="0" x2="0" y2="1">
                              <stop offset="5%" stopColor="#8b5cf6" stopOpacity={0.2}/>
                              <stop offset="95%" stopColor="#8b5cf6" stopOpacity={0}/>
                            </linearGradient>
                          </defs>
                          <CartesianGrid strokeDasharray="3 3" stroke="#161a24" />
                          <XAxis dataKey="day" stroke="#475569" style={{ fontSize: 9, fontWeight: "bold" }} />
                          <YAxis stroke="#475569" domain={["auto", "auto"]} style={{ fontSize: 9, fontWeight: "bold" }} />
                          <ChartTooltip contentStyle={{ backgroundColor: "#0b0d12", border: "1px solid #161a23" }} />
                          <Area type="monotone" dataKey="price" stroke="#8b5cf6" strokeWidth={2} fillOpacity={1} fill="url(#colorPrice)" />
                        </AreaChart>
                      </ResponsiveContainer>
                    ) : (
                      <div className="h-full flex items-center justify-center text-xs text-slate-500 italic">No price history found.</div>
                    )}
                  </div>
                </div>

                {/* Real Kronos AutoRegressive Projections */}
                <div className="bg-[#0b0d12]/50 border border-[#161a23] p-5 rounded-lg backdrop-blur-md">
                  <h3 className="text-xs font-black uppercase tracking-wider text-slate-300 border-b border-[#1b212f] pb-3 mb-4 flex items-center justify-between">
                    <span>Kronos Neural Monte Carlo Projections (Unmocked)</span>
                    {simLoading && <Loader2 size={12} className="animate-spin text-purple-400" />}
                  </h3>
                  
                  <div className="h-56 w-full">
                    {projectionData.length > 0 ? (
                      <ResponsiveContainer width="100%" height="100%">
                        <LineChart data={projectionData} margin={{ top: 5, right: 5, left: -20, bottom: 5 }}>
                          <CartesianGrid strokeDasharray="3 3" stroke="#161a24" />
                          <XAxis dataKey="step" stroke="#475569" style={{ fontSize: 9, fontWeight: "bold" }} />
                          <YAxis stroke="#475569" domain={["auto", "auto"]} style={{ fontSize: 9, fontWeight: "bold" }} />
                          <ChartTooltip contentStyle={{ backgroundColor: "#0b0d12", border: "1px solid #161a23" }} />
                          <Line type="monotone" dataKey="pathA" stroke="#10b981" strokeWidth={1.5} dot={false} name="Path A (Optimistic)" />
                          <Line type="monotone" dataKey="pathB" stroke="#8b5cf6" strokeWidth={1.5} dot={false} name="Path B (Neutral)" />
                          <Line type="monotone" dataKey="pathC" stroke="#f59e0b" strokeWidth={1.5} dot={false} name="Path C (Pessimistic)" />
                          <Legend wrapperStyle={{ fontSize: 9, fontWeight: "bold", paddingTop: 10 }} />
                        </LineChart>
                      </ResponsiveContainer>
                    ) : (
                      <div className="h-full flex items-center justify-center text-xs text-slate-500 italic">No simulations loaded. Run analysis above.</div>
                    )}
                  </div>
                  {projectionData.length > 0 && (
                    <div className="flex justify-between items-center mt-3 text-[10px] bg-[#0c0e14] p-2.5 rounded border border-[#1a1f2c] font-bold">
                      <span className="text-slate-400">Projected Upside Prob: <strong className="text-white">{(simulationStats.upsideProb * 100).toFixed(1)}%</strong></span>
                      <span className="text-slate-400">Risk Variance (Vol): <strong className="text-white">{(simulationStats.volRisk * 100).toFixed(1)}%</strong></span>
                      <span className={simulationStats.isSafe ? "text-emerald-400" : "text-amber-500"}>{simulationStats.isSafe ? "✓ Low Risk Boundary" : "⚠ Extreme Risk Variance"}</span>
                    </div>
                  )}
                </div>

              </div>

              {/* Buffett Quality + Graham Intrinsic Value + Weinstein Momentum */}
              <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
                
                {/* Buffett Audit */}
                <div className="bg-[#0b0d12]/50 border border-[#161a23] p-5 rounded-lg relative overflow-hidden backdrop-blur-md">
                  <div className="absolute top-0 left-0 w-1 h-full bg-blue-500" />
                  <h3 className="text-xs font-black uppercase tracking-wider text-slate-300 border-b border-[#1b212f] pb-3 mb-4 flex items-center justify-between">
                    <span className="flex items-center gap-1.5"><Database className="text-blue-500" size={12} />Warren Buffett Quality Audit</span>
                  </h3>
                  <div className="space-y-3 text-xs">
                    <div className="flex justify-between items-center">
                      <span className="text-slate-400">Moat rating</span>
                      <span className="font-bold text-blue-400">{activeAnalysis.moatRating}</span>
                    </div>
                    <div className="flex justify-between items-center">
                      <span className="text-slate-400">Derived ROCE</span>
                      <span className="font-bold text-white">{(activeAnalysis.detailedIndicators.fundamentals.roce * 100).toFixed(1)}%</span>
                    </div>
                    <div className="flex justify-between items-center">
                      <span className="text-slate-400">Derived ROE</span>
                      <span className="font-bold text-white">{(activeAnalysis.detailedIndicators.fundamentals.roe * 100).toFixed(1)}%</span>
                    </div>
                    <div className="flex justify-between items-center">
                      <span className="text-slate-400">Debt-to-Equity</span>
                      <span className="font-bold text-white">{activeAnalysis.detailedIndicators.fundamentals.debt_to_equity.toFixed(2)}</span>
                    </div>
                    <div className="flex justify-between items-center">
                      <span className="text-slate-400">Cash Flow Integrity</span>
                      <span className="font-bold text-white">{activeAnalysis.detailedIndicators.fundamentals.cfo_to_net_income.toFixed(2)}x</span>
                    </div>
                    <div className="pt-3 border-t border-[#1a1f2c] flex justify-between items-center font-bold">
                      <span className="text-slate-400">Verdict</span>
                      <span className="bg-blue-500/10 text-blue-400 border border-blue-500/20 px-2 py-0.5 rounded text-[10px]">
                        {activeAnalysis.detailedIndicators.buffett_scorecard.verdict} ({activeAnalysis.detailedIndicators.buffett_scorecard.score}/5)
                      </span>
                    </div>
                  </div>
                </div>

                {/* Graham Valuation */}
                <div className="bg-[#0b0d12]/50 border border-[#161a23] p-5 rounded-lg relative overflow-hidden backdrop-blur-md">
                  <div className="absolute top-0 left-0 w-1 h-full bg-emerald-500" />
                  <h3 className="text-xs font-black uppercase tracking-wider text-slate-300 border-b border-[#1b212f] pb-3 mb-4 flex items-center justify-between">
                    <span className="flex items-center gap-1.5"><Percent className="text-emerald-500" size={12} />Benjamin Graham Intrinsic Value</span>
                  </h3>
                  <div className="space-y-3 text-xs">
                    <div className="flex justify-between items-center">
                      <span className="text-slate-400">Intrinsic Value</span>
                      <span className="font-bold text-emerald-400">₹{activeAnalysis.intrinsicValue.toFixed(2)}</span>
                    </div>
                    <div className="flex justify-between items-center">
                      <span className="text-slate-400">Current Price</span>
                      <span className="font-bold text-white">₹{activeAnalysis.currentPrice.toFixed(2)}</span>
                    </div>
                    <div className="flex justify-between items-center">
                      <span className="text-slate-400">Margin of Safety</span>
                      <span className={`font-bold ${activeAnalysis.marginOfSafety >= 0.3 ? "text-emerald-400" : "text-slate-300"}`}>
                        {(activeAnalysis.marginOfSafety * 100).toFixed(1)}%
                      </span>
                    </div>
                    <div className={`mt-5 p-3 rounded border flex items-center space-x-2.5 ${activeAnalysis.isUndervalued ? "bg-emerald-950/20 border-emerald-500/20 text-emerald-300" : "bg-slate-900/40 border-[#1a1f2c] text-slate-400"}`}>
                      {activeAnalysis.isUndervalued ? (
                        <>
                          <CheckCircle className="text-emerald-400 flex-shrink-0" size={14} />
                          <div className="text-[10px] leading-normal font-bold">
                            <span className="text-white block">Value Approved</span>
                            Trades below intrinsic valuation buffer.
                          </div>
                        </>
                      ) : (
                        <>
                          <AlertTriangle className="text-amber-500 flex-shrink-0" size={14} />
                          <div className="text-[10px] leading-normal font-bold">
                            <span className="text-slate-300 block">Premium Price</span>
                            Trades above Graham intrinsic margin of safety.
                          </div>
                        </>
                      )}
                    </div>
                  </div>
                </div>

                {/* Weinstein & CANSLIM */}
                <div className="bg-[#0b0d12]/50 border border-[#161a23] p-5 rounded-lg relative overflow-hidden backdrop-blur-md">
                  <div className="absolute top-0 left-0 w-1 h-full bg-purple-500" />
                  <h3 className="text-xs font-black uppercase tracking-wider text-slate-300 border-b border-[#1b212f] pb-3 mb-4 flex items-center justify-between">
                    <span className="flex items-center gap-1.5"><TrendingUp className="text-purple-500" size={12} />Weinstein & CANSLIM Momentum</span>
                  </h3>
                  <div className="space-y-3 text-xs">
                    <div className="flex justify-between items-center">
                      <span className="text-slate-400">Weinstein Stage</span>
                      <span className="font-bold text-purple-400">{activeAnalysis.weinsteinStage}</span>
                    </div>
                    <div className="flex justify-between items-center">
                      <span className="text-slate-400">Trend Score</span>
                      <span className="font-bold text-white">{activeAnalysis.weinsteinScore.toFixed(2)}</span>
                    </div>
                    <div className="flex justify-between items-center">
                      <span className="text-slate-400">CANSLIM Checklist Rating</span>
                      <span className="font-bold text-white">{activeAnalysis.canslimScore.toFixed(2)}</span>
                    </div>
                    <div className="flex justify-between items-center">
                      <span className="text-slate-400">Breakout Volume</span>
                      <span className="font-bold text-white">{activeAnalysis.detailedIndicators.technical.sma_150 > 0 ? "SMA-150 Slope check OK" : "N/A"}</span>
                    </div>
                    <div className="flex justify-between items-center">
                      <span className="text-slate-400">SMC Liquidity Sweeps</span>
                      <span className="font-bold text-white">{activeAnalysis.detailedIndicators.technical.sweeps.length} Detected</span>
                    </div>
                  </div>
                </div>

              </div>

              {/* Lower Section: Real-time Committee Reasoning Logs */}
              <div className="bg-[#0b0d12]/50 border border-[#161a23] p-5 rounded-lg flex flex-col h-[340px] backdrop-blur-md">
                <h3 className="text-xs font-black uppercase tracking-wider text-slate-300 border-b border-[#1b212f] pb-3 mb-3 flex items-center justify-between">
                  <span className="flex items-center gap-1.5"><FileSpreadsheet className="text-purple-500" size={12} />Committee Reasoning Log Stream</span>
                  <span className={`px-2 py-0.5 rounded font-black text-[9px] uppercase border ${
                    activeAnalysis.executionStatus === "trade_executed" ? "bg-emerald-500/10 text-emerald-400 border-emerald-500/20" :
                    activeAnalysis.executionStatus === "trade_aborted" ? "bg-red-500/10 text-red-400 border-red-500/20" :
                    activeAnalysis.executionStatus === "re_planning_active" ? "bg-amber-500/10 text-amber-400 border-amber-500/20" : "bg-slate-800 text-slate-400 border-slate-700"
                  }`}>
                    {activeAnalysis.executionStatus.replace("_", " ")}
                  </span>
                </h3>

                <div className="flex-1 overflow-y-auto space-y-2 pr-1 select-text font-mono text-[10px] text-slate-300 custom-scrollbar">
                  {logs.map((log, idx) => (
                    <div 
                      key={idx} 
                      className={`p-2 rounded border ${
                        log.includes("CRITICAL") || log.includes("rejected") || log.includes("block") || log.includes("aborted") ? "bg-red-950/20 border-red-500/10 text-red-300" :
                        log.includes("Approved") || log.includes("Success") || log.includes("complete") || log.includes("executed") ? "bg-emerald-950/20 border border-emerald-500/10 text-emerald-400" :
                        log.includes("WARNING") || log.includes("halted") ? "bg-amber-950/20 border border-amber-500/10 text-amber-400" :
                        "bg-[#07080a]/40 border-[#151922]"
                      }`}
                    >
                      {log}
                    </div>
                  ))}
                  {loading && (
                    <div className="flex items-center space-x-2 p-2 text-slate-400 italic">
                      <Loader2 size={12} className="animate-spin text-purple-400" />
                      <span>Running multi-agent committee...</span>
                    </div>
                  )}
                  {!loading && logs.length === 0 && (
                    <div className="text-slate-500 text-center py-20 italic">
                      Pipeline idle. Search a stock or select from candidates to trigger committee decision.
                    </div>
                  )}
                </div>
              </div>

            </main>
          </div>
        )}

        {/* TAB 2: CONVICTION MATRIX LEADERBOARD */}
        {activeTab === "conviction" && (
          <div className="space-y-6">
            
            {/* Lead board matrix */}
            <div className="bg-[#0b0d12]/50 border border-[#161a23] p-5 rounded-lg backdrop-blur-md">
              <div className="flex justify-between items-center border-b border-[#1b212f] pb-3 mb-4">
                <h2 className="text-xs font-black uppercase tracking-wider text-slate-300 flex items-center gap-1.5">
                  <Flame className="text-purple-500" size={14} />
                  <span>0-100 Conviction Matrix Leaderboard</span>
                </h2>
                <button 
                  onClick={() => runOperation("scoring", "/api/conviction/run")}
                  className="bg-purple-600 hover:bg-purple-700 text-white px-3 py-1.5 rounded text-[10px] font-bold flex items-center gap-1"
                >
                  <Play size={10} />
                  Run Scoring Job
                </button>
              </div>

              <div className="overflow-x-auto">
                <table className="w-full text-left border-collapse text-xs">
                  <thead>
                    <tr className="border-b border-[#1a1f2c] text-slate-400 font-bold uppercase tracking-wider text-[10px]">
                      <th className="py-3 px-3">Ticker</th>
                      <th>Conviction Score</th>
                      <th>Technicals (+30)</th>
                      <th>Smart Money (+30)</th>
                      <th>Thematic (+20)</th>
                      <th>Fundamentals (+20)</th>
                      <th>Trap Penalty (-50)</th>
                      <th>Verdict</th>
                      <th className="text-right px-3">Last Scored</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-[#161a23]/60">
                    {convictionList.map((row, idx) => (
                      <tr 
                        key={idx} 
                        onClick={() => handleSelectCandidate(row.symbol)}
                        className="hover:bg-slate-800/10 font-bold text-slate-200 cursor-pointer"
                      >
                        <td className="py-3 px-3 text-white">{row.symbol}</td>
                        <td>
                          <span className={`px-2 py-0.5 rounded font-black ${
                            row.conviction_score >= 75 ? "bg-emerald-500/15 text-emerald-400 border border-emerald-500/20" :
                            row.conviction_score >= 50 ? "bg-cyan-500/15 text-cyan-400 border border-cyan-500/20" :
                            "bg-slate-800 text-slate-400"
                          }`}>
                            {row.conviction_score}/100
                          </span>
                        </td>
                        <td className="text-purple-400">+{row.technical_score}</td>
                        <td className="text-emerald-400">+{row.smart_money_score}</td>
                        <td className="text-blue-400">+{row.thematic_score}</td>
                        <td className="text-cyan-400">+{row.fundamental_score}</td>
                        <td className="text-red-400">-{row.trap_score || row.trap_penalty || 0}</td>
                        <td>
                          <span className="text-[11px] truncate block max-w-xs">{row.verdict}</span>
                        </td>
                        <td className="text-right px-3 text-slate-500 text-[10px]">
                          {new Date(row.updated_at).toLocaleString("en-IN")}
                        </td>
                      </tr>
                    ))}
                    {convictionLoading && (
                      <tr>
                        <td colSpan={9} className="py-12 text-center text-slate-400">
                          <Loader2 size={20} className="animate-spin inline mr-2 text-purple-400" />
                          <span>Loading conviction leaderboard...</span>
                        </td>
                      </tr>
                    )}
                    {!convictionLoading && convictionList.length === 0 && (
                      <tr>
                        <td colSpan={9} className="py-12 text-center text-slate-500 italic">
                          Leaderboard empty. Trigger a manual scoring run using the button above or Operations panel.
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </div>

            {/* Active overrides list */}
            <div className="bg-[#0b0d12]/50 border border-[#161a23] p-5 rounded-lg backdrop-blur-md">
              <h2 className="text-xs font-black uppercase tracking-wider text-slate-300 border-b border-[#1b212f] pb-3 mb-4 flex items-center gap-1.5">
                <ShieldAlert className="text-amber-500" size={14} />
                <span>Active News Conviction Overrides (Tier 2 / Tier 3 Auto-Adjustments)</span>
              </h2>

              <div className="overflow-x-auto">
                <table className="w-full text-left border-collapse text-xs">
                  <thead>
                    <tr className="border-b border-[#1a1f2c] text-slate-400 font-bold uppercase tracking-wider text-[10px]">
                      <th className="py-3 px-3">Ticker</th>
                      <th>Adjustment points</th>
                      <th>Override Source</th>
                      <th>Reasoning Catalyst</th>
                      <th className="text-right px-3">Auto-Expires At</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-[#161a23]/60">
                    {activeOverrides.map((row, idx) => (
                      <tr key={idx} className="font-bold text-slate-200">
                        <td className="py-3 px-3 text-white">{row.symbol}</td>
                        <td>
                          <span className={`px-2 py-0.5 rounded font-black ${
                            row.override_points > 0 ? "bg-emerald-500/10 text-emerald-400 border border-emerald-500/20" : "bg-red-500/10 text-red-400 border border-red-500/20"
                          }`}>
                            {row.override_points > 0 ? `+${row.override_points}` : row.override_points}
                          </span>
                        </td>
                        <td className="text-purple-400">{row.source}</td>
                        <td className="max-w-md truncate text-slate-300">{row.reason}</td>
                        <td className="text-right px-3 text-slate-500">
                          {new Date(row.expires_at).toLocaleString("en-IN")}
                        </td>
                      </tr>
                    ))}
                    {activeOverrides.length === 0 && (
                      <tr>
                        <td colSpan={5} className="py-8 text-center text-slate-500 italic">
                          No active score overrides present. Trigger news pipeline in Operations.
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </div>

          </div>
        )}

        {/* TAB 3: THREE-TIER NEWS SIGNALS */}
        {activeTab === "news" && (
          <div className="space-y-6">
            
            {/* Top Catalysts & Override Events */}
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
              
              <div className="bg-[#0b0d12]/50 border border-[#161a23] p-5 rounded-lg lg:col-span-2 backdrop-blur-md">
                <div className="flex justify-between items-center border-b border-[#1b212f] pb-3 mb-4">
                  <h3 className="text-xs font-black uppercase tracking-wider text-slate-300 flex items-center gap-1.5">
                    <Newspaper className="text-purple-500" size={14} />
                    <span>Material Catalysts / Order Wins Scraped (Last 24 Hours)</span>
                  </h3>
                  <button 
                    onClick={() => runOperation("news", "/api/news/pipeline")}
                    className="bg-purple-600 hover:bg-purple-700 text-white px-3 py-1 rounded text-[10px] font-bold flex items-center gap-1"
                  >
                    <Play size={10} />
                    Run News Pipeline
                  </button>
                </div>

                <div className="space-y-3">
                  {materialCatalysts.map((c, idx) => (
                    <div key={idx} className="bg-[#07080a]/60 border border-[#1a1f2c] p-3 rounded flex justify-between items-center gap-4 hover:border-slate-600 transition-all duration-200">
                      <div>
                        <div className="flex items-center space-x-2">
                          <span className="font-extrabold text-white text-xs">{c.symbol}</span>
                          <span className="bg-purple-500/10 text-purple-400 text-[9px] font-black border border-purple-500/25 px-1.5 py-0.5 rounded">{c.event_type}</span>
                          <span className="text-[10px] text-slate-500">{new Date(c.processed_at).toLocaleTimeString("en-IN")}</span>
                        </div>
                        <p className="text-xs text-slate-300 font-bold mt-1.5">{c.llm_summary || c.source_title}</p>
                      </div>

                      <div className="text-right">
                        <span className={`px-2.5 py-1 rounded text-xs font-black border block ${
                          c.conviction_adjustment > 0 ? "bg-emerald-500/10 text-emerald-400 border-emerald-500/20" : "bg-red-500/10 text-red-400 border-red-500/20"
                        }`}>
                          {c.conviction_adjustment > 0 ? `+${c.conviction_adjustment}` : c.conviction_adjustment} pts
                        </span>
                      </div>
                    </div>
                  ))}
                  {materialCatalysts.length === 0 && (
                    <div className="text-slate-500 text-center py-16 italic text-xs">
                      No material catalysts identified in the last 24 hours. Run news pipeline manually to scrape.
                    </div>
                  )}
                </div>
              </div>

              {/* Tier 1 Sector Adjustments */}
              <div className="bg-[#0b0d12]/50 border border-[#161a23] p-5 rounded-lg backdrop-blur-md">
                <h3 className="text-xs font-black uppercase tracking-wider text-slate-300 border-b border-[#1b212f] pb-3 mb-4 flex items-center gap-1.5">
                  <Globe className="text-purple-500" size={12} />
                  <span>Macro Sector Adjustments (Tier 1)</span>
                </h3>

                <div className="space-y-2.5">
                  {newsSignals.filter(s => s.tier === 1).map((s, idx) => (
                    <div key={idx} className="bg-[#07080a]/60 border border-[#1a1f2c] p-2.5 rounded text-xs font-semibold hover:border-slate-600 transition-all duration-200">
                      <div className="flex justify-between items-center font-bold">
                        <span className="text-purple-400">{s.theme.replace("_", " ")}</span>
                        <span className={s.sentiment === "BULLISH" ? "text-emerald-400" : s.sentiment === "BEARISH" ? "text-red-400" : "text-slate-400"}>
                          {s.sentiment}
                        </span>
                      </div>
                      <p className="text-slate-300 mt-1 text-[11px] font-bold">{s.llm_summary}</p>
                      <div className="flex justify-between items-center mt-2 text-[10px] text-slate-500">
                        <span>Sectors: {s.affected_sectors.join(", ")}</span>
                        <span className="font-black text-white">{s.conviction_adjustment > 0 ? "+" : ""}{s.conviction_adjustment} pts</span>
                      </div>
                    </div>
                  ))}
                  {newsSignals.filter(s => s.tier === 1).length === 0 && (
                    <div className="text-slate-500 text-center py-16 italic text-xs">
                      No macro sector signals ingested today.
                    </div>
                  )}
                </div>
              </div>

            </div>

            {/* General News Signals List */}
            <div className="bg-[#0b0d12]/50 border border-[#161a23] p-5 rounded-lg backdrop-blur-md">
              <h3 className="text-xs font-black uppercase tracking-wider text-slate-300 border-b border-[#1b212f] pb-3 mb-4 flex items-center gap-1.5">
                <FileSpreadsheet className="text-purple-500" size={14} />
                <span>All Processed Signals (Chronological Feed)</span>
              </h3>

              <div className="overflow-x-auto">
                <table className="w-full text-left border-collapse text-xs">
                  <thead>
                    <tr className="border-b border-[#1a1f2c] text-slate-400 font-bold uppercase tracking-wider text-[10px]">
                      <th className="py-3 px-3">Tier</th>
                      <th>Ticker/Query</th>
                      <th>Original Source/Title</th>
                      <th>Event Type / Theme</th>
                      <th>Sentiment</th>
                      <th>Adjustment</th>
                      <th className="text-right px-3">Processed Time</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-[#161a23]/60">
                    {newsSignals.map((row, idx) => (
                      <tr key={idx} className="font-bold text-slate-200">
                        <td className="py-3 px-3 text-slate-400">Tier {row.tier}</td>
                        <td className="text-white">{row.symbol || row.query}</td>
                        <td className="max-w-sm truncate text-slate-300" title={row.source_title}>{row.source_title || "-"}</td>
                        <td>
                          <span className="bg-purple-500/10 text-purple-400 px-2 py-0.5 rounded text-[10px] font-black border border-purple-500/20">{row.event_type || row.theme || "Generic"}</span>
                        </td>
                        <td className={row.sentiment === "BULLISH" || row.sentiment === "Bullish" ? "text-emerald-400" : row.sentiment === "BEARISH" || row.sentiment === "Bearish" ? "text-red-400" : "text-slate-400"}>
                          {row.sentiment}
                        </td>
                        <td className={row.conviction_adjustment > 0 ? "text-emerald-400" : row.conviction_adjustment < 0 ? "text-red-400" : "text-slate-500"}>
                          {row.conviction_adjustment > 0 ? `+${row.conviction_adjustment}` : row.conviction_adjustment}
                        </td>
                        <td className="text-right px-3 text-slate-500 text-[10px]">
                          {new Date(row.processed_at).toLocaleString("en-IN")}
                        </td>
                      </tr>
                    ))}
                    {newsLoading && (
                      <tr>
                        <td colSpan={7} className="py-12 text-center text-slate-400">
                          <Loader2 size={16} className="animate-spin inline mr-2 text-purple-400" />
                          Loading signals feed...
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </div>

          </div>
        )}

        {/* TAB 4: SECTOR HEATMAP & INSIDERS FEED */}
        {activeTab === "sectors" && (
          <div className="grid grid-cols-1 xl:grid-cols-2 gap-6 items-start">
            
            {/* Sector Heatmap */}
            <div className="bg-[#0b0d12]/50 border border-[#161a23] p-5 rounded-lg backdrop-blur-md">
              <div className="flex justify-between items-center border-b border-[#1b212f] pb-3 mb-4">
                <h3 className="text-xs font-black uppercase tracking-wider text-slate-300 flex items-center gap-1.5">
                  <Globe className="text-purple-500" size={14} />
                  <span>Sector Rotation Momentum Heatmap (Relative strength vs Nifty 50)</span>
                </h3>
                <button 
                  onClick={() => runOperation("sectors", "/api/sectors/refresh")}
                  className="bg-purple-600 hover:bg-purple-700 text-white px-3 py-1 rounded text-[10px] font-bold flex items-center gap-1"
                >
                  <Play size={10} />
                  Refresh Momentum
                </button>
              </div>

              <div className="grid grid-cols-2 gap-4">
                {sectorHeatmap.map((row, idx) => (
                  <div key={idx} className="bg-[#07080a]/60 border border-[#1a1f2c] p-3.5 rounded flex justify-between items-center hover:border-slate-600 transition-all duration-200">
                    <div>
                      <div className="font-extrabold text-white text-xs">{row.sector_name}</div>
                      <span className="text-[10px] text-slate-500">{row.index_symbol}</span>
                      <div className="text-[10px] text-slate-400 mt-2">RS Score: <strong className="text-white">{row.rs_score}</strong></div>
                    </div>
                    <div className="text-right">
                      <span className={`px-2 py-0.5 rounded text-[10px] font-black block border ${getRegimeBadgeColor(row.momentum_regime)}`}>
                        {row.momentum_regime}
                      </span>
                      <span className={`text-[10px] font-bold block mt-1.5 ${row.rs_change_4w >= 0 ? "text-emerald-400" : "text-red-400"}`}>
                        {row.rs_change_4w >= 0 ? "+" : ""}{(row.rs_change_4w * 100).toFixed(2)}% Δ4W
                      </span>
                    </div>
                  </div>
                ))}
                {sectorsLoading && (
                  <div className="col-span-2 text-center py-12 text-slate-400">
                    <Loader2 size={16} className="animate-spin inline mr-2 text-purple-400" />
                    Calculating sector momentum relative strength...
                  </div>
                )}
              </div>
            </div>

            {/* Insider Disclosures Feed */}
            <div className="bg-[#0b0d12]/50 border border-[#161a23] p-5 rounded-lg backdrop-blur-md">
              <div className="flex justify-between items-center border-b border-[#1b212f] pb-3 mb-4">
                <h3 className="text-xs font-black uppercase tracking-wider text-slate-300 flex items-center gap-1.5">
                  <Database className="text-purple-500" size={14} />
                  <span>NSE SASTI Insider & Promoter Trading Disclosures Feed</span>
                </h3>
                <button 
                  onClick={() => runOperation("insiders", "/api/insiders/crawl")}
                  className="bg-purple-600 hover:bg-purple-700 text-white px-3 py-1 rounded text-[10px] font-bold flex items-center gap-1"
                >
                  <Play size={10} />
                  Crawl NSE SASTI
                </button>
              </div>

              <div className="overflow-x-auto h-[600px] custom-scrollbar">
                <table className="w-full text-left border-collapse text-xs">
                  <thead>
                    <tr className="border-b border-[#1a1f2c] text-slate-400 font-bold uppercase tracking-wider text-[10px]">
                      <th className="py-2.5 px-2">Ticker</th>
                      <th>Acquirer Promoter</th>
                      <th>Category</th>
                      <th>Tx Type</th>
                      <th>Quantity</th>
                      <th>Value (INR)</th>
                      <th className="text-right px-2">Trade Date</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-[#161a23]/60">
                    {insiderFeed.map((row, idx) => (
                      <tr 
                        key={idx} 
                        onClick={() => handleSelectCandidate(row.symbol)}
                        className="hover:bg-slate-800/10 font-bold text-slate-200 cursor-pointer"
                      >
                        <td className="py-2 px-2 text-white">{row.symbol}</td>
                        <td className="max-w-[140px] truncate text-slate-300" title={row.acquirer_name}>{row.acquirer_name}</td>
                        <td className="text-slate-400 text-[10px]">{row.category_of_person || "Promoter"}</td>
                        <td className={row.transaction_type === "Buy" ? "text-emerald-400" : "text-red-400"}>{row.transaction_type}</td>
                        <td>{parseInt(row.quantity).toLocaleString("en-IN")} sh</td>
                        <td className="text-purple-400">₹{parseFloat(row.value_rs || 0).toLocaleString("en-IN", { maximumFractionDigits: 0 })}</td>
                        <td className="text-right px-2 text-slate-500 text-[10px]">{row.trade_date}</td>
                      </tr>
                    ))}
                    {insiderLoading && (
                      <tr>
                        <td colSpan={7} className="py-12 text-center text-slate-400">
                          <Loader2 size={16} className="animate-spin inline mr-2 text-purple-400" />
                          Crawling insider disclosures from NSE archives...
                        </td>
                      </tr>
                    )}
                    {!insiderLoading && insiderFeed.length === 0 && (
                      <tr>
                        <td colSpan={7} className="py-8 text-center text-slate-500 italic">
                          Disclosures feed is empty. Click button to crawl NSE SASTI files.
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </div>

          </div>
        )}

        {/* TAB 5: PRIVATE TRADE JOURNAL LEDGER */}
        {activeTab === "journal" && (
          <div className="grid grid-cols-1 xl:grid-cols-3 gap-6 items-start">
            
            {/* Journal Table Ledger */}
            <div className="bg-[#0b0d12]/50 border border-[#161a23] p-5 rounded-lg xl:col-span-2 backdrop-blur-md h-[700px] flex flex-col">
              <h3 className="text-xs font-black uppercase tracking-wider text-slate-300 border-b border-[#1b212f] pb-3 mb-4 flex items-center gap-1.5">
                <Briefcase className="text-purple-500" size={14} />
                <span>Simulated Portfolio Trading Log & Realized PnL</span>
              </h3>

              <div className="flex-1 overflow-y-auto custom-scrollbar">
                <table className="w-full text-left border-collapse text-xs">
                  <thead>
                    <tr className="border-b border-[#1a1f2c] text-slate-400 font-bold uppercase tracking-wider text-[9px]">
                      <th className="py-2.5 px-2">Ticker</th>
                      <th>Entry Date</th>
                      <th>Entry Price</th>
                      <th>Qty</th>
                      <th>Stop Loss</th>
                      <th>Target</th>
                      <th>Realized PnL</th>
                      <th>Status</th>
                      <th className="text-right px-2">Actions</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-[#161a23]/60">
                    {journalEntries.map((row, idx) => (
                      <tr key={idx} className="font-bold text-slate-200">
                        <td className="py-3 px-2 text-white">{row.symbol}</td>
                        <td>{row.entry_date}</td>
                        <td>₹{parseFloat(row.entry_price).toFixed(2)}</td>
                        <td>{row.quantity} sh</td>
                        <td className="text-red-400">₹{parseFloat(row.stop_loss).toFixed(2)}</td>
                        <td className="text-emerald-400">{row.target_price ? `₹${parseFloat(row.target_price).toFixed(2)}` : "-"}</td>
                        <td className={row.exit_date ? (parseFloat(row.pnl) >= 0 ? "text-emerald-400" : "text-red-400") : "text-slate-400"}>
                          {row.exit_date ? `₹${parseFloat(row.pnl).toLocaleString("en-IN", { minimumFractionDigits: 2 })}` : "-"}
                        </td>
                        <td>
                          {row.exit_date ? (
                            <span className="bg-slate-800 text-slate-400 border border-slate-700 px-1.5 py-0.5 rounded text-[9px] font-black uppercase">Closed</span>
                          ) : (
                            <span className="bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 px-1.5 py-0.5 rounded text-[9px] font-black uppercase">Active</span>
                          )}
                        </td>
                        <td className="text-right px-2">
                          <div className="flex justify-end items-center gap-1.5">
                            {row.exit_date === null && (
                              <button 
                                onClick={() => {
                                  setExitForm(prev => ({ ...prev, trade_id: row.id }));
                                  setShowExitModal(true);
                                }}
                                className="bg-purple-600 hover:bg-purple-700 text-white px-2 py-0.5 rounded text-[9px] font-bold"
                              >
                                Exit
                              </button>
                            )}
                            <button 
                              onClick={() => handleDeleteTrade(row.id)}
                              className="text-slate-500 hover:text-red-400 p-1"
                            >
                              <Trash2 size={12} />
                            </button>
                          </div>
                        </td>
                      </tr>
                    ))}
                    {journalLoading && (
                      <tr>
                        <td colSpan={9} className="py-12 text-center text-slate-400">
                          <Loader2 size={16} className="animate-spin inline mr-2 text-purple-400" />
                          Fetching trade ledger...
                        </td>
                      </tr>
                    )}
                    {journalEntries.length === 0 && (
                      <tr>
                        <td colSpan={9} className="py-12 text-center text-slate-500 italic">
                          Journal is empty. Log a new transaction on the right panel.
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </div>

            {/* Log Trade Entry Form */}
            <div className="bg-[#0b0d12]/50 border border-[#161a23] p-5 rounded-lg backdrop-blur-md">
              <h3 className="text-xs font-black uppercase tracking-wider text-slate-300 border-b border-[#1b212f] pb-3 mb-4 flex items-center gap-1.5">
                <Plus className="text-purple-500" size={14} />
                <span>Log New Swing Transaction</span>
              </h3>

              <form onSubmit={handleLogTrade} className="space-y-4 text-xs font-bold">
                <div>
                  <label className="text-slate-400 block mb-1 uppercase tracking-wider text-[10px]">Symbol</label>
                  <input 
                    type="text" 
                    className="w-full bg-[#07080a] border border-[#232b3c] rounded px-3 py-2 text-white focus:outline-none focus:border-purple-500 uppercase"
                    value={journalForm.symbol}
                    onChange={(e) => setJournalForm(prev => ({ ...prev, symbol: e.target.value }))}
                    placeholder="e.g. TCS"
                    required
                  />
                </div>

                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="text-slate-400 block mb-1 uppercase tracking-wider text-[10px]">Entry Price</label>
                    <input 
                      type="number" 
                      step="any"
                      className="w-full bg-[#07080a] border border-[#232b3c] rounded px-3 py-2 text-white focus:outline-none focus:border-purple-500"
                      value={journalForm.entry_price}
                      onChange={(e) => setJournalForm(prev => ({ ...prev, entry_price: e.target.value }))}
                      required
                    />
                  </div>
                  <div>
                    <label className="text-slate-400 block mb-1 uppercase tracking-wider text-[10px]">Quantity</label>
                    <input 
                      type="number" 
                      className="w-full bg-[#07080a] border border-[#232b3c] rounded px-3 py-2 text-white focus:outline-none focus:border-purple-500"
                      value={journalForm.quantity}
                      onChange={(e) => setJournalForm(prev => ({ ...prev, quantity: e.target.value }))}
                      required
                    />
                  </div>
                </div>

                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="text-slate-400 block mb-1 uppercase tracking-wider text-[10px]">Stop Loss</label>
                    <input 
                      type="number" 
                      step="any"
                      className="w-full bg-[#07080a] border border-[#232b3c] rounded px-3 py-2 text-red-400 focus:outline-none focus:border-red-500"
                      value={journalForm.stop_loss}
                      onChange={(e) => setJournalForm(prev => ({ ...prev, stop_loss: e.target.value }))}
                      required
                    />
                  </div>
                  <div>
                    <label className="text-slate-400 block mb-1 uppercase tracking-wider text-[10px]">Target Price</label>
                    <input 
                      type="number" 
                      step="any"
                      className="w-full bg-[#07080a] border border-[#232b3c] rounded px-3 py-2 text-emerald-400 focus:outline-none focus:border-emerald-500"
                      value={journalForm.target_price}
                      onChange={(e) => setJournalForm(prev => ({ ...prev, target_price: e.target.value }))}
                    />
                  </div>
                </div>

                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="text-slate-400 block mb-1 uppercase tracking-wider text-[10px]">Entry Date</label>
                    <input 
                      type="date" 
                      className="w-full bg-[#07080a] border border-[#232b3c] rounded px-3 py-2 text-white focus:outline-none focus:border-purple-500"
                      value={journalForm.entry_date}
                      onChange={(e) => setJournalForm(prev => ({ ...prev, entry_date: e.target.value }))}
                      required
                    />
                  </div>
                  <div>
                    <label className="text-slate-400 block mb-1 uppercase tracking-wider text-[10px]">Conviction Score</label>
                    <input 
                      type="number" 
                      min="0"
                      max="100"
                      className="w-full bg-[#07080a] border border-[#232b3c] rounded px-3 py-2 text-white focus:outline-none focus:border-purple-500"
                      value={journalForm.conviction_score}
                      onChange={(e) => setJournalForm(prev => ({ ...prev, conviction_score: e.target.value }))}
                      required
                    />
                  </div>
                </div>

                <div>
                  <label className="text-slate-400 block mb-1 uppercase tracking-wider text-[10px]">Catalyst Setup Notes</label>
                  <textarea 
                    rows="2"
                    className="w-full bg-[#07080a] border border-[#232b3c] rounded px-3 py-2 text-white focus:outline-none focus:border-purple-500 font-medium"
                    value={journalForm.catalyst}
                    onChange={(e) => setJournalForm(prev => ({ ...prev, catalyst: e.target.value }))}
                    placeholder="Weinstein Stage 2 breakout / Promoters buying..."
                  />
                </div>

                <button 
                  type="submit"
                  className="w-full bg-emerald-600 hover:bg-emerald-700 text-white font-extrabold py-2.5 rounded transition-all duration-200 uppercase tracking-widest text-[10px]"
                >
                  Log Transaction
                </button>
              </form>
            </div>

          </div>
        )}

        {/* TAB 6: SYSTEM OPERATIONS & MANUAL CRON TRIGGER */}
        {activeTab === "operations" && (
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 items-start">
            
            {/* List of operations/cron jobs */}
            <div className="bg-[#0b0d12]/50 border border-[#161a23] p-5 rounded-lg backdrop-blur-md space-y-4">
              <h2 className="text-xs font-black uppercase tracking-wider text-slate-300 border-b border-[#1b212f] pb-3 mb-2 flex items-center gap-1.5">
                <Settings className="text-purple-500" size={14} />
                <span>Manual Cron & Data Crawler Control Board</span>
              </h2>

              {/* Operations cards */}
              {[
                {
                  key: "nightly",
                  name: "Full Nightly Sync Pipeline",
                  endpoint: "/api/jobs/nightly",
                  desc: "Chains Bhavcopy ingest, Insider disclosure crawl, Sector rotation calculation, and Conviction Score Matrix scoring sequentially. Runs daily at 8:30 PM IST."
                },
                {
                  key: "news",
                  name: "Three-Tier News Engine Ingestion",
                  endpoint: "/api/news/pipeline",
                  desc: "Runs Tier 1 Global Macro searches, Tier 2 corporate filings announcements crawl (NSE API), and Tier 3 watchlist sentiment scans."
                },
                {
                  key: "bhavcopy",
                  name: "Bhavcopy Ingestion Crawler",
                  endpoint: "/api/thematic/crawl",
                  desc: "Downloads latest NSE archives EOD price & deliverable positions report, parsing volumes and delivery percentages."
                },
                {
                  key: "insiders",
                  name: "Insider SASTI Filings crawler",
                  endpoint: "/api/insiders/crawl",
                  desc: "Scrapes official NSE SASTI archives (last 7 days) and ingests promoter buy/sell filings."
                },
                {
                  key: "sectors",
                  name: "Sector Rotation Refresh",
                  endpoint: "/api/sectors/refresh",
                  desc: "Downloads 6-month historical indices closes from yfinance, calculating RS vs Nifty 50 and momentum regimes."
                },
                {
                  key: "scoring",
                  name: "Conviction Score Matrix recalculator",
                  endpoint: "/api/conviction/run",
                  desc: "Scores all constituents 0-100 across Technicals, Delivery Volumes, Themes, Fundamentals and Traps, sending alerts for high-conviction crossovers."
                }
              ].map(op => (
                <div key={op.key} className="bg-[#07080a]/60 border border-[#1a1f2c] p-4 rounded flex flex-col md:flex-row justify-between items-start md:items-center gap-4 hover:border-slate-600 transition-all duration-200">
                  <div className="max-w-md">
                    <div className="font-extrabold text-white text-xs">{op.name}</div>
                    <p className="text-[10px] text-slate-400 mt-1 leading-normal font-medium">{op.desc}</p>
                    <span className="text-[9px] text-purple-400 block mt-2 font-mono">{op.endpoint}</span>
                  </div>

                  <div className="flex-shrink-0">
                    <button 
                      onClick={() => runOperation(op.key, op.endpoint)}
                      disabled={runningOperations[op.key]}
                      className="bg-purple-600 hover:bg-purple-700 text-white font-extrabold px-4 py-2 rounded text-[10px] uppercase tracking-widest disabled:opacity-50 flex items-center space-x-1.5"
                    >
                      {runningOperations[op.key] ? (
                        <Loader2 size={12} className="animate-spin" />
                      ) : (
                        <Play size={10} className="fill-current" />
                      )}
                      <span>{runningOperations[op.key] ? "Running..." : "Execute"}</span>
                    </button>
                  </div>
                </div>
              ))}
            </div>

            {/* Execution logs terminal */}
            <div className="bg-[#0b0d12]/50 border border-[#161a23] p-5 rounded-lg backdrop-blur-md flex flex-col h-[700px]">
              <h2 className="text-xs font-black uppercase tracking-wider text-slate-300 border-b border-[#1b212f] pb-3 mb-4 flex items-center gap-1.5">
                <FileSpreadsheet className="text-purple-500" size={14} />
                <span>Live Pipeline Output Logs Terminal</span>
              </h2>

              <div className="flex-1 bg-[#050608] border border-[#161a23] p-4 rounded font-mono text-[10px] text-slate-300 overflow-y-auto custom-scrollbar select-text space-y-4">
                {Object.keys(operationLogs).map(key => (
                  <div key={key} className="border-b border-[#151922] pb-3">
                    <div className="text-purple-400 font-extrabold uppercase mb-1 tracking-wider text-[9px]">[Operation: {key}]</div>
                    <pre className="whitespace-pre-wrap leading-relaxed">{operationLogs[key]}</pre>
                  </div>
                ))}
                {Object.keys(operationLogs).length === 0 && (
                  <div className="text-slate-600 text-center py-40 italic">
                    Terminal idle. Click "Execute" on any system crawler to inspect the live return values.
                  </div>
                )}
              </div>
            </div>

          </div>
        )}

      </div>

      {/* EXIT TRADE MODAL */}
      {showExitModal && (
        <div className="fixed inset-0 bg-black/80 backdrop-blur-sm flex items-center justify-center p-4 z-50">
          <div className="bg-[#0b0d12] border border-[#1a1f2c] p-5 rounded-lg w-full max-w-sm text-xs font-bold">
            <h3 className="text-sm font-black text-white border-b border-[#1a1f2c] pb-3 mb-4 uppercase tracking-wider">Log Exit Trade Parameters</h3>
            
            <form onSubmit={handleExitTrade} className="space-y-4">
              <div>
                <label className="text-slate-400 block mb-1 uppercase tracking-wider text-[10px]">Exit Price</label>
                <input 
                  type="number" 
                  step="any"
                  className="w-full bg-[#07080a] border border-[#232b3c] rounded px-3 py-2 text-white focus:outline-none focus:border-purple-500"
                  value={exitForm.exit_price}
                  onChange={(e) => setExitForm(prev => ({ ...prev, exit_price: e.target.value }))}
                  required
                />
              </div>

              <div>
                <label className="text-slate-400 block mb-1 uppercase tracking-wider text-[10px]">Exit Date</label>
                <input 
                  type="date" 
                  className="w-full bg-[#07080a] border border-[#232b3c] rounded px-3 py-2 text-white focus:outline-none focus:border-purple-500"
                  value={exitForm.exit_date}
                  onChange={(e) => setExitForm(prev => ({ ...prev, exit_date: e.target.value }))}
                  required
                />
              </div>

              <div>
                <label className="text-slate-400 block mb-1 uppercase tracking-wider text-[10px]">Outcome Notes</label>
                <textarea 
                  rows="3"
                  className="w-full bg-[#07080a] border border-[#232b3c] rounded px-3 py-2 text-white focus:outline-none focus:border-purple-500 font-medium"
                  value={exitForm.outcome_notes}
                  onChange={(e) => setExitForm(prev => ({ ...prev, outcome_notes: e.target.value }))}
                  placeholder="Exit target reached / Trailing stop triggered..."
                />
              </div>

              <div className="flex justify-end gap-3 pt-2">
                <button 
                  type="button"
                  onClick={() => setShowExitModal(false)}
                  className="bg-slate-800 hover:bg-slate-700 text-slate-300 font-bold px-4 py-2 rounded uppercase tracking-wider text-[9px]"
                >
                  Cancel
                </button>
                <button 
                  type="submit"
                  className="bg-emerald-600 hover:bg-emerald-700 text-white font-extrabold px-4 py-2 rounded uppercase tracking-wider text-[9px]"
                >
                  Record Exit
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* FOOTER */}
      <footer className="mt-8 border-t border-[#151922] pt-4 flex flex-col md:flex-row justify-between items-center text-[10px] text-slate-500 font-bold">
        <div className="flex items-center space-x-2">
          <Globe size={12} className="text-purple-500" />
          <span>Obsidian Engine API v2.0 // Active Workspace: Echo</span>
        </div>
        <div className="mt-2 md:mt-0">
          Last sync details: Real yfinance data feeds, pgvector matching, and local Kronos predictors active.
        </div>
      </footer>

    </div>
  );
}
