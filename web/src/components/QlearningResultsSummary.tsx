import type { ComparisonData } from '../data/types'
import { qCargoRules, qStateRows, qVehicleRules } from '../data/qlearningMechanics'

function percent(value: number, digits = 2) {
  return `${value > 0 ? '+' : ''}${(value * 100).toFixed(digits)}%`
}

function duration(seconds: number) {
  if (seconds < 60) return `${seconds.toFixed(1)}秒`
  return `${Math.floor(seconds / 60)}分${Math.round(seconds % 60)}秒`
}

function number(value: number) {
  return value.toLocaleString('zh-CN', { maximumFractionDigits: 0 })
}

export default function QlearningResultsSummary({ data }: { data: ComparisonData }) {
  const analysis = data.threeMethodAnalysis
  if (!analysis) return <div className="error-panel">缺少Q-learning—LP分析数据。</div>
  const q = analysis.methods.find((item) => item.methodId === 'tabular-hrl')!
  const diagnostics = analysis.qlearningDiagnostics
  const drivers = analysis.qlearningCostDrivers
  const maxDriver = Math.max(...drivers.map((item) => Math.abs(item.delta)), 1)

  return (
    <section className="qlearning-result-summary" aria-labelledby="qlearning-results-title">
      <div className="subsection-title"><span id="qlearning-results-title">训练与测试结果</span><small>5个seed训练 · 20例验证 · 12例测试</small></div>
      <div className="experiment-summary">
        <article><span>正式测试</span><b>{q.validatedCases}/{analysis.caseCount}</b><small>全部完成并通过统一独立验证器</small></article>
        <article><span>并行seed收敛</span><b>{diagnostics.convergedSeeds}/{diagnostics.totalSeeds}</b><small>表示Q值与策略稳定，不代表接近MILP</small></article>
        <article className="inferred-card"><span>相对MILP逐例差距</span><b>{percent(q.meanPairwiseGapToMilp)}</b><small>平均总成本 {Math.round(q.meanCost).toLocaleString('zh-CN')}</small></article>
        <article><span>完整进程时间</span><b>{duration(diagnostics.meanCaseProcessSeconds)}</b><small>包含候选尝试、读写与验证</small></article>
      </div>

      <div className="q-learning-mechanics">
        <article>
          <header><span>Q-TABLE ROWS</span><h3>每一行：5维离散状态</h3></header>
          <div className="q-table-scroll"><table><thead><tr><th>维度</th><th>计算</th><th>编码</th></tr></thead><tbody>
            {qStateRows.map((row) => <tr key={row.dimension}><td>{row.dimension}</td><td>{row.calculation}</td><td>{row.encoding}</td></tr>)}
          </tbody></table></div>
          <p className="q-state-example"><code>2|0|0|1|3</code>：12小时以后、运力压力低、服务风险低、车辆紧张度中、车辆故障。</p>
        </article>
        <article>
          <header><span>Q-TABLE COLUMNS</span><h3>每一列：9种组合规则</h3></header>
          <div className="q-rule-groups">
            <div><b>3种班车规则</b>{qVehicleRules.map((rule) => <p key={rule.name}><strong>{rule.name}</strong>{rule.meaning}</p>)}</div>
            <div><b>3种货物规则</b>{qCargoRules.map((rule) => <p key={rule.name}><strong>{rule.name}</strong>{rule.meaning}</p>)}</div>
          </div>
          <div className="q-action-matrix" aria-label="九种Q表动作">
            <span />{qCargoRules.map((rule) => <b key={rule.name}>{rule.name}</b>)}
            {qVehicleRules.flatMap((vehicle) => [<b key={`${vehicle.name}-head`}>{vehicle.name}</b>, ...qCargoRules.map((cargo) => <span key={`${vehicle.name}-${cargo.name}`}>{vehicle.name.replace('优先', '')}＋{cargo.name.replace('优先', '')}</span>)])}
          </div>
        </article>
      </div>

      <div className="q-update-box">
        <span>Q值如何更新</span>
        <code>Q(s,a) ← Q(s,a) + α [ r + γ max Q(s′,a′) − Q(s,a) ]</code>
        <p><b>r</b> = −当前方案成本/日初基准成本，<b>γ</b> = 1，<b>α</b> = 1/N(s,a)<sup>0.6</sup>。5个seed分别训练同结构Q表，最后逐单元格平均；测试阶段不再更新。</p>
      </div>

      <div className="q-result-diagnosis">
        <article className="q-driver-card">
          <header><span>COST DIFFERENCE</span><h3>Q-learning—LP相对MILP的平均成本增量</h3><p>运输成本是最主要差距，其次是服务不达标惩罚和方案变更成本。</p></header>
          <div className="delta-bars">
            {drivers.map((item) => <div key={item.key}><span>{item.label}</span><i className={item.delta >= 0 ? 'up' : 'down'} style={{ width: `${Math.max(3, Math.abs(item.delta) / maxDriver * 100)}%` }} /><b className={item.delta >= 0 ? 'up' : 'down'}>{item.delta > 0 ? '+' : ''}{number(item.delta)}</b></div>)}
          </div>
        </article>
        <article className="q-structural-card">
          <header><span>OBSERVED STRUCTURE</span><h3>结果反映出的结构问题</h3></header>
          <div className="diagnosis-facts">
            <div><b>{diagnostics.learnedStateCount}</b><span>实际状态</span><small>理论组合较多，但观测状态高度集中</small></div>
            <div><b>9</b><span>规则动作</span><small>不能直接决定加车、删车和串点</small></div>
            <div><b>{diagnostics.meanExternalMissionTasks.toFixed(1)}</b><span>平均外请任务</span><small>MILP为{diagnostics.milpMeanExternalMissionTasks.toFixed(1)}</small></div>
            <div><b>{diagnostics.meanMissionTasks.toFixed(1)}</b><span>平均班车任务</span><small>MILP为{diagnostics.milpMeanMissionTasks.toFixed(1)}</small></div>
          </div>
        </article>
      </div>
      <p className="figure-footnote">接受方案累计规划时间平均{q.meanRuntimeSeconds.toFixed(2)}秒/例；完整进程平均{diagnostics.meanCaseProcessSeconds.toFixed(2)}秒/例，后者还包含未采用候选、读写和独立验证。</p>
    </section>
  )
}
