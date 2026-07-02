/**
 * 数据拉取 Hook
 *
 * 本地开发：代理到 Flask API（localhost:5555）
 * 生产环境（Vercel）：直接读取 GitHub Raw API
 *
 * GitHub 仓库里的 data/*.json 通过 GitHub Actions 或手动 git push 更新
 */
import useSWR from 'swr'

// 你的 GitHub 用户名和仓库名
const GITHUB_USER = 'wangCy021005'
const GITHUB_REPO = 'binance_strategy'
const GITHUB_BRANCH = 'main'

function githubRaw(path) {
  return `https://raw.githubusercontent.com/${GITHUB_USER}/${GITHUB_REPO}/${GITHUB_BRANCH}/${path}`
}

const fetcher = (url) =>
  fetch(url, { cache: 'no-store' }).then((r) => {
    if (!r.ok) throw new Error(`HTTP ${r.status}`)
    return r.json()
  })

/** 判断是否在生产环境（Vercel）*/
const isProd = import.meta.env.PROD

/** 构建 URL：本地 → Flask API，生产 → GitHub Raw */
function apiUrl(path, githubPath) {
  if (isProd) return githubRaw(githubPath || path)
  return path
}

// ── 各数据 Hook ────────────────────────────────────────────────────────────

export function useStats() {
  const url = apiUrl('/api/stats', 'data/latest.json')
  const { data, error, isLoading } = useSWR(url, fetcher, {
    refreshInterval: 5 * 60 * 1000,
  })

  // 生产环境从 latest.json 里提取 stats
  const stats = isProd && data ? data.stats : data

  return {
    stats,
    meta: isProd && data ? data.meta : null,
    isLoading,
    isError: !!error,
  }
}

export function useEquity() {
  const url = apiUrl('/api/equity', 'data/latest.json')
  const { data, error, isLoading } = useSWR(url, fetcher, {
    refreshInterval: 10 * 60 * 1000,
  })

  // 生产：从 latest.json 提取 equity 数组
  const equity = isProd && data
    ? (data.equity || []).map((e) => ({ t: e.time?.slice(0, 10), nav: e.nav }))
    : data

  return { equity, isLoading, isError: !!error }
}

export function useTrades() {
  const url = apiUrl('/api/trades', 'data/latest.json')
  const { data, error, isLoading } = useSWR(url, fetcher, {
    refreshInterval: 10 * 60 * 1000,
  })

  const trades = isProd && data
    ? (data.trades || [])
        .filter((t) => 'pnl_pct' in t)
        .slice(-50)
        .map((t) => ({
          time: t.time?.slice(0, 10),
          symbol: t.symbol,
          side: t.side,
          pnl: +(t.pnl_pct * 100).toFixed(2),
          reason: t.reason?.slice(0, 30),
        }))
    : data

  return { trades: trades || [], isLoading, isError: !!error }
}

export function useRegime() {
  const url = apiUrl('/api/regime', 'data/latest.json')
  const { data, error, isLoading } = useSWR(url, fetcher, {
    refreshInterval: 10 * 60 * 1000,
  })

  const regime = isProd && data ? data.regime_dist : data

  return { regime: regime || {}, isLoading, isError: !!error }
}

export function useLiveState() {
  const url = apiUrl('/api/live', 'data/live_state.json')
  const { data, error, isLoading } = useSWR(url, fetcher, {
    refreshInterval: 60 * 1000,
  })
  return { live: data, isLoading, isError: !!error }
}

export function useSignals() {
  // 生产环境读取预先生成的 signals 文件（live 脚本运行时写入）
  const url = apiUrl('/api/signals', 'data/live_signals.json')
  const { data, error, isLoading, mutate } = useSWR(url, fetcher, {
    refreshInterval: 5 * 60 * 1000,
  })
  return { signals: data, isLoading, isError: !!error, refresh: mutate }
}
