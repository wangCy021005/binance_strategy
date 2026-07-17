import { fmtPct, fmt } from '../utils/formatters'

function PositionRow({ pos }) {
  const isLong = pos.side === 'long'
  const isWin  = pos.pnl_pct >= 0
  return (
    <div className="flex items-center justify-between bg-slate-900/60 rounded-lg px-3 py-2">
      <div className="flex items-center gap-2">
        <span className={`text-xs font-bold px-2 py-0.5 rounded-full ${
          isLong ? 'bg-emerald-900/60 text-emerald-300' : 'bg-red-900/60 text-red-300'
        }`}>
          {isLong ? '↑ 多' : '↓ 空'}
        </span>
        <span className="text-sm font-medium">
          {pos.symbol?.replace('/USDT', '')}
        </span>
      </div>
      <div className="text-right">
        <div className="text-xs text-slate-400">
          开仓 {pos.entry?.toFixed(4)}
        </div>
        <div className={`text-xs font-mono ${isWin ? 'text-up' : 'text-down'}`}>
          {isWin ? '+' : ''}{pos.pnl_pct?.toFixed(1)}%
        </div>
      </div>
    </div>
  )
}

export default function SimAccount({ sim, simStats, simEquity }) {
  const nav      = simStats?.nav || 1.0
  const totalRet = simStats?.total_return || 0
  const cash     = simStats?.cash || 0
  const positions = sim?.positions || []
  const trades   = sim?.trades || []
  const posList  = simEquity ? [] : []  // placeholder

  return (
    <div className="bg-card border border-border rounded-xl p-4">
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-sm font-semibold text-slate-300">🟡 模拟账户</h2>
        <span className="text-xs px-2 py-0.5 rounded-full bg-yellow-900/40 text-yellow-300 border border-yellow-700/50">
          实时跟踪
        </span>
      </div>

      {/* 净值概览 */}
      <div className="grid grid-cols-2 gap-2 mb-3">
        <div className="bg-slate-900/40 rounded-lg p-2">
          <p className="text-xs text-slate-500">模拟净值</p>
          <p className={`text-lg font-bold font-mono ${nav >= 1 ? 'text-up' : 'text-down'}`}>
            {fmt(nav, 4)}
          </p>
        </div>
        <div className="bg-slate-900/40 rounded-lg p-2">
          <p className="text-xs text-slate-500">累计收益</p>
          <p className={`text-lg font-bold font-mono ${totalRet >= 0 ? 'text-up' : 'text-down'}`}>
            {fmtPct(totalRet)}
          </p>
        </div>
      </div>

      <div className="text-xs text-slate-500 mb-3">
        现金 {fmt(cash, 1)} USDT · 持仓 {positions.length} · 交易 {simStats?.total_trades || 0} 笔
        {simStats?.win_rate != null && (
          <> · 胜率 {(simStats.win_rate * 100).toFixed(0)}%</>
        )}
      </div>

      {/* 当前持仓 */}
      {positions.length > 0 && (
        <>
          <div className="text-xs text-slate-500 mb-1">当前持仓</div>
          <div className="space-y-1.5 mb-3">
            {positions.map((p, i) => <PositionRow key={i} pos={p} />)}
          </div>
        </>
      )}

      {/* 最近交易 */}
      {trades.length > 0 && (
        <>
          <div className="text-xs text-slate-500 mb-1">最近交易</div>
          <div className="space-y-1">
            {trades.slice(-5).reverse().map((t, i) => {
              const isWin = t.pnl >= 0
              return (
                <div key={i} className="flex justify-between text-xs bg-slate-900/40 rounded px-2 py-1">
                  <span>{t.symbol?.replace('/USDT', '')} {t.side?.includes('long') ? '↑' : '↓'}</span>
                  <span className="text-slate-500">{t.reason?.slice(0, 15)}</span>
                  <span className={`font-mono ${isWin ? 'text-up' : 'text-down'}`}>
                    {isWin ? '+' : ''}{t.pnl_pct?.toFixed(1)}%
                  </span>
                </div>
              )
            })}
          </div>
        </>
      )}
    </div>
  )
}
