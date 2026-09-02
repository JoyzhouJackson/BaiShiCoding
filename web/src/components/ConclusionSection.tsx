import { realMetricsForFindings } from '../data/chartUtils'
import type { ComparisonData } from '../data/types'
import SectionHeading from './SectionHeading'

export default function ConclusionSection({ data }: { data: ComparisonData }) {
  const real = realMetricsForFindings(data.metrics)
  const paired = data.pairedAnalysis
  const validated = real.filter((item) => item.validationStatus === 'pass').length
  const categories = new Set(real.map((item) => item.category)).size
  const pairedCases = paired?.pairedCases ?? 0

  return (
    <section className="page-section conclusion-section" id="conclusion">
      <SectionHeading
        index="05"
        kicker="证据边界与下一步"
        title="当前能得出什么，不能得出什么"
        description="结论只读取dataStatus为real的数据。目前MILP和Benders＋列生成是真实结果；强化学习占位不会进入排名或推断。"
      />
      <div className="conclusion-hero">
        <div className="big-number">{pairedCases}<small> 对</small></div>
        <div><span className="eyebrow">PAIRED VERIFIED CASES</span><h3>MILP与Benders均稳定完成，但小规模下MILP更合适</h3><p>{validated}份方法—案例结果全部通过独立校验，覆盖{categories}类场景。Benders证明了分解路线可行，但本组案例的平均成本高7.03%、平均求解时间高45.8%，暂未体现规模分解优势。</p></div>
      </div>
      <div className="conclusion-columns">
        <article><span>01</span><h3>真实发现</h3><ul><li>两种方法在相同12个正式案例上均可行并通过校验。</li><li>MILP在12/12个案例中取得更低总成本。</li><li>Benders主要差距来自更高的方案变更成本和运输成本。</li><li>紧急插单场景差距最大，分类平均成本高10.60%。</li><li>事件额外重调度与每6小时固定滚动可以共存。</li></ul></article>
        <article><span>02</span><h3>必须保留的边界</h3><ul><li>正式案例仅12个，每类3个，不做显著性推断。</li><li>Benders只有69/99个阶段达到目标Gap。</li><li>“恢复最优”只针对固定班车后的连续货物流。</li><li>合成数据、单车型、等效吨连续货量。</li><li>当前使用相同的有限候选行程全集，不是无限路径空间。</li></ul></article>
        <article><span>03</span><h3>下一步</h3><ul><li>强化Benders割并处理重复割停滞。</li><li>重点降低滚动过程中不必要的班车和货物改道。</li><li>在更大节点、需求和路径规模下检验分解优势。</li><li>完成强化学习真实训练后接入第三组同口径结果。</li><li>再扩展多车型和重量—体积双容量。</li></ul></article>
      </div>
      <div className="final-boundary"><b>最终判断</b><p>当前推荐把联合MILP作为12个小规模案例的主方案，把Benders＋列生成作为结构化分解对照组。它已经证明“能稳定产生业务可行方案”，但尚未证明“更快、更优或所有阶段达到5% Gap”。分层表格强化学习仍为模拟占位，不构成性能证据。</p></div>
    </section>
  )
}
