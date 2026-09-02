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

  if (!analysis) return <section className="page-section"><div className="error-panel">缺少三方法真实对比数据。</div></section>

  const q = analysis.methods.find((item) => item.methodId === 'tabular-hrl')!
  const drivers = analysis.qlearningCostDrivers
  const maxDriver = Math.max(...drivers.map((item) => Math.abs(item.delta)), 1)
  const diagnostics = analysis.qlearningDiagnostics

  return (
    <section className="page-section comparison-section" id="comparison">
      <SectionHeading
        index="03"
        kicker="三方法统一口径结果"
        title="先看结论，再解释差距从哪里来"
        description="三种方法使用相同的12个V6冻结案例、信息揭示时点、业务约束、目标函数和独立验证器。结果展示按“可行性—成本—速度—原因—改进”展开。"
      />

      <div className="truth-banner three-method-truth" role="note">
        <div><span>真实冻结测试</span><b>MILP × Benders-CG × 两层Q-learning</b><small>{analysis.methodCaseValidationPasses}/36份方法—案例结果全部通过独立验证</small></div>
        <div><span>证据边界</span><b>合法配对，但不夸大最优性</b><small>12例是演示集合；MILP日初触及时限，差距不是数学最优性Gap</small></div>
      </div>

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
        <div><span>核心结论</span><b>MILP质量最好，Q-learning最快但成本代价明显</b></div>
        <p>Benders-CG相对MILP逐例平均高{percent(analysis.methods.find((item) => item.methodId === 'benders-cg')!.meanPairwiseGapToMilp, 2)}；Q-learning高{percent(q.meanPairwiseGapToMilp, 2)}，相对Benders-CG仍高{percent(analysis.qlearningGapToBendersCg, 2)}。Q-learning完整进程墙钟平均{diagnostics.meanCaseProcessSeconds.toFixed(2)}秒/例，快于两种优化方法，但训练收敛没有转化为高质量方案。</p>
      </aside>

      <div className="subsection-title numbered"><span><i>01</i> 四类业务场景</span><small>每类3个案例，只做描述性配对比较</small></div>
      <div className="three-method-table" role="table" aria-label="三方法按场景成本对照">
        <div className="table-head" role="row"><span>场景</span><span>MILP</span><span>Benders-CG</span><span>Q-learning</span><span>Q相对MILP</span></div>
        {analysis.categories.map((row) => (
          <div key={row.category} role="row">
            <b>{row.label}</b>
            <span>{number(row.milp.meanCost)}</span>
            <span>{number(row['benders-cg'].meanCost)}</span>
            <span>{number(row['tabular-hrl'].meanCost)}</span>
            <strong>{percent(row['tabular-hrl'].meanPairwiseGapToMilp, 2)}</strong>
          </div>
        ))}
      </div>

      <div className="subsection-title numbered"><span><i>02</i> Q-learning为什么差</span><small>用结果分解定位，不把“已收敛”等同于“高质量”</small></div>
      <div className="q-diagnosis-grid">
        <article className="q-driver-card">
          <header><span>COST DRIVER</span><h3>相对MILP的平均成本增量</h3><p>运输、服务短缺和方案变更解释了几乎全部差距。</p></header>
          <div className="delta-bars">
            {drivers.map((item) => (
              <div key={item.key}>
                <span>{item.label}</span>
                <i className={item.delta >= 0 ? 'up' : 'down'} style={{ width: `${Math.max(3, Math.abs(item.delta) / maxDriver * 100)}%` }} />
                <b className={item.delta >= 0 ? 'up' : 'down'}>{item.delta > 0 ? '+' : ''}{number(item.delta)}</b>
              </div>
            ))}
          </div>
        </article>
        <article className="q-structural-card">
          <header><span>STRUCTURAL DIAGNOSIS</span><h3>主要是表达与解码问题</h3><p>增加训练轮数无法突破当前动作和下层规划器的上限。</p></header>
          <div className="diagnosis-facts">
            <div><b>{diagnostics.learnedStateCount}</b><span>实际学习状态</span><small>两个关键特征各只用到1个分箱</small></div>
            <div><b>9</b><span>组合规则动作</span><small>不是逐条班车开行决策</small></div>
            <div><b>{diagnostics.meanExternalMissionTasks.toFixed(1)}</b><span>平均外请任务</span><small>MILP仅{diagnostics.milpMeanExternalMissionTasks.toFixed(1)}</small></div>
            <div><b>{diagnostics.shieldChangedDecisions}/{diagnostics.decisionCount}</b><span>屏蔽改选</span><small>说明屏蔽不是主要损失来源</small></div>
          </div>
        </article>
      </div>

      <div className="subsection-title numbered"><span><i>03</i> 如何改进</span><small>先消除结构偏差，再扩大训练</small></div>
      <div className="improvement-roadmap">
        <article><span>STEP 01 · 解码器</span><h3>先减少冗余班车</h3><p>恢复大算例的逐辆删减，优先删除高成本外请车，并加入班车替换、合并与串点局部搜索。</p><b>最大直接收益</b></article>
        <article><span>STEP 02 · MDP</span><h3>让状态与奖励对齐</h3><p>加入节点车辆、OD积压、临期货量和外请比例；奖励改成增量已发生成本＋终局服务惩罚。</p><b>解决状态混叠</b></article>
        <article><span>STEP 03 · 学习</span><h3>再丰富动作与经验</h3><p>让Q-learning选择加车、删车、外请、串点等明确调整；对训练状态枚举反事实动作，并用训练集MILP解预训练。</p><b>目标：差距20%以内</b></article>
      </div>
      <p className="improvement-potential">若只消除当前运输成本增量，其他成本保持不变，Q-learning相对MILP的平均剩余差距将从{percent(q.meanPairwiseGapToMilp, 1)}降至约{percent(diagnostics.residualGapIfTransportDeltaRemoved, 1)}。这说明提升空间很大，但主要来自重构下层规划器，而不是继续重复现有经验。</p>

      <details className="convergence-boundary">
        <summary>比较为什么合法，又为什么不能称为全局最优性比较？</summary>
        <div>
          <p><b>合法性：</b>三种方法使用相同冻结输入、信息时点、硬约束、成本口径和验证器，36/36份结果均验证通过。</p>
          <p><b>MILP边界：</b>12个日初模型都触及300秒时限，因此“相对MILP差距”是相对已记录MILP可行结果的经验差距。</p>
          <p><b>Benders边界：</b>{paired?.convergence.gapReachedCount ?? 0}/{paired?.convergence.phaseCount ?? 0}个联合阶段达到目标Gap；字段optimal的作用域是固定班车后的货物流恢复。</p>
          <p><b>Q-learning边界：</b>这是上层Q表、启发式班车生成和下层货物LP组成的混合方法，不是端到端纯强化学习。</p>
        </div>
      </details>

      <div className="subsection-title numbered"><span><i>04</i> 逐案例交互图</span><small>切换成本、服务、时间和变更指标</small></div>
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
