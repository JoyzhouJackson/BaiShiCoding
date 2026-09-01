import { useEffect, useState } from 'react'
import { globalParameters, structuralRules } from '../data/content'
import { loadCaseDetail } from '../data/api'
import type { CaseDetail, CaseSummary, FoundationData } from '../data/types'
import SectionHeading from './SectionHeading'
import ExplainableText from './ExplainableText'

interface FoundationSectionProps {
  foundation: FoundationData
  cases: CaseSummary[]
  selectedCaseId: string
  onSelectCase: (caseId: string) => void
  onExplain: (title: string, content: string) => void
}

const productLabels: Record<string, string> = { urgent: '加急', standard: '普通', economy: '经济' }

function ExpandableCard({ icon, title, summary, children }: { icon: string; title: string; summary: string; children: React.ReactNode }) {
  const [open, setOpen] = useState(false)
  return (
    <article className={`foundation-card ${open ? 'is-open' : ''}`}>
      <div className="card-icon">{icon}</div>
      <span className="eyebrow">COMMON FOUNDATION</span>
      <h3>{title}</h3>
      <p className="card-summary">{summary}</p>
      <button className="text-button" type="button" onClick={() => setOpen((value) => !value)} aria-expanded={open}>
        {open ? '收起完整信息 ↑' : '展开完整信息 ↓'}
      </button>
      <div className="expand-content" hidden={!open}>{children}</div>
    </article>
  )
}

function FactList({ rows, onExplain }: { rows: string[][]; onExplain: (title: string, content: string) => void }) {
  return (
    <dl className="fact-list">
      {rows.map(([label, value]) => <div key={label}><dt><ExplainableText text={label} onExplain={onExplain} /></dt><dd><ExplainableText text={value} onExplain={onExplain} /></dd></div>)}
    </dl>
  )
}

export default function FoundationSection({ foundation, cases, selectedCaseId, onSelectCase, onExplain }: FoundationSectionProps) {
  const [detail, setDetail] = useState<CaseDetail | null>(null)
  const [detailError, setDetailError] = useState('')
  const selected = cases.find((item) => item.caseId === selectedCaseId) ?? cases[0]

  useEffect(() => {
    let active = true
    setDetail(null)
    setDetailError('')
    loadCaseDetail(selected.caseId)
      .then((value) => { if (active) setDetail(value) })
      .catch((error: Error) => { if (active) setDetailError(error.message) })
    return () => { active = false }
  }, [selected.caseId])

  const time = foundation.time
  const vehicle = foundation.vehicle
  const costs = foundation.cost
  return (
    <section className="page-section foundation-section" id="foundation">
      <SectionHeading
        index="01"
        kicker="统一问题边界"
        title="先固定共同世界，再比较求解方法"
        description="以下业务结构、全局假设和测试实例对三种方法完全一致。切换方法不会改变它们，从而保证比较口径统一。"
      />
      <div className="foundation-grid">
        <ExpandableCard icon="◎" title="固定模型结构" summary="业务规则、决策边界与必须满足的物理约束。">
          <FactList rows={structuralRules} onExplain={onExplain} />
        </ExpandableCard>
        <ExpandableCard icon="⌁" title="全局固定参数" summary="时间、产品、服务目标、中转与滚动机制的共同假设。">
          <FactList rows={globalParameters} onExplain={onExplain} />
          <div className="parameter-strip">
            <span><b>{Number(time.planning_slots) * Number(time.slot_hours)}h</b>规划窗口</span>
            <span><b>{Number(time.observation_slots) * Number(time.slot_hours)}h</b>观察期</span>
            <span><b>{vehicle.capacity_equivalent_tons as number}t</b>单车容量</span>
          </div>
        </ExpandableCard>
        <ExpandableCard icon="▦" title="实例与实验参数" summary="网络物理参数、成本、需求生成规则与12个正式案例。">
          <label className="field-label" htmlFor="foundation-case">当前案例</label>
          <select id="foundation-case" value={selected.caseId} onChange={(event) => onSelectCase(event.target.value)}>
            {cases.map((item) => <option key={item.caseId} value={item.caseId}>{item.caseId} · {item.categoryLabel}</option>)}
          </select>
          <div className="case-stats">
            <span><b>{selected.eventHour == null ? '—' : `${selected.eventHour}h`}</b>异常时刻</span>
            <span><b>{selected.forecastTotal.toFixed(1)}</b>预测吨位</span>
            <span><b>{selected.actualTotal.toFixed(1)}</b>实际吨位</span>
            <span><b>{(selected.forecastErrorRate * 100).toFixed(1)}%</b>预测偏差</span>
          </div>
          <FactList onExplain={onExplain} rows={[
            ['网络规模', `${foundation.network.nodeCount}个节点、${foundation.network.undirectedEdgeCount}条双向物理连接`],
            ['数据集合', `${foundation.datasets.frozenMasterCases}个冻结母集；当前${foundation.datasets.activeTestCases}个正式案例，每类${foundation.datasets.activePerCategory}个`],
            ['需求扰动', '批次总量±20%，OD—产品占比再做±10%扰动并重新归一'],
            ['仓储政策', foundation.storagePolicy],
            ['成本口径', `装卸${costs.handling_per_ton_operation}/吨·次；中转${costs.transfer_extra_per_ton}/吨；库存${costs.inventory_holding_per_ton_slot}/吨·时段`],
          ]} />
          <button className="inline-help" type="button" onClick={() => onExplain('预测量与实际量', '0、6、12小时分别给出该批预测总量。实际总量围绕各批预测量±20%波动，再扰动OD—产品构成。实际量在固定滚动点核实，因此预测误差本身不额外触发事件调度。')}>为什么预测偏差不算异常？</button>
          {detailError && <p className="error-note">{detailError}</p>}
          {!detail && !detailError && <p className="loading-note">正在按需读取案例明细…</p>}
          {detail && (
            <div className="detail-tables">
              <h4>节点真实参数</h4>
              <div className="table-scroll"><table><thead><tr><th>节点</th><th>初始自有车</th><th>外请上限/期</th><th>处理能力范围</th></tr></thead><tbody>
                {detail.nodes.map((node) => <tr key={node.id}><td>{node.id}</td><td>{node.initial_own_vehicles}</td><td>{Math.max(...node.external_vehicle_limit)}</td><td>{Math.min(...node.handling_capacity).toFixed(1)}–{Math.max(...node.handling_capacity).toFixed(1)}</td></tr>)}
              </tbody></table></div>
              <h4>需求构成</h4>
              <div className="product-bars">
                {Object.entries(selected.products).map(([key, values]) => <div key={key}><span>{productLabels[key]}</span><i style={{ width: `${Math.min(100, values.actual / selected.actualTotal * 260)}%` }} /><b>{values.actual.toFixed(1)}t</b></div>)}
              </div>
              <p className="micro-note">共 {detail.demands.length} 个 OD—产品—批次需求；完整明细已保留在按案例分片中。</p>
            </div>
          )}
        </ExpandableCard>
      </div>
    </section>
  )
}
