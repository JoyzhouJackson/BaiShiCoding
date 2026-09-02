import type { ComparisonData } from '../data/types'
import SectionHeading from './SectionHeading'

function percent(value: number) {
  return `${value > 0 ? '+' : ''}${(value * 100).toFixed(2)}%`
}

export default function ConclusionSection({ data }: { data: ComparisonData }) {
  const analysis = data.threeMethodAnalysis
  if (!analysis) return null
  const milp = analysis.methods.find((item) => item.methodId === 'milp')!
  const benders = analysis.methods.find((item) => item.methodId === 'benders-cg')!
  const q = analysis.methods.find((item) => item.methodId === 'tabular-hrl')!
  const diagnostics = analysis.qlearningDiagnostics

  return (
    <section className="page-section conclusion-section" id="conclusion">
      <SectionHeading
        index="05"
        kicker="研究总结"
        title="结论、思考与展望"
        description="分别总结三种解决方案的结果、局限与后续研究方向。"
      />
      <div className="conclusion-hero">
        <div><span className="eyebrow">OVERALL RESULT</span><h3>三种方案均能完成动态运输计划，但在解质量、速度和扩展方式上各有取舍</h3><p>MILP平均成本{Math.round(milp.meanCost).toLocaleString('zh-CN')}；Benders-CG逐例平均高{percent(benders.meanPairwiseGapToMilp)}；Q-learning—LP逐例平均高{percent(q.meanPairwiseGapToMilp)}，完整进程平均{diagnostics.meanCaseProcessSeconds.toFixed(0)}秒/例。</p></div>
      </div>
      <div className="conclusion-columns">
        <article><span>01</span><h3>MILP联合决策</h3><ul><li>本组案例平均成本最低，是当前解质量基准。</li><li>能同时权衡班车、货物行程、货量和服务水平。</li><li>日初规划均运行至300秒，尚未证明全局最优。</li><li>后续重点是候选动态扩充、热启动和分解加速。</li></ul></article>
        <article><span>02</span><h3>Benders分解＋列生成</h3><ul><li>把班车主问题与货物流列生成清晰分开。</li><li>平均成本相对MILP高{percent(benders.meanPairwiseGapToMilp)}。</li><li>69/99个动态阶段达到5%目标Gap，切割与列生成仍有改进空间。</li><li>后续重点是强割、多割、稳定化定价和路径池复用。</li></ul></article>
        <article><span>03</span><h3>Q-learning—LP</h3><ul><li>5个seed均收敛，12个测试案例均得到可行方案。</li><li>完整进程平均{diagnostics.meanCaseProcessSeconds.toFixed(0)}秒/例，但平均成本仍明显偏高。</li><li>主要问题是状态混叠、规则动作过粗和外请班车过量。</li><li>后续重点是局部状态、原子动作、奖励对齐和班车局部搜索。</li></ul></article>
      </div>
      <div className="final-boundary"><b>我的最终感悟</b><p>这次比较让我认识到，不同方法的价值不能只用成本或速度单独判断。MILP提供了解质量基准，Benders与列生成展示了利用问题结构扩展求解的可能性，Q-learning—LP则验证了快速生成可行方案的潜力。Q-learning当前的差距并不意味着强化学习不适合，而是说明状态、动作、奖励和下层方案生成必须与业务决策紧密对应。未来我希望以MILP结果作为学习与评价基准，逐步改进Q-learning的班车调整能力，并研究兼顾解质量、响应速度和大规模适用性的混合优化方法。</p></div>
    </section>
  )
}
