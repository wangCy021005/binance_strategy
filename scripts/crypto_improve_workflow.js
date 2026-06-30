export const meta = {
  name: 'crypto-improve',
  description: '币安量化策略完整改进循环：回测→分析师→人工卡点→开发→CR→验证',
  phases: [
    { title: '回测', detail: '运行最新代码的完整回测' },
    { title: '分析师诊断', detail: '5维度分析（知识库/代码/年度统计/交易质量/BTC基准背离）' },
    { title: '开发者修复', detail: '根据诊断修改代码' },
    { title: 'CR 审查', detail: 'CR Agent 审查 diff' },
    { title: '回测验证', detail: '验证修复效果' },
    { title: '目标评估', detail: '判断是否达到实盘就绪标准' },
  ],
}

// ── 目标指标（知识库第21课 Quality Gate）────────────────────────────────────
// 币安合约：无T+1，可做空，杠杆可用，手续费0.04%（远低于A股）
const TARGETS = (args && args.targets) || {
  sharpe:          1.5,   // 实盘折半后 0.75+（加密波动大，1.5是高标准）
  annual_return:   30,    // 年化30%（加密市场机会多，但BTC本身约16%/年）
  max_drawdown:   -25,    // -25%（加密允许比A股更大的回撤）
  total_trades:    200,   // 足够的统计样本
  win_rate_min:    0.45,  // 胜率≥45%才考虑加杠杆
  milestone_sharpe:        0.7,
  milestone_annual_return: 16,  // BTC同期年化水平
}

// ── 运行参数 ────────────────────────────────────────────────────────────────
const APPROVED_FIXES = (args && args.approved_fixes) || null
const PR_MERGED      = (args && args.pr_merged)      || false
const ITERATION      = (args && args.iteration)      || 1
const PROJECT_ROOT   = '/Users/wangcy/binance_strategy'
const VENV_PYTHON    = `${PROJECT_ROOT}/../hot_sector_strategy/.venv/bin/python`

// ─────────────────────────────────────────────────────────────────────────────
// Phase 1: 读取回测结果
// ─────────────────────────────────────────────────────────────────────────────
phase('回测')

let currentMetrics = null

if (PR_MERGED || ITERATION === 1) {
  const backtestAgent = await agent(
    PR_MERGED
      ? `运行币安量化策略完整回测：
1. cd ${PROJECT_ROOT}
2. 运行：${VENV_PYTHON} backend/run_backtest.py
3. 等待完成（看到"币安量化策略回测结果"字样）
4. 读取 ${PROJECT_ROOT}/data/latest.json

返回 JSON: annual_return, sharpe, max_drawdown, total_trades, win_rate, backtest_success`
      : `读取 ${PROJECT_ROOT}/data/latest.json，返回当前回测指标。
字段：annual_return, sharpe, max_drawdown, total_trades, win_rate, backtest_success(设为true)`,
    {
      label: PR_MERGED ? '运行回测' : '读取现有结果',
      phase: '回测',
      schema: {
        type: 'object',
        properties: {
          annual_return:    { type: 'number' },
          sharpe:           { type: 'number' },
          max_drawdown:     { type: 'number' },
          total_trades:     { type: 'number' },
          win_rate:         { type: 'number' },
          backtest_success: { type: 'boolean' },
        },
        required: ['backtest_success', 'sharpe', 'annual_return', 'total_trades'],
      },
    }
  )
  currentMetrics = backtestAgent
} else {
  currentMetrics = args.last_metrics || {
    annual_return: 0, sharpe: 0, total_trades: 0, win_rate: 0, backtest_success: true
  }
}

log(`当前指标: 年化=${(currentMetrics.annual_return||0).toFixed(2)}%  Sharpe=${(currentMetrics.sharpe||0).toFixed(3)}  交易=${currentMetrics.total_trades||0}笔  胜率=${((currentMetrics.win_rate||0)*100).toFixed(1)}%`)

// 检查是否已达最终目标
const finalTargetsMet =
  (currentMetrics.sharpe||0) >= TARGETS.sharpe &&
  (currentMetrics.annual_return||0) >= TARGETS.annual_return &&
  (currentMetrics.total_trades||0) >= TARGETS.total_trades

if (finalTargetsMet) {
  log('🎉 所有目标已达成！策略实盘就绪，循环结束。')
  return { iteration: ITERATION, status: 'targets_met', metrics: currentMetrics }
}

// ─────────────────────────────────────────────────────────────────────────────
// Phase 2: 分析师诊断（5维度并行）
// ─────────────────────────────────────────────────────────────────────────────
phase('分析师诊断')

// 加密特有分析维度：
//   1. 知识库层 → 通用量化原则 + 加密市场特殊性
//   2. 代码层   → config/strategies/regime 实现缺陷
//   3. 时序统计层 → 年度/Regime分布/各资产贡献
//   4. 交易质量层 → 卖后10日 + 资金费率贡献 + Alpha因子效果
//   5. BTC基准背离层 → 策略净值 vs BTC 的背离分析
const [kbInsights, codeState, yearData, tradeQuality, btcDivAnalysis] = await parallel([

  // ── 维度1：知识库（完整读全22章+4附录）────────────────────────────────────
  () => agent(`
你是加密量化策略的知识库分析师。

## 核心要求：每章必须完整读完
使用 Read 工具读取以下目录的所有章节（逐章完整阅读）：
${PROJECT_ROOT}/knowledge/quant-book/

## 加密市场 vs A股的关键差异（读完章节后结合这些差异分析）
| 特性 | A股 | 币安合约 |
|------|-----|---------|
| 做空 | 极难 | 永续合约随时做空 |
| T+1 | 是 | 否（即时交易）|
| 涨跌幅限制 | ±10% | 无限制 |
| 资金费率 | 无 | 每8小时结算 |
| 动量IC | 负（短期反转） | 正（趋势延续）|
| 手续费 | 0.16%/次 | 0.04%/次 |

## 当前问题
年化=${(currentMetrics.annual_return||0).toFixed(2)}%，Sharpe=${(currentMetrics.sharpe||0).toFixed(3)}
最大回撤=${(currentMetrics.max_drawdown||0).toFixed(2)}%，胜率=${((currentMetrics.win_rate||0)*100).toFixed(1)}%

找出知识库中与加密市场实际差距最大的原则（重点关注：
- 仓位管理：Kelly公式在加密波动下的适用性
- Regime识别：ADX在加密中是否有效
- 资金费率套利：知识库是否有对应内容
- 风险控制：加密的熔断参数如何设置）

每条原则格式：[第X课§X.X 原文] → 加密适用性分析 → 当前代码是否正确应用`, { label: '读知识库', phase: '分析师诊断' }),

  // ── 维度2：代码实现 ───────────────────────────────────────────────────────
  () => agent(`
读取以下文件，分析代码实现质量：
1. ${PROJECT_ROOT}/backend/config.py           # 所有参数
2. ${PROJECT_ROOT}/backend/agents/regime_agent.py  # Regime识别逻辑
3. ${PROJECT_ROOT}/backend/strategies/momentum.py  # 动量策略
4. ${PROJECT_ROOT}/backend/strategies/funding_arb.py # 资金费率套利
5. ${PROJECT_ROOT}/backend/core/alpha_factor.py    # AlphaGPT因子

分析要点：
- Regime weights是否合理（bull/ranging/bear/crisis权重）
- 动量信号的时间窗口是否适合加密（4h K线 × 42/126/252周期 = 7/21/42天）
- 资金费率套利的阈值设置（当前>0.1%做空，<-0.05%做多）
- Alpha因子（HL_RANGE × VOL_RATIO）是否有效利用

指出代码中可能的bug和改进点。`, { label: '读代码', phase: '分析师诊断' }),

  // ── 维度3：时序统计 ────────────────────────────────────────────────────────
  () => agent(`
运行以下分析脚本并返回结果：

\`\`\`python
import json, sys
sys.path.insert(0, '${PROJECT_ROOT}/backend')
data = json.load(open('${PROJECT_ROOT}/data/latest.json'))
equity = data['equity']
trades = data.get('trades', [])

# 年度收益
years = {}
for pt in equity:
    y = pt['time'][:4]
    years.setdefault(y, []).append(float(pt.get('nav', 1.0)))

result = {'year_stats': [], 'strategy_dist': {}, 'regime_dist': {}}
prev = 1.0
for y in sorted(years):
    navs = years[y]
    ret = (navs[-1] - prev) / prev * 100
    yr_trades = [t for t in trades if t.get('time', '')[:4] == y]
    result['year_stats'].append({'year': y, 'return_pct': round(ret,2), 'trades': len(yr_trades)})
    prev = navs[-1]

# 策略分布
for t in trades:
    if 'close' in t.get('side', ''):
        s = t.get('strategy', '?')
        result['strategy_dist'][s] = result['strategy_dist'].get(s,0) + 1

# Regime 分布（from latest.json regime字段）
regime_data = data.get('regime', [])
if regime_data:
    total = len(regime_data)
    for r_item in regime_data:
        r = r_item[1] if isinstance(r_item, list) else r_item.get('regime','?')
        result['regime_dist'][r] = result['regime_dist'].get(r,0) + 1
    for k in result['regime_dist']:
        result['regime_dist'][k] = round(result['regime_dist'][k]/total*100, 1)

import json as j
print(j.dumps(result, ensure_ascii=False))
\`\`\`

执行：cd ${PROJECT_ROOT} && ${VENV_PYTHON} -c "<上面的代码>"
返回JSON结果。`, { label: '年度统计', phase: '分析师诊断' }),

  // ── 维度4：交易质量（卖后10日 + Alpha因子效果）──────────────────────────────
  () => agent(`
运行以下交易质量分析脚本：

\`\`\`python
import json, sqlite3, sys
import pandas as pd
sys.path.insert(0, '${PROJECT_ROOT}/backend')

data = json.load(open('${PROJECT_ROOT}/data/latest.json'))
all_trades = data.get('trades', [])

# 找卖出交易
closes = [t for t in all_trades if 'close' in t.get('side','') and t.get('pnl_pct') is not None]
if not closes:
    print(json.dumps({'error': '无平仓记录'}))
    exit()

closes.sort(key=lambda x: x.get('pnl_pct',0))
big_losers  = closes[:6]
big_winners = closes[-6:]

conn = sqlite3.connect('${PROJECT_ROOT}/cache_db/crypto_data.db')

def get_window(symbol, center_time, n=10):
    sym_db = symbol.replace('/', '')
    df = pd.read_sql_query(
        "SELECT open_time, close FROM ohlcv WHERE symbol=? AND timeframe='4h' ORDER BY open_time",
        conn, params=(sym_db,)
    )
    if df.empty: return None
    df = df.drop_duplicates('open_time').set_index('open_time')
    times = df.index.tolist()
    # 找最近的时间点
    ct = center_time[:16]
    matching = [t for t in times if t[:16] == ct]
    if not matching:
        matching = [t for t in times if t[:10] == center_time[:10]]
    if not matching: return None
    ci = times.index(matching[0])
    start = max(0, ci-n)
    end   = min(len(times), ci+n+1)
    sub   = df.iloc[start:end].copy()
    base  = float(df.iloc[ci]['close'])
    sub['rel'] = (sub['close'].astype(float)/base - 1)*100
    sub['day'] = list(range(start-ci, end-ci))
    return sub

def exit_score(post_10d, pnl_pct):
    score = 5.0
    if post_10d and len(post_10d) >= 3:
        final = post_10d[-1]
        if final < -5: score += 3.0
        elif final < -2: score += 1.5
        elif final > 8: score -= 3.0
        elif final > 3: score -= 1.5
    if pnl_pct > 10: score += 1.0
    elif pnl_pct < -5: score -= 1.0
    return max(0, min(10, round(score, 1)))

def analyze_group(group):
    results = []
    for t in group:
        sym   = t.get('symbol','?')
        time_ = t.get('time','')
        pnl   = t.get('pnl_pct', 0) * 100 if t.get('pnl_pct') else 0
        strat = t.get('strategy','?')

        post_pattern = []
        w2 = get_window(sym, time_, n=12)
        if w2 is not None:
            post = w2[w2['day'] > 0]['rel'].values
            post_pattern = [round(float(x),1) for x in post[:10]]

        x_score = exit_score(post_pattern, pnl)

        results.append({
            'symbol': sym, 'strategy': strat,
            'pnl_pct': round(pnl,1), 'time': time_[:10],
            'post_10d': post_pattern,
            'exit_score': x_score,
        })
    return results

result = {
    'big_losers':  analyze_group(big_losers),
    'big_winners': analyze_group(big_winners),
}

winners_up = sum(1 for r in result['big_winners'] if r['post_10d'] and r['post_10d'][-1]>0)
losers_down= sum(1 for r in result['big_losers']  if r['post_10d'] and r['post_10d'][-1]<0)

def avg(lst): return round(sum(lst)/len(lst),1) if lst else 0

result['summary'] = {
    '大赢止盈后10日继续涨': f"{winners_up}/{len(result['big_winners'])}",
    '大亏止损后10日继续跌': f"{losers_down}/{len(result['big_losers'])}",
    '大赢平均出场分':  avg([r['exit_score'] for r in result['big_winners']]),
    '大亏平均出场分':  avg([r['exit_score'] for r in result['big_losers']]),
}
conn.close()
import json as j
print(j.dumps(result, ensure_ascii=False))
\`\`\`

执行：cd ${PROJECT_ROOT} && ${VENV_PYTHON} -c "<上面的代码>"
返回JSON结果，含 big_losers、big_winners、summary。`, { label: '交易质量分析', phase: '分析师诊断' }),

  // ── 维度5：BTC基准背离诊断 ────────────────────────────────────────────────
  () => agent(`
运行以下BTC基准背离分析脚本：

\`\`\`python
import json, sqlite3
import pandas as pd
import numpy as np

data = json.load(open('${PROJECT_ROOT}/data/latest.json'))
equity = data['equity']
trades = data.get('trades', [])

# 加载BTC价格作为基准
conn = sqlite3.connect('${PROJECT_ROOT}/cache_db/crypto_data.db')
btc = pd.read_sql_query(
    "SELECT open_time, close FROM ohlcv WHERE symbol='BTCUSDT' AND timeframe='4h' ORDER BY open_time",
    conn)
conn.close()
btc = btc.drop_duplicates('open_time').set_index('open_time')['close'].astype(float)
btc_norm = btc / btc.iloc[0]  # 从1.0开始归一化

# 构建策略净值序列
nav_series = {e['time']: float(e.get('nav',1.0)) for e in equity}

# 对齐
rel = []
for t, nav in sorted(nav_series.items()):
    btc_nav = btc_norm.get(t)
    if btc_nav:
        rel.append({'time': t, 'nav': nav, 'btc': float(btc_nav), 'diff': nav - float(btc_nav)})

# 找背离期（策略持续跑输BTC超过5%）
WINDOW=120   # 120根4h K线 = 20天
DIV_THRESH=-0.05
periods = []
in_div = False
start_t = None

for i in range(WINDOW, len(rel)):
    window_avg = sum(r['diff'] for r in rel[i-WINDOW:i]) / WINDOW
    if not in_div and window_avg < DIV_THRESH:
        in_div = True; start_t = rel[i-WINDOW]['time']
    elif in_div and window_avg >= DIV_THRESH:
        periods.append({'start': start_t, 'end': rel[i]['time']})
        in_div = False
if in_div:
    periods.append({'start': start_t, 'end': rel[-1]['time']})

# 分析每个背离期
buy_dates = set(t['time'][:10] for t in trades if 'open' in t.get('side',''))
results = []
for p in periods[:5]:
    seg = [r for r in rel if p['start'] <= r['time'] <= p['end']]
    if not seg: continue
    btc_gain = round((seg[-1]['btc'] - seg[0]['btc']) / seg[0]['btc'] * 100, 1)
    nav_gain = round((seg[-1]['nav'] - seg[0]['nav']) / seg[0]['nav'] * 100, 1)
    buys_in  = sum(1 for d in buy_dates if p['start'][:10] <= d <= p['end'][:10])
    results.append({
        'start': p['start'][:10], 'end': p['end'][:10],
        'days': len(seg),
        'btc_gain': btc_gain, 'nav_gain': nav_gain,
        'relative_gap': round(nav_gain - btc_gain, 1),
        'buys_count': buys_in,
        'diagnosis': (
            '空仓踏空（bull期未交易）' if buys_in < 3 and btc_gain > 10
            else '持仓亏损（信号质量差）' if nav_gain < -5
            else '整体保守（仓位不足）'
        ),
    })

all_diffs = [r['diff'] for r in rel]
import json as j
print(j.dumps({
    'divergence_periods': results,
    'global_stats': {
        'avg_daily_relative_pct': round(sum(all_diffs)/len(all_diffs)*100, 2) if all_diffs else 0,
        'days_outperform': sum(1 for d in all_diffs if d > 0),
        'days_underperform': sum(1 for d in all_diffs if d < 0),
        'total_divergence_periods': len(periods),
    },
}, ensure_ascii=False))
\`\`\`

执行：cd ${PROJECT_ROOT} && ${VENV_PYTHON} -c "<上面的代码>"
返回JSON结果，含 divergence_periods 和 global_stats。`, { label: 'BTC基准背离诊断', phase: '分析师诊断' }),
])

// ─────────────────────────────────────────────────────────────────────────────
// 生成结构化诊断报告
// ─────────────────────────────────────────────────────────────────────────────
const analysis = await agent(`
你是币安量化策略首席分析师。基于以下5个维度生成结构化诊断报告。

## 加密市场特殊性（必须考虑）
- 动量IC在加密市场为正（与A股相反，趋势延续）
- 资金费率是加密特有的Alpha源（知识库无此内容，需单独评估）
- 可做空，可加杠杆（但需要胜率>50%才适合杠杆）
- 24/7交易，无T+1，无涨跌停限制

## 当前指标
年化: ${(currentMetrics.annual_return||0).toFixed(2)}%（里程碑目标: ${TARGETS.milestone_annual_return}%）
Sharpe: ${(currentMetrics.sharpe||0).toFixed(3)}（里程碑目标: ${TARGETS.milestone_sharpe}）
最大回撤: ${(currentMetrics.max_drawdown||0).toFixed(2)}%
交易笔数: ${currentMetrics.total_trades||0}
胜率: ${((currentMetrics.win_rate||0)*100).toFixed(1)}%

## 维度1：知识库原则（加密适配版）
${kbInsights}

## 维度2：代码实现现状
${codeState}

## 维度3：时序统计（年度/Regime分布）
${yearData}

## 维度4：交易质量（出场评分0-10）
${tradeQuality}

## 维度5：BTC基准背离诊断
${btcDivAnalysis}

## 加密特有分析重点

**资金费率套利评估**（维度4数据）：
- 资金费率策略的实际贡献（vs 动量策略）
- 当前阈值（>0.1%做空）是否合适

**杠杆适用性判断**：
- 胜率${((currentMetrics.win_rate||0)*100).toFixed(1)}% ${(currentMetrics.win_rate||0) < 0.50 ? '< 50%：不适合加杠杆（会放大亏损）' : '≥ 50%：可以考虑适度杠杆'}
- Kelly公式：胜率×盈亏比 判断最优仓位

**BTC背离诊断**（维度5）：
- 策略跑赢/跑输BTC的时段分析
- 空仓踏空 vs 持仓亏损

## 输出修复方案

生成 fix_proposals 列表，每条必须包含：
| 字段 | 说明 |
|------|------|
| id | "fix-001"... |
| priority | P0/P1/P2 |
| title | 一句话标题 |
| file | 完整文件路径 |
| description | 具体改法（可直接执行）|
| kb_chapter | 知识库章节+原文引用 |
| data_evidence | 来自维度3/4/5的具体数字 |
| crypto_note | 加密市场特殊考虑（若有）|
| expected_improvement | 预期效果（量化）|
| impact_score | 0-10 |
| confidence_score | 0-10 |
| kb_score | 0-10 |

修复规范：不引入未来数据，参数在config.py中，止损逻辑基于价格（非杠杆P&L）`,
  {
    label: '生成诊断报告',
    phase: '分析师诊断',
    schema: {
      type: 'object',
      properties: {
        summary: { type: 'string' },
        root_causes: {
          type: 'array',
          items: {
            type: 'object',
            properties: {
              issue: { type: 'string' },
              impact: { type: 'string' },
              kb_reference: { type: 'string' },
              priority: { type: 'string' },
            },
            required: ['issue', 'impact', 'priority'],
          },
        },
        fix_proposals: {
          type: 'array',
          items: {
            type: 'object',
            properties: {
              id: { type: 'string' },
              priority: { type: 'string' },
              title: { type: 'string' },
              file: { type: 'string' },
              description: { type: 'string' },
              kb_chapter: { type: 'string' },
              data_evidence: { type: 'string' },
              crypto_note: { type: 'string' },
              expected_improvement: { type: 'string' },
              impact_score: { type: 'number' },
              confidence_score: { type: 'number' },
              kb_score: { type: 'number' },
            },
            required: ['id','priority','title','file','description',
                       'impact_score','confidence_score','kb_score'],
          },
        },
      },
      required: ['summary', 'root_causes', 'fix_proposals'],
    },
  }
)

// ─────────────────────────────────────────────────────────────────────────────
// 输出分析报告
// ─────────────────────────────────────────────────────────────────────────────
log(`\n${'━'.repeat(60)}`)
log(`第 ${ITERATION} 轮分析报告`)
log(`${'━'.repeat(60)}`)
log(`\n当前指标：年化 ${(currentMetrics.annual_return||0).toFixed(2)}% | Sharpe ${(currentMetrics.sharpe||0).toFixed(3)} | 交易 ${currentMetrics.total_trades||0}笔 | 胜率 ${((currentMetrics.win_rate||0)*100).toFixed(1)}%`)
log(`\n核心问题：${analysis.summary}`)
log(`\n根因：`)
for (const rc of (analysis.root_causes||[])) {
  log(`  [${rc.priority}] ${rc.issue} (${rc.kb_reference||''})`)
}

log(`\n修复方案打分总表：`)
log(`  ${'ID'.padEnd(8)} ${'优先级'.padEnd(6)} ${'影响'.padEnd(4)} ${'置信'.padEnd(4)} ${'知识库'.padEnd(6)} 标题`)
for (const f of (analysis.fix_proposals||[])) {
  const title = (f.title||'').slice(0, 50)
  log(`  ${(f.id||'').padEnd(8)} ${(f.priority||'').padEnd(6)} ${String(f.impact_score||0).padEnd(4)} ${String(f.confidence_score||0).padEnd(4)} ${String(f.kb_score||0).padEnd(6)} ${title}`)
}

log(`\n═══ 详细修复方案 ═══`)
for (const f of (analysis.fix_proposals||[]).slice(0,5)) {
  log(`\n[${f.id}] ${f.priority} - ${f.title}`)
  log(`  文件：${f.file||'—'}`)
  log(`  知识库：${(f.kb_chapter||f.kb_reference||'—').slice(0,100)}`)
  log(`  数据：${(f.data_evidence||'—').slice(0,120)}`)
  if (f.crypto_note) log(`  加密特注：${f.crypto_note.slice(0,100)}`)
  log(`  预期效果：${f.expected_improvement||'—'}`)
  log(`  打分：影响=${f.impact_score} 置信=${f.confidence_score} KB=${f.kb_score}`)
}

return {
  status: 'awaiting_approval',
  iteration: ITERATION,
  metrics: currentMetrics,
  analysis: analysis,
}
