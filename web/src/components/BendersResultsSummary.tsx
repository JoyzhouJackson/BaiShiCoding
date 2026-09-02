import type { ComparisonData } from '../data/types'

function percent(value: number) {
  return `${value > 0 ? '+' : ''}${(value * 100).toFixed(2)}%`
}

export default function BendersResultsSummary({ data }: { data: ComparisonData }) {
  const paired = data.pairedAnalysis
  if (!paired) return <div className="error-panel">缺少Benders成对分析数据。</div>
  const convergence = paired.convergence

  return (
    <section className="benders-result-summary" aria-labelledby="benders-results-title">
      <div className="subsection-title"><span id="benders-results-title">真实实验结果</span><small>12个同案例结果与99次动态阶段记录</small></div>
      <div className="experiment-summary">
        <article><span>完成并验证</span><b>{paired.bothValidatedCases}/{paired.pairedCases}</b><small>与MILP相同的12个正式案例</small></article>
        <article><span>完整运行墙钟时间</span><b>{convergence.runElapsedLabel}</b><small>4个外层进程 × 每进程3线程</small></article>
        <article><span>达到目标Gap</span><b>{convergence.gapReachedCount}/{convergence.phaseCount}</b><small>完整Benders动态求解阶段</small></article>
        <article className="inferred-card"><span>相对MILP平均成本</span><b>{percent(paired.weightedCostDeltaRate)}</b><small>相同输入、约束与成本口径</small></article>
      </div>
      <div className="benders-evidence-split">
        <article><span>可行性结论</span><h4>稳定完成全部案例</h4><p>{convergence.warmStartOptimalCount}/{convergence.phaseCount}次初始主问题成功，{convergence.recoveryOptimalCount}/{convergence.phaseCount}次固定班车货物流恢复最优，没有依赖联合MILP兜底。</p></article>
        <article><span>优化质量结论</span><h4>割仍不足以快速收紧下界</h4><p>{convergence.innerTimeLimitCount}次达到内层时间上限，{convergence.stalledDuplicateCutCount}次因重复割停滞；最大记录Gap为{(convergence.maxRecordedGap * 100).toFixed(2)}%。</p></article>
      </div>
      <p className="figure-footnote">这里的“恢复最优”仅指固定班车方案后的连续货物分配；不能据此宣称所有班车开行与货物路由联合阶段全局最优。完整成对成本、运行时间和分项原因见下方“统一口径结果”。</p>
    </section>
  )
}
