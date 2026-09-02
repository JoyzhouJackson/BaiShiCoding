import { lazy, Suspense, useMemo, useState } from 'react'
import { categoryLabels, metricOptions, type MetricKey } from '../data/chartUtils'
import type { Category, ComparisonData } from '../data/types'
import SectionHeading from './SectionHeading'

const ComparisonChart = lazy(() => import('./ComparisonChart'))

interface ComparisonSectionProps { data: ComparisonData }

function percent(value: number, digits = 1) {
  const sign = value > 0 ? '+' : ''
  return `${sign}${(value * 100).toFixed(digits)}%`
}

function number(value: number) {
  return value.toLocaleString('zh-CN', { maximumFractionDigits: 0 })
}

export default function ComparisonSection({ data }: ComparisonSectionProps) {
  const [metricKey, setMetricKey] = useState<MetricKey>('totalCost')
  const [category, setCategory] = useState<Category | 'all'>('all')
  const [chartType, setChartType] = useState<'line' | 'box'>('line')
  const selectedMetric = metricOptions.find((item) => item.key === metricKey)!
  const metrics = useMemo(() => data.metrics.filter((item) => category === 'all' || item.category === category), [category, data.metrics])
  const real = metrics.filter((item) => item.dataStatus === 'real')
  const realMethods = data.methods.filter((item) => item.dataStatus === 'real')
  const mockMethods = data.methods.filter((item) => item.dataStatus === 'mock')
  const passed = real.filter((item) => item.validationStatus === 'pass').length
  const paired = data.pairedAnalysis
  const maxPositiveDelta = paired ? Math.max(...paired.costDeltas.map((item) => Math.max(0, item.delta)), 1) : 1

  return (
    <section className="page-section comparison-section" id="comparison">
      <SectionHeading
        index="03"
        kicker="统一口径结果"
        title="同一批案例，拆开看成本、速度与证据边界"
        description="MILP与Benders＋列生成使用相同的12个案例、业务约束、成本系数和300秒调用上限。先给出成对结论，再下钻到逐案例和成本分项。"
      />
      <div className="truth-banner" role="note">
        <div><span>真实成对证据</span><b>{realMethods.map((item) => item.label).join(' × ')}</b><small>{paired?.pairedCases ?? 0}对同案例 · {passed}份方法—案例结果通过独立验证</small></div>
        {mockMethods.length > 0 && <div className="mock-warning"><span>模拟占位</span><b>{mockMethods.map((item) => item.label).join(' / ')}</b><small>不参与排名、结论或统计推断</small></div>}
      </div>

      {paired && (
        <>
          <div className="paired-kpis" aria-label="MILP与Benders成对比较摘要">
            <article><span>可行性</span><b>{paired.bothValidatedCases}/{paired.pairedCases}</b><small>两种方法均完成且验证通过</small></article>
            <article className="negative"><span>平均总成本</span><b>{percent(paired.weightedCostDeltaRate, 2)}</b><small>Benders {number(paired.bendersMeanCost)} / MILP {number(paired.milpMeanCost)}</small></article>
            <article className="negative"><span>平均求解时间</span><b>{percent(paired.runtimeDeltaRate, 1)}</b><small>Benders {number(paired.bendersMeanRuntimeSeconds)}秒 / MILP {number(paired.milpMeanRuntimeSeconds)}秒</small></article>
            <article><span>阶段收敛</span><b>{paired.convergence.gapReachedCount}/{paired.convergence.phaseCount}</b><small>达到目标Gap；其余阶段发布可行恢复方案</small></article>
          </div>

          <div className="paired-analysis-grid">
            <article className="category-comparison-card">
              <header><span>SCENARIO VIEW</span><h3>四类场景的平均成本差异</h3><p>正值表示Benders成本更高；每类只有3对案例，仅作描述性比较。</p></header>
              <div className="category-comparison-table" role="table" aria-label="按场景分类的平均总成本对照">
                <div className="table-head" role="row"><span>场景</span><span>MILP</span><span>Benders</span><span>差异</span></div>
                {paired.categories.map((row) => <div key={row.category} role="row"><b>{row.label}</b><span>{number(row.milpMeanCost)}</span><span>{number(row.bendersMeanCost)}</span><strong>{percent(row.relativeCostDelta, 2)}</strong></div>)}
              </div>
            </article>
            <article className="delta-card">
              <header><span>COST DRIVER</span><h3>多出的成本来自哪里</h3><p>12对案例累计差额；向右为Benders更高，绿色为Benders更低。</p></header>
              <div className="delta-bars">
                {paired.costDeltas.map((item) => (
                  <div key={item.key}>
                    <span>{item.label}</span>
                    <i className={item.delta >= 0 ? 'up' : 'down'} style={{ width: `${Math.max(3, Math.abs(item.delta) / maxPositiveDelta * 100)}%` }} />
                    <b className={item.delta >= 0 ? 'up' : 'down'}>{item.delta > 0 ? '+' : ''}{number(item.delta)}</b>
                  </div>
                ))}
              </div>
            </article>
          </div>

          <aside className="comparison-finding">
            <div><span>PAIRED FINDING</span><b>MILP在本组12个小规模案例中成本更低、速度更快</b></div>
            <p>Benders没有在任何案例中取得更低总成本；最佳差距为 {percent(paired.bestCase.relativeCostDelta, 2)}（{paired.bestCase.caseId}），最大差距为 {percent(paired.worstCase.relativeCostDelta, 2)}（{paired.worstCase.caseId}）。净成本差额主要由变更成本和运输成本构成。</p>
          </aside>

          <details className="convergence-boundary">
            <summary>为什么“12/12结果最优”不等于“99个联合优化阶段全部达到5% Gap”？</summary>
            <div>
              <p><b>已确认：</b>99/99次初始主问题找到方案，99/99次固定班车后的货物流恢复达到最优，因此12个动态案例均可执行并通过业务校验。</p>
              <p><b>不能扩大解释：</b>完整Benders阶段中，{paired.convergence.gapReachedCount}次达到目标Gap，{paired.convergence.innerTimeLimitCount}次达到内层时间上限，{paired.convergence.stalledDuplicateCutCount}次因重复割停滞。最大记录Gap为{percent(paired.convergence.maxRecordedGap, 2)}，出现在{paired.convergence.maxGapCaseId}的日初规划。</p>
              <p>结果字段 <code>optimal</code> 的作用域是 <code>{paired.convergence.statusScope}</code>，即固定班车方案后的货物恢复最优，不代表班车与货物联合问题已证明全局最优。</p>
            </div>
          </details>
        </>
      )}

      <div className="chart-controls">
        <label>指标<select value={metricKey} onChange={(event) => setMetricKey(event.target.value as MetricKey)}>{metricOptions.map((item) => <option key={item.key} value={item.key}>{item.label}</option>)}</select></label>
        <label>场景<select value={category} onChange={(event) => setCategory(event.target.value as Category | 'all')}>{Object.entries(categoryLabels).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label>
        <div className="segmented" aria-label="图形类型">
          <button className={chartType === 'line' ? 'active' : ''} type="button" onClick={() => setChartType('line')}>逐案例折线</button>
          <button className={chartType === 'box' ? 'active' : ''} type="button" onClick={() => setChartType('box')}>方法箱型图</button>
        </div>
      </div>
      <div className={`chart-shell ${mockMethods.length ? 'mock-surface' : ''}`}>
        <Suspense fallback={<div className="chart-loading">正在加载可视化组件…</div>}>
          <ComparisonChart metrics={metrics} metricKey={metricKey} chartType={chartType} unit={selectedMetric.unit} />
        </Suspense>
      </div>
      <p className="stat-note">每类仅3对案例，箱型图和折线用于描述性比较，不进行显著性检验。强化学习仍为模拟占位，始终带水印且不会进入上述结论。</p>
    </section>
  )
}
