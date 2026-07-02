import { fmtPct, fmt } from '../utils/formatters'

function Card({ label, value, valueClass, sub }) {
  return (
    <div className="bg-card border border-border rounded-xl p-4">
      <p className="text-xs text-slate-500 mb-1">{label}</p>
      <p className={`text-2xl font-bold font-mono ${valueClass}`}>{value}</p>
      {sub && <p className="text-xs text-slate-500 mt-1">{sub}</p>}
    </div>
  )
}

export default function StatsCards({ stats, meta }) {
  if (!stats) {
    return (
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
        {[...Array(4)].map((_, i) => (
          <div key={i} className="bg-card border border-border rounded-xl p-4 animate-pulse h-20" />
        ))}
      </div>
    )
  }

  const dateRange = meta
    ? `${meta.start} ~ ${meta.end}`
    : `${stats.start || ''} ~ ${stats.end || ''}`

  const sharpeOk = (stats.sharpe ?? stats.sharpe) >= 0.5

  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
      <Card
        label="总收益率"
        value={fmtPct(stats.total_return ?? (stats.total_return_pct * 100))}
        valueClass={(stats.total_return ?? 0) >= 0 ? 'text-up' : 'text-down'}
        sub={dateRange}
      />
      <Card
        label="Sharpe 比率"
        value={fmt(stats.sharpe, 3)}
        valueClass={sharpeOk ? 'text-up' : 'text-blue'}
        sub={sharpeOk ? '已超里程碑 ✅' : '目标 0.7'}
      />
      <Card
        label="年化收益"
        value={fmtPct(stats.annual_return)}
        valueClass={(stats.annual_return ?? 0) >= 0 ? 'text-up' : 'text-down'}
        sub={`${stats.total_trades || 0} 笔交易`}
      />
      <Card
        label="最大回撤"
        value={fmtPct(stats.max_drawdown)}
        valueClass="text-down"
        sub={`胜率 ${((stats.win_rate || 0) * 100).toFixed(1)}%`}
      />
    </div>
  )
}
