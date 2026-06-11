import React, { useState, useEffect } from "react";
import { 
  LineChart, 
  Line, 
  XAxis, 
  YAxis, 
  CartesianGrid, 
  Tooltip, 
  ReferenceLine, 
  ResponsiveContainer 
} from "recharts";
import { 
  TrendingUp, 
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
  Briefcase
} from "lucide-react";

export default function App() {
  const [tickerInput, setTickerInput] = useState("RELIANCE");
  const [loading, setLoading] = useState(false);
  const [currentNode, setCurrentNode] = useState("");
  const [logs, setLogs] = useState([]);
  
  // Pipeline analysis states
  const [activeAnalysis, setActiveAnalysis] = useState({
    ticker: "RELIANCE.NS",
    currentPrice: 1263.0,
    fundamentalScore: 1.0,
    sentimentScore: 0.8,
    isInvalidated: false,
    kronosUpsideProb: 0.93,
    kronosVolRisk: 0.08,
    allocationPercentage: 1.86,
    executionStatus: "trade_executed",
    flags: { qualified_remarks: false, promoter_pledging_spike: false, operating_cash_flow_drop: false }
  });

  // Simulated paper-trading holdings
  const [positions, setPositions] = useState([
    { ticker: "RELIANCE.NS", buyPrice: 1263.0, currentPrice: 1272.5, size: 147, stopLoss: 1215.0, pnl: 1396.5, status: "Active" }
  ]);

  // Monte Carlo simulation chart data generator
  const [chartData, setChartData] = useState([]);

  useEffect(() => {
    generateChartData(1263.0, 0.93);
  }, []);

  const generateChartData = (startPrice, upsideProb) => {
    // Generate 30 paths of 24 steps
    const numPaths = 12; // lower count for chart performance and cleaner aesthetics
    const steps = 24;
    const data = [];
    
    for (let s = 0; s <= steps; s++) {
      const stepObj = { step: s };
      for (let p = 0; p < numPaths; p++) {
        let trend = (upsideProb - 0.5) * 0.8; // trend bias
        let noise = (Math.sin(s * 0.5 + p) * 0.3 + (Math.random() - 0.5)) * 1.5;
        let price = startPrice + (s * trend) + noise;
        stepObj[`path_${p}`] = parseFloat(price.toFixed(2));
      }
      data.push(stepObj);
    }
    setChartData(data);
  };

  // Subscribe to SSE updates
  useEffect(() => {
    const sse = new EventSource("http://127.0.0.1:8000/api/stream_pipeline");
    sse.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        if (data.node) {
          setCurrentNode(data.node);
          setLogs((prev) => [...prev, `[State Engine] Entering ${data.node}...`]);
        }
        if (data.updates) {
          const u = data.updates;
          setActiveAnalysis((prev) => ({
            ...prev,
            ticker: data.ticker,
            currentPrice: u.current_price || prev.currentPrice,
            fundamentalScore: u.fundamental_score !== undefined ? u.fundamental_score : prev.fundamentalScore,
            sentimentScore: u.sentiment_score !== undefined ? u.sentiment_score : prev.sentimentScore,
            isInvalidated: u.is_invalidated !== undefined ? u.is_invalidated : prev.isInvalidated,
            kronosUpsideProb: u.kronos_upside_prob !== undefined ? u.kronos_upside_prob : prev.kronosUpsideProb,
            kronosVolRisk: u.kronos_vol_risk !== undefined ? u.kronos_vol_risk : prev.kronosVolRisk,
            allocationPercentage: u.allocation_percentage !== undefined ? u.allocation_percentage : prev.allocationPercentage,
            executionStatus: u.execution_status || prev.executionStatus,
            flags: u.flags || prev.flags
          }));

          if (u.logs) {
            setLogs(u.logs);
          }
          if (u.current_price || u.kronos_upside_prob) {
            generateChartData(u.current_price || 1200, u.kronos_upside_prob || 0.5);
          }
        }
      } catch (e) {
        console.error("Failed parsing SSE event:", e);
      }
    };
    return () => sse.close();
  }, []);

  const triggerAnalysis = async () => {
    setLoading(true);
    setLogs([]);
    setCurrentNode("discovery");
    try {
      const response = await fetch("http://127.0.0.1:8000/api/analyze", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ticker: tickerInput })
      });
      const data = await response.json();
      if (data.status === "success" && data.final_state) {
        const final = data.final_state;
        
        // Add new simulated paper positions if executed
        if (final.execution_status === "trade_executed") {
          const tickerName = final.ticker || tickerInput.toUpperCase() + ".NS";
          const buyPrice = final.current_price || 1200.0;
          const allocationVal = final.allocation_percentage || 0.015;
          const virtualEquity = 1000000.0; // ₹10L
          const size = Math.floor((virtualEquity * allocationVal) / buyPrice);
          
          const newPos = {
            ticker: tickerName,
            buyPrice: buyPrice,
            currentPrice: buyPrice,
            size: size,
            stopLoss: parseFloat((buyPrice * 0.95).toFixed(2)),
            pnl: 0.0,
            status: "Active"
          };
          setPositions((prev) => [newPos, ...prev.filter(p => p.ticker !== tickerName)]);
        }
      }
    } catch (e) {
      logger.error("Analysis trigger failed:", e);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-[#08090d] text-slate-100 p-6">
      {/* HEADER SECTION */}
      <header className="flex flex-col md:flex-row justify-between items-start md:items-center border-b border-[#1b1e28] pb-6 mb-6">
        <div>
          <div className="flex items-center space-x-2">
            <span className="bg-[#9c27b0] text-[10px] font-bold tracking-widest px-2 py-0.5 rounded text-white uppercase">HF Live</span>
            <h1 className="text-2xl font-extrabold tracking-tight text-white flex items-center">
              ECHO <span className="text-[#9c27b0] ml-1">ENGINE</span>
            </h1>
          </div>
          <p className="text-slate-400 text-xs mt-1">Multi-Agent Investment Committee & Autoregressive Risk Analytics</p>
        </div>

        {/* Paper Account Radar */}
        <div className="flex items-center space-x-6 mt-4 md:mt-0 bg-[#0f1118]/80 border border-[#1b1e28] px-5 py-3 rounded-lg backdrop-blur-md">
          <div className="text-right">
            <span className="text-[10px] text-slate-400 block uppercase font-bold tracking-wider">Virtual Balance</span>
            <span className="text-lg font-extrabold text-[#00ff88]">₹10,00,000.00</span>
          </div>
          <div className="border-l border-[#1b1e28] h-8" />
          <div className="text-right">
            <span className="text-[10px] text-slate-400 block uppercase font-bold tracking-wider">Active Holdings</span>
            <span className="text-lg font-extrabold text-white flex items-center justify-end">
              <Briefcase size={16} className="text-[#c084fc] mr-1.5" />
              {positions.length}
            </span>
          </div>
        </div>
      </header>

      {/* SEARCH AND CONTROLS */}
      <section className="bg-[#0f1118]/60 border border-[#1d212d] p-4 rounded-xl mb-6 flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div className="flex items-center space-x-3 w-full md:w-auto">
          <Compass className="text-[#a855f7] flex-shrink-0" size={20} />
          <span className="text-sm font-semibold whitespace-nowrap">Screen NSE Stock:</span>
          <div className="relative w-full md:w-64">
            <input 
              type="text" 
              className="bg-[#08090c] border border-[#272d3e] rounded-lg px-3 py-1.5 w-full text-sm font-semibold focus:outline-none focus:border-[#a855f7] text-white uppercase"
              value={tickerInput}
              onChange={(e) => setTickerInput(e.target.value.toUpperCase())}
            />
          </div>
          <button 
            onClick={triggerAnalysis} 
            disabled={loading}
            className="bg-[#9c27b0] hover:bg-[#b030b0] text-white px-4 py-1.5 rounded-lg text-sm font-bold flex items-center space-x-1.5 disabled:opacity-50 transition-all duration-200 shadow-lg shadow-[#9c27b0]/20"
          >
            {loading ? (
              <Loader2 size={16} className="animate-spin" />
            ) : (
              <Play size={14} className="fill-current" />
            )}
            <span>{loading ? "Analyzing..." : "Analyze"}</span>
          </button>
        </div>

        {/* Global Market Status Indicators */}
        <div className="flex items-center space-x-4 text-xs">
          <div className="flex items-center space-x-1.5 bg-[#00ff88]/10 text-[#00ff88] px-2.5 py-1 rounded border border-[#00ff88]/20 font-bold">
            <TrendingUp size={12} />
            <span>GIFT Nifty (+0.42%)</span>
          </div>
          <div className="flex items-center space-x-1.5 bg-slate-800/50 text-slate-300 px-2.5 py-1 rounded border border-slate-700/50 font-bold">
            <span>Market Regime: Bullish breakouts</span>
          </div>
        </div>
      </section>

      {/* CORE WORKSPACE GRID */}
      <main className="grid grid-cols-1 xl:grid-cols-3 gap-6 mb-6">
        
        {/* COMMITTEE AGENT MATRIX */}
        <div className="xl:col-span-2 space-y-6">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            
            {/* Fundamental Desk Panel */}
            <div className="bg-[#0f1118]/80 border border-[#1b1e28] rounded-xl p-5 backdrop-blur-md relative overflow-hidden">
              <div className="absolute top-0 left-0 w-1 h-full bg-[#3b82f6]" />
              <h2 className="text-sm font-bold text-slate-100 flex items-center space-x-2">
                <Database className="text-[#3b82f6]" size={16} />
                <span>Fundamental Desk (ChromaDB + Ollama)</span>
              </h2>
              
              <div className="mt-4 space-y-3">
                <div className="flex justify-between items-center bg-[#08090d] p-3 rounded-lg border border-[#1b1e28]">
                  <span className="text-xs text-slate-400">Fundamental Conviction Score</span>
                  <span className={`text-base font-extrabold ${activeAnalysis.fundamentalScore < 0.5 ? "text-red-400" : "text-[#3b82f6]"}`}>
                    {activeAnalysis.fundamentalScore.toFixed(2)}
                  </span>
                </div>

                <h3 className="text-[10px] text-slate-400 font-bold uppercase tracking-wider mt-4">Audited Forensic Risks</h3>
                <div className="grid grid-cols-3 gap-2 mt-1">
                  <div className={`p-2 rounded border text-center text-xs font-semibold ${activeAnalysis.flags?.qualified_remarks ? "bg-red-950/20 border-red-500/30 text-red-400" : "bg-[#08090d] border-[#1b1e28] text-slate-400"}`}>
                    Auditor Remarks
                  </div>
                  <div className={`p-2 rounded border text-center text-xs font-semibold ${activeAnalysis.flags?.promoter_pledging_spike ? "bg-red-950/20 border-red-500/30 text-red-400" : "bg-[#08090d] border-[#1b1e28] text-slate-400"}`}>
                    Pledging Spike
                  </div>
                  <div className={`p-2 rounded border text-center text-xs font-semibold ${activeAnalysis.flags?.operating_cash_flow_drop ? "bg-red-950/20 border-red-500/30 text-red-400" : "bg-[#08090d] border-[#1b1e28] text-slate-400"}`}>
                    Cash Flow Drop
                  </div>
                </div>
              </div>
            </div>

            {/* Sentiment Invalidation Desk Panel */}
            <div className="bg-[#0f1118]/80 border border-[#1b1e28] rounded-xl p-5 backdrop-blur-md relative overflow-hidden">
              <div className="absolute top-0 left-0 w-1 h-full bg-[#ef4444]" />
              <h2 className="text-sm font-bold text-slate-100 flex items-center space-x-2">
                <ShieldAlert className="text-[#ef4444]" size={16} />
                <span>Sentiment & Circuit Breaker Desk</span>
              </h2>

              <div className="mt-4 space-y-3">
                <div className="flex justify-between items-center bg-[#08090d] p-3 rounded-lg border border-[#1b1e28]">
                  <span className="text-xs text-slate-400">Morning Sentiment Score</span>
                  <span className="text-base font-extrabold text-[#00ff88]">
                    {(activeAnalysis.sentimentScore * 100).toFixed(0)}% Bullish
                  </span>
                </div>

                <div className={`p-3 rounded-lg border flex items-center space-x-3 ${activeAnalysis.isInvalidated ? "bg-red-950/40 border-red-500/30 text-red-200" : "bg-[#08090d] border-[#1b1e28] text-slate-300"}`}>
                  {activeAnalysis.isInvalidated ? (
                    <>
                      <XCircle className="text-red-500 flex-shrink-0" size={18} />
                      <div className="text-xs">
                        <span className="font-bold block">Circuit Breaker Tripped</span>
                        <span>Candidate invalidated due to extreme retail mania or critical news.</span>
                      </div>
                    </>
                  ) : (
                    <>
                      <CheckCircle className="text-[#00ff88] flex-shrink-0" size={18} />
                      <div className="text-xs">
                        <span className="font-bold block text-white">Sentiment Stable</span>
                        <span>No severe corporate disclosures or extreme retail mania.</span>
                      </div>
                    </>
                  )}
                </div>
              </div>
            </div>

          </div>

          {/* KRONOS CANVAS - MONTE CARLO TRAJECTORY */}
          <div className="bg-[#0f1118]/80 border border-[#1b1e28] rounded-xl p-5 backdrop-blur-md">
            <div className="flex justify-between items-center mb-4">
              <h2 className="text-sm font-bold text-slate-100 flex items-center space-x-2">
                <Cpu className="text-[#e2ba34]" size={16} />
                <span>Latent Physics Engine (Kronos Monte Carlo Rollouts)</span>
              </h2>
              
              <div className="flex items-center space-x-4 text-xs font-semibold">
                <span className="bg-[#e2ba34]/10 text-[#e2ba34] border border-[#e2ba34]/20 px-2 py-0.5 rounded">
                  Upside Prob: {(activeAnalysis.kronosUpsideProb * 100).toFixed(0)}%
                </span>
                <span className="bg-slate-800 text-slate-300 px-2 py-0.5 rounded">
                  Volatility: {(activeAnalysis.kronosVolRisk * 100).toFixed(2)}%
                </span>
              </div>
            </div>

            {/* Recharts Trajectory Visualization */}
            <div className="h-64 w-full">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={chartData} margin={{ top: 10, right: 10, left: 0, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#1b1e28" />
                  <XAxis dataKey="step" stroke="#475569" style={{ fontSize: 10 }} />
                  <YAxis domain={["auto", "auto"]} stroke="#475569" style={{ fontSize: 10 }} />
                  <Tooltip contentStyle={{ backgroundColor: "#0f1118", border: "1px solid #1b1e28" }} />
                  {/* Reference Line for dynamic stop-loss or support boundaries */}
                  <ReferenceLine 
                    y={activeAnalysis.currentPrice * 0.95} 
                    label={{ value: "Support Floor (-5%)", fill: "#ef4444", fontSize: 10, position: "top" }} 
                    stroke="#ef4444" 
                    strokeDasharray="3 3" 
                  />
                  {chartData.length > 0 && Object.keys(chartData[0])
                    .filter((key) => key.startsWith("path_"))
                    .map((key, i) => (
                      <Line 
                        key={key} 
                        type="monotone" 
                        dataKey={key} 
                        stroke={activeAnalysis.kronosUpsideProb >= 0.85 ? "#00ff88" : "#f43f5e"} 
                        strokeWidth={1} 
                        dot={false}
                        opacity={0.25}
                      />
                    ))}
                </LineChart>
              </ResponsiveContainer>
            </div>
          </div>
        </div>

        {/* AGENT LOGS & DECISIONS RUN TIME */}
        <div className="bg-[#0f1118]/80 border border-[#1b1e28] rounded-xl p-5 backdrop-blur-md flex flex-col h-[520px]">
          <h2 className="text-sm font-bold text-slate-100 flex items-center space-x-2 border-b border-[#1b1e28] pb-3 mb-3">
            <FileText className="text-[#a855f7]" size={16} />
            <span>Investment Committee Stream Logs</span>
          </h2>
          
          {/* Transition Path Status Visual */}
          <div className="flex items-center justify-between text-xs bg-[#08090d] p-3 rounded-lg border border-[#1b1e28] mb-3">
            <span className="text-slate-400 font-bold uppercase tracking-wider">State Machine Status</span>
            <span className={`px-2.5 py-0.5 rounded font-extrabold uppercase tracking-wide ${
              activeAnalysis.executionStatus === "trade_executed" ? "bg-[#00ff88]/10 text-[#00ff88]" :
              activeAnalysis.executionStatus === "trade_aborted" ? "bg-red-500/10 text-red-400" :
              activeAnalysis.executionStatus === "re_planning_active" ? "bg-[#e2ba34]/10 text-[#e2ba34]" : "bg-slate-800 text-slate-400"
            }`}>
              {activeAnalysis.executionStatus.replace("_", " ")}
            </span>
          </div>

          <div className="flex-1 overflow-y-auto space-y-2 font-mono text-[11px] text-slate-300 pr-1 select-text">
            {logs.map((log, idx) => (
              <div 
                key={idx} 
                className={`p-2 rounded ${
                  log.includes("CRITICAL") || log.includes("rejected") ? "bg-red-950/20 border border-red-500/10 text-red-300" :
                  log.includes("Approved") || log.includes("Success") ? "bg-[#00ff88]/5 border border-[#00ff88]/10 text-[#00ff88]" :
                  log.includes("WARNING") ? "bg-[#e2ba34]/5 border border-[#e2ba34]/10 text-[#e2ba34]" :
                  "bg-[#08090d]/50 border border-[#1b1e28]/50"
                }`}
              >
                {log}
              </div>
            ))}
            {loading && (
              <div className="flex items-center space-x-2 p-2 text-slate-400 italic">
                <Loader2 size={12} className="animate-spin text-[#a855f7]" />
                <span>Running graph edge transitions...</span>
              </div>
            )}
            {!loading && logs.length === 0 && (
              <div className="text-slate-500 text-center py-20 italic">
                No active committee executions. Click "Analyze" above to run the state graph.
              </div>
            )}
          </div>
        </div>

      </main>

      {/* PAPER TRADING POSITIONS TABLE */}
      <section className="bg-[#0f1118]/80 border border-[#1b1e28] rounded-xl p-5 backdrop-blur-md">
        <h2 className="text-sm font-bold text-slate-100 flex items-center space-x-2 border-b border-[#1b1e28] pb-3 mb-3">
          <Briefcase className="text-[#00ff88]" size={16} />
          <span>Simulated Paper Trading Ledger</span>
        </h2>

        <div className="overflow-x-auto">
          <table className="w-full text-left border-collapse text-xs">
            <thead>
              <tr className="border-b border-[#1b1e28] text-slate-400 font-bold uppercase tracking-wider">
                <th className="py-2.5">Ticker</th>
                <th>Avg. Buy Price</th>
                <th>Last Traded Price</th>
                <th>Position Size</th>
                <th>Trailing Stop</th>
                <th>Simulated PnL</th>
                <th className="text-right">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[#1b1e28]/40">
              {positions.map((pos, idx) => (
                <tr key={idx} className="hover:bg-slate-800/10 font-medium">
                  <td className="py-3 font-bold text-white">{pos.ticker}</td>
                  <td>₹{pos.buyPrice.toFixed(2)}</td>
                  <td>₹{pos.currentPrice.toFixed(2)}</td>
                  <td>{pos.size} shares</td>
                  <td className="text-red-400">₹{pos.stopLoss.toFixed(2)}</td>
                  <td className={pos.pnl >= 0 ? "text-[#00ff88]" : "text-red-400"}>
                    ₹{pos.pnl >= 0 ? "+" : ""}{pos.pnl.toFixed(2)}
                  </td>
                  <td className="text-right">
                    <span className="bg-[#00ff88]/10 text-[#00ff88] px-2 py-0.5 rounded font-bold text-[10px] uppercase">
                      {pos.status}
                    </span>
                  </td>
                </tr>
              ))}
              {positions.length === 0 && (
                <tr>
                  <td colSpan={7} className="text-slate-500 text-center py-6 italic">
                    No active simulated paper-trading positions.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
