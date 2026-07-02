import { regimeBadgeClass } from '../utils/formatters'

function SignalRow({ s }) {
  const isLong = s.direction === 'long' || s.direction === 1
  return (
    <div className="flex items-center justify-between bg-slate-900/60 rounded-lg px-3 py-2">
      <div className="flex items-center gap-2">
        <span className={`text-xs font-bold px-2 py-0.5 rounded-full ${
          isLong ? 'bg-emerald-900/60 text-emerald-300' : 'bg-red-900/60 text-red-300'
        }`}>
          {isLong ? '↑ 多' : '↓ 空'}
        </span>
        <span className="text-sm font-medium">
          {s.symbol?.replace('/USDT', '')}
        </span>
      </div>
      <div className="text-right">
        <div className={`text-xs font-mono ${
          (s.momentum ?? 0) >= 0 ? 'text-up' : 'text-down'
        }`}>
          {(s.momentum ?? 0) >= 0 ? '+' : ''}{s.momentum ?? 0}%
        </div>
        <div className="text-xs text-slate-500">
          得分 {(s.score ?? 0).toFixed(3)}
        </div>
      </div>
    </div>
  )
}

export default function SignalsPanel({ signals, onRefresh }) {
  if (!signals && !onRefresh) return null

  const regime    = signals?.regime || '—'
  const slotCount = signals?.slots ?? '—'
  const capPct    = signals?.cap_pct ?? '—'
  const asOf      = signals?.as_of || signals?.timestamp?.slice(0, 10) || '—'
  const list      = signals?.signals || []

  return (
    <div className="bg-card border border-border rounded-xl p-4">
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-sm font-semibold text-slate-300">⚡ 当前信号</h2>
        {onRefresh && (
          <button
            onClick={onRefresh}
            className="text-xs text-blue px-2 py-1 rounded hover:bg-slate-800 transition-colors"
          >
            刷新
          </button>
        )}
      </div>

      {/* 元信息 */}
      <div className="flex flex-wrap gap-2 mb-3">
        <span className={`text-xs px-2 py-0.5 rounded-full border ${regimeBadgeClass(regime)}`}>
          {regime.toUpperCase()}
        </span>
        <span className="text-xs text-slate-400">
          {slotCount} 槽 · 仓位 {capPct}%
        </span>
        <span className="text-xs text-slate-500">
          {asOf}
        </span>
      </div>

      {/* 信号列表 */}
      {!signals ? (
        <div className="space-y-2">
          {[...Array(3)].map((_, i) => (
            <div key={i} className="h-10 bg-slate-900/60 rounded-lg animate-pulse" />
          ))}
        </div>
      ) : list.length === 0 ? (
        <p className="text-xs text-slate-500 py-4 text-center">
          当前无有效信号（Regime={regime}）
        </p>
      ) : (
        <div className="space-y-2">
          {list.map((s, i) => <SignalRow key={i} s={s} />)}
        </div>
      )}
    </div>
  )
}
