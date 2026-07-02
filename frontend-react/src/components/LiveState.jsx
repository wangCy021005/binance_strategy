import { regimeBadgeClass } from '../utils/formatters'

function Row({ label, children }) {
  return (
    <div className="flex items-center justify-between py-1.5 border-b border-slate-800/60 last:border-0">
      <span className="text-xs text-slate-500">{label}</span>
      <span className="text-xs">{children}</span>
    </div>
  )
}

export default function LiveState({ live }) {
  if (!live) {
    return (
      <div className="bg-card border border-border rounded-xl p-4">
        <h2 className="text-sm font-semibold text-slate-300 mb-3">🔴 实盘状态</h2>
        <div className="space-y-2">
          {[...Array(5)].map((_, i) => (
            <div key={i} className="h-6 bg-slate-900/60 rounded animate-pulse" />
          ))}
        </div>
      </div>
    )
  }

  if (!live.timestamp) {
    return (
      <div className="bg-card border border-border rounded-xl p-4">
        <h2 className="text-sm font-semibold text-slate-300 mb-3">🔴 实盘状态</h2>
        <p className="text-xs text-slate-500 py-4 text-center">
          暂无实盘记录<br />
          <span className="text-slate-600">先运行 run_live.py</span>
        </p>
      </div>
    )
  }

  const regime  = live.regime || '—'
  const opened  = live.opened || []
  const closed  = live.closed || []
  const targets = live.targets || []

  return (
    <div className="bg-card border border-border rounded-xl p-4">
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-sm font-semibold text-slate-300">🔴 实盘状态</h2>
        <span className={`text-xs px-2 py-0.5 rounded-full border ${
          live.dry_run
            ? 'bg-yellow-900/50 text-yellow-300 border-yellow-700'
            : 'bg-red-900/50 text-red-300 border-red-700'
        }`}>
          {live.dry_run ? 'DRY RUN' : '实盘中 🔴'}
        </span>
      </div>

      <Row label="最后运行">
        {live.timestamp?.slice(0, 16).replace('T', ' ')}
      </Row>
      <Row label="Regime">
        <span className={`px-2 py-0.5 rounded-full border text-xs ${regimeBadgeClass(regime)}`}>
          {regime.toUpperCase()}
        </span>
      </Row>
      <Row label="风控">
        <span className={live.risk_level === 'NORMAL' ? 'text-up' : 'text-down'}>
          {live.risk_level || '—'}
        </span>
      </Row>
      <Row label="账户">
        <span className="text-blue font-mono">
          {live.portfolio?.toFixed(2) || '—'} USDT
        </span>
      </Row>

      {/* 今日操作 */}
      {(opened.length > 0 || closed.length > 0) && (
        <>
          <div className="text-xs text-slate-500 mt-3 mb-1">今日操作</div>
          {opened.length > 0 && (
            <div className="text-xs flex gap-1 flex-wrap">
              <span className="text-slate-500">开仓</span>
              {opened.map((s) => (
                <span key={s} className="bg-emerald-900/50 text-emerald-300 px-1.5 rounded">
                  {s.replace('/USDT', '')}
                </span>
              ))}
            </div>
          )}
          {closed.length > 0 && (
            <div className="text-xs flex gap-1 flex-wrap mt-1">
              <span className="text-slate-500">平仓</span>
              {closed.map((s) => (
                <span key={s} className="bg-red-900/50 text-red-300 px-1.5 rounded">
                  {s.replace('/USDT', '')}
                </span>
              ))}
            </div>
          )}
        </>
      )}

      {/* 目标仓位 */}
      {targets.length > 0 && (
        <>
          <div className="text-xs text-slate-500 mt-3 mb-1">目标仓位</div>
          <div className="space-y-1">
            {targets.map((t, i) => {
              const isLong = t.direction > 0
              return (
                <div key={i} className="flex justify-between text-xs">
                  <span className={isLong ? 'text-up' : 'text-down'}>
                    {isLong ? '↑' : '↓'} {t.symbol?.replace('/USDT', '')}
                  </span>
                  <span className="text-slate-400 font-mono">
                    {t.size_usdt?.toFixed(0)} U
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
