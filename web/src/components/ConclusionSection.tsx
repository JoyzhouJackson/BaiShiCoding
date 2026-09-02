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
        kicker="结论、反思与展望"
        title="结果不只回答谁更好，也告诉我们下一步该改哪里"
        description="三种方法都完成了真实冻结测试。这里把可确认的发现、必须保留的证据边界，以及Q-learning的改进路径放在一起。"
      />
      <div className="conclusion-hero">
        <div className="big-number">36<small> /36</small></div>
        <div><span className="eyebrow">VALIDATED METHOD–CASE RESULTS</span><h3>MILP守住解质量，Q-learning验证了快速可行，但尚未学到高质量策略</h3><p>MILP平均成本{Math.round(milp.meanCost).toLocaleString('zh-CN')}；Benders-CG逐例平均高{percent(benders.meanPairwiseGapToMilp)}；Q-learning高{percent(q.meanPairwiseGapToMilp)}。Q-learning完整进程平均{diagnostics.meanCaseProcessSeconds.toFixed(0)}秒/例，速度优势真实存在，但不能掩盖班车任务过多带来的成本损失。</p></div>
      </div>
      <div className="conclusion-columns">
        <article><span>01</span><h3>已经解决</h3><ul><li>建立班车开行与货物路由的统一动态业务模型。</li><li>MILP、Benders-CG与两层Q-learning均完成12例测试。</li><li>三种方法36份结果全部通过同一独立验证器。</li><li>异常触发与每6小时滚动能够在执行锁定下协同运行。</li><li>网页可按同一时钟回放三种真实计划。</li></ul></article>
        <article><span>02</span><h3>关键反思</h3><ul><li>训练收敛只代表Q表稳定，不代表策略接近MILP。</li><li>当前Q-learning只选择9种规则，不能直接控制具体班车。</li><li>实际状态仅16种，运力压力和服务风险分箱失去区分度。</li><li>Q方案平均118项班车任务，MILP为80.8项。</li><li>Q平均外请36.4项，MILP仅8.0项，是运输成本差距的核心。</li></ul></article>
        <article><span>03</span><h3>下一阶段</h3><ul><li>先完善删车、替换、合并与串点局部搜索。</li><li>用节点车辆、OD积压和临期货量重构状态。</li><li>将奖励改为增量成本与终局服务惩罚。</li><li>把动作扩展为明确的加车、删车、外请和串点调整。</li><li>只用训练集MILP标签预训练，并把目标先设为差距20%以内。</li></ul></article>
      </div>
      <div className="final-boundary"><b>最终判断</b><p>当前8节点、12案例规模下，MILP是解质量主方案，Benders-CG是可扩展分解对照，两层Q-learning是快速可行策略原型。Q-learning表现差不是因为测试不可行，也不是seed不稳定，而是状态、动作、奖励和班车解码器存在结构偏差；这也给出了清晰、可验证的下一轮研究路线。</p></div>
    </section>
  )
}
