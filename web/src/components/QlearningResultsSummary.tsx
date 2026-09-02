import type { ComparisonData } from '../data/types'

function percent(value: number, digits = 2) {
  return `${value > 0 ? '+' : ''}${(value * 100).toFixed(digits)}%`
}

function duration(seconds: number) {
  if (seconds < 60) return `${seconds.toFixed(1)}秒`
  return `${Math.floor(seconds / 60)}分${Math.round(seconds % 60)}秒`
}

export default function QlearningResultsSummary({ data }: { data: ComparisonData }) {
  const analysis = data.threeMethodAnalysis
  if (!analysis) return <div className="error-panel">缺少Q-learning三方法分析数据。</div>
  const q = analysis.methods.find((item) => item.methodId === 'tabular-hrl')!
  const diagnostics = analysis.qlearningDiagnostics

  return (
    <section className="qlearning-result-summary" aria-labelledby="qlearning-results-title">
      <div className="subsection-title"><span id="qlearning-results-title">真实训练与测试结果</span><small>5个seed训练 · 20例验证 · 12例冻结测试</small></div>
      <div className="experiment-summary">
        <article><span>正式测试</span><b>{q.validatedCases}/{analysis.caseCount}</b><small>全部完成并通过统一独立验证器</small></article>
        <article><span>并行seed收敛</span><b>{diagnostics.convergedSeeds}/{diagnostics.totalSeeds}</b><small>策略稳定不等于目标值接近MILP</small></article>
        <article className="inferred-card"><span>相对MILP逐例差距</span><b>{percent(q.meanPairwiseGapToMilp)}</b><small>平均总成本 {Math.round(q.meanCost).toLocaleString('zh-CN')}</small></article>
        <article><span>完整进程时间</span><b>{duration(diagnostics.meanCaseProcessSeconds)}</b><small>含屏蔽尝试、IO与独立验证</small></article>
      </div>
      <div className="q-evidence-grid">
        <article><span>STATE</span><h4>状态表达发生退化</h4><p>Q表只学到{diagnostics.learnedStateCount}个状态；运力压力与服务风险各只使用1个分箱，许多不同网络状态被当作同一状态。</p></article>
        <article><span>ACTION</span><h4>动作是规则，不是班车任务</h4><p>Q表只在9种规则组合中选择，具体开行、串点和外请仍由启发式解码，不能精细逼近MILP方案。</p></article>
        <article><span>DECODER</span><h4>外请任务明显过量</h4><p>平均班车任务{diagnostics.meanMissionTasks.toFixed(1)}项、外请{diagnostics.meanExternalMissionTasks.toFixed(1)}项；MILP分别为{diagnostics.milpMeanMissionTasks.toFixed(1)}和{diagnostics.milpMeanExternalMissionTasks.toFixed(1)}。</p></article>
      </div>
      <p className="figure-footnote">当前方法是“上层表格Q-learning＋启发式班车生成＋下层货物LP＋可行性屏蔽”的混合方法。接受计划累计运行时间平均{q.meanRuntimeSeconds.toFixed(2)}秒/例，但该字段不包含被屏蔽候选的全部尝试时间。</p>
    </section>
  )
}
