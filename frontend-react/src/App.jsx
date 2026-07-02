import { useStats, useEquity, useTrades, useRegime, useLiveState, useSignals } from './hooks/useData'
import StatsCards  from './components/StatsCards'
import EquityChart from './components/EquityChart'
import RegimeChart from './components/RegimeChart'
import SignalsPanel from './components/SignalsPanel'
import LiveState   from './components/LiveState'
import TradesTable from './components/TradesTable'
import { regimeBadgeClass } from './utils/formatters'

function Header({ live, stats }) {
  const regime   = live?.regime || '—'
  const isDryRun = live?.dry_run !== false

  return (
    <div className="flex flex-col sm:flex-row sm:items-center justify-between mb-6 gap-3">
      <div>
        <h1 className="text-2xl font-bold text-white tracking-tight">
          🚀 币安量化策略
        </h1>
        <p className="text-xs text-slate-500 mt-0.5">
          Momentum · AlphaGPT · 2022 ~ 2025
        </p>
      </div>
      <div className="flex items-center gap-2 flex-wrap">
        {/* 实盘/模拟标识 */}
        <span className={`text-xs px-3 py-1 rounded-full border font-medium ${
          isDryRun
            ? 'bg-yellow-900/40 text-yellow-300 border-yellow-700/50'
            : 'bg-red-900/40 text-red-300 border-red-700/50'
        }`}>
          {isDryRun ? '🟡 模拟运行' : '🔴 实盘中'}
        </span>
        {/* 当前 Regime */}
        {regime !== '—' && (
          <span className={`text-xs px-3 py-1 rounded-full border font-medium ${regimeBadgeClass(regime)}`}>
            {regime.toUpperCase()}
          </span>
        )}
        {/* Sharpe 指示 */}
        {stats && (
          <span className={`text-xs px-3 py-1 rounded-full border font-medium ${
            stats.sharpe >= 0.5
              ? 'bg-emerald-900/40 text-emerald-300 border-emerald-700/50'
              : 'bg-slate-800 text-slate-400 border-slate-700'
          }`}>
            Sharpe {stats.sharpe?.toFixed(3)}
          </span>
        )}
      </div>
    </div>
  )
}

export default function App() {
  const { stats, meta, isLoading: statsLoading } = useStats()
  const { equity }   = useEquity()
  const { trades }   = useTrades()
  const { regime }   = useRegime()
  const { live }     = useLiveState()
  const { signals, refresh: refreshSignals } = useSignals()

  return (
    <div className="min-h-screen bg-bg p-4 md:p-6 max-w-7xl mx-auto">
      <Header live={live} stats={stats} />

      {/* KPI 卡片 */}
      <StatsCards stats={stats} meta={meta} />

      {/* 净值曲线 + Regime 饼图 */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-4">
        <div className="md:col-span-2">
          <EquityChart equity={equity} />
        </div>
        <RegimeChart regime={regime} />
      </div>

      {/* 信号 + 实盘 + 交易记录 */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <SignalsPanel signals={signals} onRefresh={refreshSignals} />
        <LiveState    live={live} />
        <TradesTable  trades={trades} />
      </div>

      {/* 页脚 */}
      <div className="mt-6 text-center text-xs text-slate-600">
        数据每 5 分钟自动刷新 · 仅供参考，不构成投资建议
      </div>
    </div>
  )
}
