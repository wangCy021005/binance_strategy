export default function TradesTable({ trades }) {
  const list = [...(trades || [])].reverse().slice(0, 25)

  return (
    <div className="bg-card border border-border rounded-xl p-4">
      <h2 className="text-sm font-semibold text-slate-300 mb-3">📋 近期交易</h2>
      <div className="overflow-y-auto max-h-64">
        <table className="w-full text-xs">
          <thead>
            <tr className="text-slate-500 border-b border-slate-700">
              <th className="text-left pb-2 font-medium">时间</th>
              <th className="text-left pb-2 font-medium">品种</th>
              <th className="text-right pb-2 font-medium">盈亏</th>
            </tr>
          </thead>
          <tbody>
            {!trades ? (
              [...Array(8)].map((_, i) => (
                <tr key={i}>
                  <td colSpan={3} className="py-1">
                    <div className="h-4 bg-slate-900/60 rounded animate-pulse w-full" />
                  </td>
                </tr>
              ))
            ) : list.length === 0 ? (
              <tr>
                <td colSpan={3} className="text-center py-6 text-slate-500">
                  暂无交易记录
                </td>
              </tr>
            ) : (
              list.map((t, i) => {
                const isLong = t.side?.includes('long')
                const isWin  = t.pnl >= 0
                return (
                  <tr key={i} className="border-b border-slate-800/50 hover:bg-slate-900/30 transition-colors">
                    <td className="py-1.5 text-slate-500">
                      {t.time?.slice(5)}
                    </td>
                    <td className="py-1.5">
                      <span className={`mr-1 ${isLong ? 'text-up' : 'text-down'}`}>
                        {isLong ? '↑' : '↓'}
                      </span>
                      {t.symbol?.replace('/USDT', '')}
                    </td>
                    <td className={`py-1.5 text-right font-mono font-medium ${
                      isWin ? 'text-up' : 'text-down'
                    }`}>
                      {isWin ? '+' : ''}{t.pnl?.toFixed(1)}%
                    </td>
                  </tr>
                )
              })
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}
