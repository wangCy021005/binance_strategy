import { useStats, useEquity, useTrades, useRegime, useLiveState, useSignals, useSimAccount } from './hooks/useData'
import StatsCards  from './components/StatsCards'
import EquityChart from './components/EquityChart'
import RegimeChart from './components/RegimeChart'
import SignalsPanel from './components/SignalsPanel'
import LiveState   from './components/LiveState'
import TradesTable from './components/TradesTable'
import SimAccount  from './components/SimAccount'
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
          Momentum · AlphaGPT · 实时模拟跟踪
        </p>
      </div>
      <div className="flex items-center gap-2 flex-wrap">
        <span className={`text-xs px-3 py-1 rounded-full border font-medium ${
          isDryRun
            ? 'bg-yellow-900/40 text-yellow-300 border-yellow-700/50'
            : 'bg-red-900/40 text-red-300 border-red-700/50'
        }`}>
          {isDryRun ? '🟡 模拟运行' : '🔴 实盘中'}
        </span>
        {regime !== '—' && (
          <span className={`text-xs px-3 py-1 rounded-full border font-medium ${regimeBadgeClass(regime)}`}>
            {regime.toUpperCase()}
          </span>
        )}
        {stats && (
          <span className={`text-xs px-3 py-1 rounded-full border font-medium ${
            stats.sharpe >= 0.5
              ? 'bg-emerald-900/40 text-emerald-300 border-emerald-700/50'
              : 'bg-slate-800 text-slate-400 border-slate-700'
          }`}>
            回测 Sharpe {stats.sharpe?.toFixed(3)}
          </span>
        )}
      </div>
    </div>
  )
}

export default function App() {
  const { stats, meta } = useStats()
  const { equity }   = useEquity()
  const { trades }   = useTrades()
  const { regime }   = useRegime()
  const { live }     = useLiveState()
  const { signals, refresh: refreshSignals } = useSignals()
  const { sim, simStats, simEquity } = useSimAccount()

  return (
    <div className="min-h-screen bg-bg p-4 md:p-6 max-w-7xl mx-auto">
      <Header live={live} stats={stats} />

      {/* KPI 卡片 */}
      <StatsCards stats={stats} meta={meta} />

      {/* 净值曲线 + Regime 饼图 */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-4">
        <div className="md:col-span-2">
          <EquityChart equity={equity} simEquity={simEquity} />
        </div>
        <RegimeChart regime={regime} />
      </div>

      {/* 模拟账户 + 信号 + 实盘状态 */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-4">
        <SimAccount sim={sim} simStats={simStats} simEquity={simEquity} />
        <SignalsPanel signals={signals} onRefresh={refreshSignals} />
        <LiveState live={live} />
      </div>

      {/* 回测交易记录 */}
      <div className="grid grid-cols-1">
        <TradesTable trades={trades} />
      </div>

      <div className="mt-6 text-center text-xs text-slate-600">
        模拟账户每天 UTC 00:10 自动运行 · 数据每 5 分钟刷新 · 仅供参考
      </div>
    </div>
  )
}
