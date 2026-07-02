import {
  LineChart, Line, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer, ReferenceLine,
} from 'recharts'

const CustomTooltip = ({ active, payload, label }) => {
  if (!active || !payload?.length) return null
  return (
    <div className="bg-card border border-border rounded-lg px-3 py-2 text-xs">
      <p className="text-slate-400">{label}</p>
      <p className="text-up font-mono font-bold">
        NAV {payload[0].value?.toFixed(4)}
      </p>
    </div>
  )
}

export default function EquityChart({ equity }) {
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

  // 每月采样一个点（避免过密）
  const sampled = equity.filter((_, i) => i % 3 === 0 || i === equity.length - 1)

  return (
    <div className="bg-card border border-border rounded-xl p-4">
      <h2 className="text-sm font-semibold text-slate-300 mb-3">📈 净值曲线</h2>
      <ResponsiveContainer width="100%" height={200}>
        <LineChart data={sampled} margin={{ top: 4, right: 8, left: -16, bottom: 0 }}>
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
          <Line
            type="monotone"
            dataKey="nav"
            stroke="#48bb78"
            strokeWidth={2}
            dot={false}
            activeDot={{ r: 4, fill: '#48bb78' }}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}
