import {
  LineChart, Line, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer, ReferenceLine, Legend,
} from 'recharts'

const CustomTooltip = ({ active, payload, label }) => {
  if (!active || !payload?.length) return null
  return (
    <div className="bg-card border border-border rounded-lg px-3 py-2 text-xs">
      <p className="text-slate-400">{label}</p>
      {payload.map((p, i) => (
        <p key={i} className="font-mono font-bold" style={{ color: p.color }}>
          {p.name}: {p.value?.toFixed(4)}
        </p>
      ))}
    </div>
  )
}

export default function EquityChart({ equity, simEquity }) {
  if (!equity?.length) {
    return (
      <div className="bg-card border border-border rounded-xl p-4">
        <h2 className="text-sm font-semibold text-slate-300 mb-3">📈 净值曲线</h2>
        <div className="h-48 flex items-center justify-center text-slate-500 text-sm animate-pulse">
          加载中...
        </div>
      </div>
    )
  }

  // 合并回测净值 + 模拟净值（按日期对齐）
  const simMap = {}
  if (simEquity?.length) {
    simEquity.forEach(e => {
      simMap[e.time?.slice(0, 10)] = e.nav
    })
  }

  const data = equity
    .filter((_, i) => i % 3 === 0 || i === equity.length - 1)
    .map(e => ({
      t: e.t,
      回测: e.nav,
      模拟: simMap[e.t] || null,   // 有则显示
    }))

  // 模拟净值可能超出回测区间，补上额外的点
  if (simEquity?.length) {
    const lastBacktestDate = equity[equity.length - 1]?.t
    simEquity.forEach(e => {
      const d = e.time?.slice(0, 10)
      if (d > lastBacktestDate && !data.find(x => x.t === d)) {
        data.push({ t: d, 回测: null, 模拟: e.nav })
      }
    })
  }

  const hasSim = simEquity?.length > 0

  return (
    <div className="bg-card border border-border rounded-xl p-4">
      <h2 className="text-sm font-semibold text-slate-300 mb-3">
        📈 净值曲线 {hasSim && <span className="text-xs text-slate-500 ml-2">回测 + 实时模拟</span>}
      </h2>
      <ResponsiveContainer width="100%" height={200}>
        <LineChart data={data} margin={{ top: 4, right: 8, left: -16, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#2d3748" />
          <XAxis
            dataKey="t"
            tick={{ fill: '#718096', fontSize: 10 }}
            tickLine={false}
            axisLine={false}
            tickFormatter={(v) => v?.slice(2, 7)}
            interval="preserveStartEnd"
          />
          <YAxis
            tick={{ fill: '#718096', fontSize: 10 }}
            tickLine={false}
            axisLine={false}
            tickFormatter={(v) => v.toFixed(2)}
            domain={['auto', 'auto']}
          />
          <Tooltip content={<CustomTooltip />} />
          <ReferenceLine y={1} stroke="#4a5568" strokeDasharray="4 4" />
          {hasSim && <Legend iconSize={10} wrapperStyle={{ fontSize: 11 }} />}
          <Line type="monotone" dataKey="回测" stroke="#4299e1" strokeWidth={2} dot={false} />
          {hasSim && (
            <Line type="monotone" dataKey="模拟" stroke="#48bb78" strokeWidth={2} dot={false}
              activeDot={{ r: 4 }} connectNulls />
          )}
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}
