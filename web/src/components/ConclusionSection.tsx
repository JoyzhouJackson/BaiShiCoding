import { realMetricsForFindings } from '../data/chartUtils'
import type { ComparisonData } from '../data/types'
import SectionHeading from './SectionHeading'

export default function ConclusionSection({ data }: { data: ComparisonData }) {
  const real = realMetricsForFindings(data.metrics)
  const completed = real.filter((item) => item.caseStatus === 'complete').length
  const validated = real.filter((item) => item.validationStatus === 'pass').length
  const categories = new Set(real.map((item) => item.category)).size
  return (
    <section className="page-section conclusion-section" id="conclusion">
      <SectionHeading
        index="05"
        kicker="证据边界与下一步"
        title="当前能得出什么，不能得出什么"
        description="结论只读取dataStatus为real的数据。模拟占位永远不会进入排名、推荐或统计推断。"
      />
      <div className="conclusion-hero">
        <div className="big-number">{validated}<small>/ {real.length}</small></div>
        <div><span className="eyebrow">VERIFIED REAL CASES</span><h3>真实MILP正式案例全部通过独立验证</h3><p>{completed}个案例完成，覆盖{categories}类场景。滚动机制能够响应紧急插单、紧急撤单与车辆故障；仓储非约束后，节点处理能力与可用运力成为主要瓶颈。</p></div>
      </div>
      <div className="conclusion-columns">
        <article><span>01</span><h3>真实发现</h3><ul><li>12个正式案例均可行并通过独立约束校验。</li><li>每6小时更新与事件额外重调度可以共存。</li><li>所有未撤销货物最终送达，服务不足通过软惩罚衡量。</li><li>最终滚动模型均为最优状态，但日初模型曾达到时间上限，因此不宣称整个动态过程全局最优。</li></ul></article>
        <article><span>02</span><h3>局限</h3><ul><li>合成数据且正式案例仅12个。</li><li>单车型、等效吨连续货量，未考虑重量—体积双容量。</li><li>仓储容量不约束，路径由固定候选集产生。</li><li>日初求解达到时间上限。</li><li>是聚合货量计划，不是逐票、逐车和仓内微观仿真。</li></ul></article>
        <article><span>03</span><h3>未来工作</h3><ul><li>以真实数据校准需求、成本与处理能力。</li><li>扩展多车型、重量—体积双容量与随机/鲁棒优化。</li><li>实现Benders、列生成和Branch-and-Price的大规模求解。</li><li>从表格Q学习升级到多智能体、离线或鲁棒DRL。</li><li>接入数字孪生仿真，验证微观执行可行性。</li></ul></article>
      </div>
      <div className="final-boundary"><b>重要说明</b><p>Benders＋列生成和分层表格强化学习的数字及动画目前都是组件占位，不构成性能证据；只有接入各自真实JSON并通过同口径验证后，才能进行方法排名和差异结论。</p></div>
    </section>
  )
}
