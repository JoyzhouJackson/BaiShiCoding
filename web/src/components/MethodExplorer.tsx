import { useState } from 'react'
import { methodContents } from '../data/content'
import type { MethodId } from '../data/types'
import FlowDiagram from './FlowDiagram'
import SectionHeading from './SectionHeading'
import ExplainableText from './ExplainableText'

interface MethodExplorerProps {
  onExplain: (title: string, content: string) => void
}

type ExplanationLevel = 'business' | 'algorithm' | 'math'
const levelLabels: Record<ExplanationLevel, string> = { business: '业务解释', algorithm: '算法解释', math: '数学细节' }

function StatusPill({ status, text }: { status: 'real' | 'mock' | 'planned'; text: string }) {
  return <span className={`status-pill ${status}`}>{status === 'real' ? '●' : '◌'} {text}</span>
}

export default function MethodExplorer({ onExplain }: MethodExplorerProps) {
  const [selectedId, setSelectedId] = useState<MethodId>('milp')
  const [level, setLevel] = useState<ExplanationLevel>('business')
  const method = methodContents.find((item) => item.id === selectedId)!

  return (
    <section className="page-section methods-section" id="methods">
      <SectionHeading
        index="02"
        kicker="三条求解路线"
        title="同一问题，三种不同的决策机制"
        description="MILP展示已实现模型与真实结果；另外两种方法如实标明设计完成但实验待运行，不用模拟数字替代方法证据。"
      />
      <div className="method-tabs" role="tablist" aria-label="求解方法">
        {methodContents.map((item, index) => (
          <button key={item.id} role="tab" aria-selected={item.id === selectedId} className={item.id === selectedId ? 'active' : ''} onClick={() => setSelectedId(item.id)}>
            <span>0{index + 1}</span>{item.label}<small>{item.dataStatus === 'real' ? 'REAL' : 'PLANNED'}</small>
          </button>
        ))}
      </div>
      <article className="method-panel" key={method.id}>
        <div className="method-intro">
          <div>
            <StatusPill status={method.dataStatus} text={method.statusText} />
            <h3>{method.label}</h3>
            <p className="method-tagline"><ExplainableText text={method.tagline} onExplain={onExplain} /></p>
          </div>
          <div className="why-box"><span>WHY THIS METHOD</span><p><ExplainableText text={method.why} onExplain={onExplain} /></p></div>
        </div>
        <div className="decision-grid">
          <div><h4>它决定什么</h4><ul className="check-list">{method.decides.map((item) => <li key={item}><ExplainableText text={item} onExplain={onExplain} /></li>)}</ul></div>
          <div><h4>它不决定什么</h4><ul className="minus-list">{method.notDecides.map((item) => <li key={item}><ExplainableText text={item} onExplain={onExplain} /></li>)}</ul></div>
        </div>
        <div className="subsection-title"><span>交互式技术路线</span><small>关键业务决策置于主流程，辅助说明按需展开</small></div>
        <FlowDiagram method={method} onExplain={onExplain} />
        <div className="method-detail-grid">
          <div className="explanation-card">
            <div className="level-tabs" role="tablist" aria-label="解释深度">
              {(Object.keys(levelLabels) as ExplanationLevel[]).map((item) => <button key={item} role="tab" aria-selected={level === item} className={level === item ? 'active' : ''} onClick={() => setLevel(item)}>{levelLabels[item]}</button>)}
            </div>
            <div className="level-copy" key={`${method.id}-${level}`}><ul>{method.explanations[level].map((item) => <li key={item}><ExplainableText text={item} onExplain={onExplain} /></li>)}</ul></div>
          </div>
          <div className="settings-card"><h4>参数与停止条件</h4><dl>{method.settings.map((item) => <div key={item.label}><dt>{item.label}</dt><dd>{item.value}</dd></div>)}</dl></div>
        </div>
        <div className="evidence-grid">
          <div><span className="eyebrow">VERIFICATION</span><h4>正确性与验证</h4><ul>{method.verification.map((item) => <li key={item}>{item}</li>)}</ul></div>
          <div><span className="eyebrow">STRENGTHS</span><h4>优势与适用范围</h4><ul>{method.advantages.map((item) => <li key={item}>{item}</li>)}</ul></div>
          <div><span className="eyebrow">LIMITS</span><h4>缺点与边界</h4><ul>{method.limitations.map((item) => <li key={item}>{item}</li>)}</ul></div>
        </div>
      </article>
    </section>
  )
}
