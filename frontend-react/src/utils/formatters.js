/** 带正负号的百分比 */
export const fmtPct = (v, dec = 1) =>
  v == null ? '—' : `${v >= 0 ? '+' : ''}${v.toFixed(dec)}%`

/** 普通数字 */
export const fmt = (v, dec = 2) => (v == null ? '—' : v.toFixed(dec))

/** Regime 颜色 */
export const REGIME_COLORS = {
  bull:     '#48bb78',
  trending: '#f6ad55',
  ranging:  '#4299e1',
  bear:     '#fc8181',
  crisis:   '#b794f4',
}

/** 方向文本和颜色 */
export function directionLabel(side, direction) {
  const isLong =
    side?.includes('long') || direction === 'long' || direction === 1
  return {
    text:  isLong ? '↑ 多' : '↓ 空',
    color: isLong ? 'text-up' : 'text-down',
  }
}

/** Badge 样式 */
export function regimeBadgeClass(regime) {
  const map = {
    bull:     'bg-emerald-900/60 text-emerald-300 border-emerald-700',
    trending: 'bg-orange-900/60 text-orange-300 border-orange-700',
    ranging:  'bg-blue-900/60 text-blue-300 border-blue-700',
    bear:     'bg-red-900/60 text-red-300 border-red-700',
    crisis:   'bg-purple-900/60 text-purple-300 border-purple-700',
  }
  return map[regime] || map.ranging
}
