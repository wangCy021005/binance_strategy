import { PieChart, Pie, Cell, Tooltip, Legend, ResponsiveContainer } from 'recharts'
import { REGIME_COLORS } from '../utils/formatters'

const LABEL_MAP = {
  bull: '牛市', ranging: '震荡', bear: '熊市',
  crisis: '危机', trending: '趋势'
}

export default function RegimeChart({ regime }) {
  if (!regime || !Object.keys(regime).length) {
    return (
      <div className="bg-card border border-border rounded-xl p-4">
        <h2 className="text-sm font-semibold text-slate-300 mb-3">🌡️ Regime 分布</h2>
        <div className="h-48 flex items-center justify-center text-slate-500 animate-pulse text-sm">
          加载中...
        </div>
      </div>
    )
  }

  const total = Object.values(regime).reduce((a, b) => a + b, 0)
  const data = Object.entries(regime)
    .sort((a, b) => b[1] - a[1])
    .map(([key, val]) => ({
      name: `${LABEL_MAP[key] || key} ${((val / total) * 100).toFixed(0)}%`,
      value: val,
      color: REGIME_COLORS[key] || '#a0aec0',
    }))

  return (
    <div className="bg-card border border-border rounded-xl p-4">
      <h2 className="text-sm font-semibold text-slate-300 mb-3">🌡️ Regime 分布</h2>
      <ResponsiveContainer width="100%" height={200}>
        <PieChart>
          <Pie
            data={data}
            cx="50%"
            cy="45%"
            innerRadius={50}
            outerRadius={75}
            paddingAngle={3}
            dataKey="value"
          >
            {data.map((entry, i) => (
              <Cell key={i} fill={entry.color} stroke="transparent" />
            ))}
          </Pie>
          <Tooltip
            formatter={(v) => [`${((v / total) * 100).toFixed(1)}%`, '占比']}
            contentStyle={{ background: '#1a1d2e', border: '1px solid #2d3748', borderRadius: 8, fontSize: 12 }}
          />
          <Legend
            iconSize={10}
            wrapperStyle={{ fontSize: 11, paddingTop: 8 }}
          />
        </PieChart>
      </ResponsiveContainer>
    </div>
  )
}
