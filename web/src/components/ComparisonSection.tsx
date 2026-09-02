import { lazy, Suspense, useMemo, useState } from 'react'
import { categoryLabels, metricOptions, type MetricKey } from '../data/chartUtils'
import type { Category, ComparisonData, MethodId } from '../data/types'
import SectionHeading from './SectionHeading'

const ComparisonChart = lazy(() => import('./ComparisonChart'))

interface ComparisonSectionProps { data: ComparisonData }

function percent(value: number, digits = 1) {
  const sign = value > 0 ? '+' : ''
  return `${sign}${(value * 100).toFixed(digits)}%`
}

function number(value: number, digits = 0) {
  return value.toLocaleString('zh-CN', { maximumFractionDigits: digits })
}

const methodTone: Record<MethodId, string> = {
  milp: 'milp',
  'benders-cg': 'benders',
  'tabular-hrl': 'qlearning',
}

export default function ComparisonSection({ data }: ComparisonSectionProps) {
  const [metricKey, setMetricKey] = useState<MetricKey>('totalCost')
  const [category, setCategory] = useState<Category | 'all'>('all')
  const [chartType, setChartType] = useState<'line' | 'box'>('line')
  const selectedMetric = metricOptions.find((item) => item.key === metricKey)!
  const metrics = useMemo(() => data.metrics.filter((item) => category === 'all' || item.category === category), [category, data.metrics])
  const analysis = data.threeMethodAnalysis
  const paired = data.pairedAnalysis

  if (!analysis) return <section className="page-section"><div className="error-panel">缺少三种方案对比数据。</div></section>

  const q = analysis.methods.find((item) => item.methodId === 'tabular-hrl')!
  const diagnostics = analysis.qlearningDiagnostics

  return (
    <section className="page-section comparison-section" id="comparison">
      <SectionHeading
        index="03"
        kicker="三种解决方案对比"
        title="三种解决方案的结果对比与差距解释"
        description="三种方案使用相同的12个测试案例、信息揭示时点、业务约束、目标函数和独立验证器，以下比较成本、速度与方案结构。"
      />

      <div className="method-scorecards" aria-label="三方法总体表现">
        {analysis.methods.map((method, index) => (
          <article key={method.methodId} className={`method-scorecard ${methodTone[method.methodId]}`}>
            <header><span>0{index + 1}</span><b>{method.label}</b><em>{method.validatedCases}/12 可行</em></header>
            <div className="scorecard-cost"><small>平均总成本</small><strong>{number(method.meanCost)}</strong></div>
            <dl>
              <div><dt>相对MILP逐例差距</dt><dd>{percent(method.meanPairwiseGapToMilp, 2)}</dd></div>
              <div><dt>已接受计划时间</dt><dd>{method.meanRuntimeSeconds.toFixed(2)}秒</dd></div>
              <div><dt>平均班车任务</dt><dd>{method.meanMissionTasks.toFixed(1)}</dd></div>
              <div><dt>其中外请任务</dt><dd>{method.meanExternalMissionTasks.toFixed(1)}</dd></div>
            </dl>
          </article>
        ))}
      </div>

      <aside className="comparison-finding three-way-finding">
        <div><span>对比结论</span><b>MILP成本最低，Benders-CG差距较小，Q-learning—LP速度较快但成本较高</b></div>
        <p>Benders-CG相对MILP逐例平均高{percent(analysis.methods.find((item) => item.methodId === 'benders-cg')!.meanPairwiseGapToMilp, 2)}；Q-learning—LP高{percent(q.meanPairwiseGapToMilp, 2)}，相对Benders-CG高{percent(analysis.qlearningGapToBendersCg, 2)}。Q-learning—LP完整进程平均{diagnostics.meanCaseProcessSeconds.toFixed(2)}秒/例。</p>
      </aside>

      <div className="subsection-title numbered"><span><i>01</i> 四类业务场景</span><small>每类3个案例，只做描述性配对比较</small></div>
      <div className="three-method-table" role="table" aria-label="三方法按场景成本对照">
        <div className="table-head" role="row"><span>场景</span><span>MILP</span><span>Benders-CG</span><span>Benders相对MILP</span><span>Q-learning—LP</span><span>Q相对MILP</span></div>
        {analysis.categories.map((row) => (
          <div key={row.category} role="row">
            <b>{row.label}</b>
            <span>{number(row.milp.meanCost)}</span>
            <span>{number(row['benders-cg'].meanCost)}</span>
            <strong>{percent(row['benders-cg'].meanPairwiseGapToMilp, 2)}</strong>
            <span>{number(row['tabular-hrl'].meanCost)}</span>
            <strong>{percent(row['tabular-hrl'].meanPairwiseGapToMilp, 2)}</strong>
          </div>
        ))}
      </div>

      <details className="convergence-boundary">
        <summary>比较口径与最优性说明</summary>
        <div>
          <p><b>统一口径：</b>三种方案使用相同输入、信息时点、约束、成本和验证器，因此可以逐案例比较。</p>
          <p><b>MILP：</b>12个日初模型均触及300秒上限，所以相对MILP的百分比是相对本次MILP可行结果的经验差距。</p>
          <p><b>Benders-CG：</b>{paired?.convergence.gapReachedCount ?? 0}/{paired?.convergence.phaseCount ?? 0}个动态阶段达到5%目标Gap。</p>
          <p><b>Q-learning—LP：</b>由上层单张Q表、班车规则解码器和下层货物LP组成。</p>
        </div>
      </details>

      <div className="subsection-title numbered"><span><i>02</i> 12个案例的指标对比</span><small>切换成本、服务、时间和方案变更指标</small></div>
      <div className="chart-controls">
        <label>指标<select value={metricKey} onChange={(event) => setMetricKey(event.target.value as MetricKey)}>{metricOptions.map((item) => <option key={item.key} value={item.key}>{item.label}</option>)}</select></label>
        <label>场景<select value={category} onChange={(event) => setCategory(event.target.value as Category | 'all')}>{Object.entries(categoryLabels).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label>
        <div className="segmented" aria-label="图形类型">
          <button className={chartType === 'line' ? 'active' : ''} type="button" onClick={() => setChartType('line')}>逐案例折线</button>
          <button className={chartType === 'box' ? 'active' : ''} type="button" onClick={() => setChartType('box')}>方法箱型图</button>
        </div>
      </div>
      <div className="chart-shell">
        <Suspense fallback={<div className="chart-loading">正在加载可视化组件…</div>}>
          <ComparisonChart metrics={metrics} metricKey={metricKey} chartType={chartType} unit={selectedMetric.unit} />
        </Suspense>
      </div>
      <p className="stat-note">运行时间主图使用各结果文件中“日初＋已接受滚动计划”的累计时间。Q-learning完整进程墙钟还包含失败候选、IO和验证，因此另行报告为{diagnostics.meanCaseProcessSeconds.toFixed(2)}秒/例。每类仅3例，不进行显著性检验。</p>
    </section>
  )
}
