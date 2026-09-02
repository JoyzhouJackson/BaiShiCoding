import { lazy, Suspense, useState } from 'react'
import { methodContents } from '../data/content'
import type { ComparisonData, MethodContent, MethodId } from '../data/types'
import ExplainableText from './ExplainableText'
import FlowDiagram from './FlowDiagram'
import MilpBusinessFlow from './MilpBusinessFlow'
import SectionHeading from './SectionHeading'

const MilpResultsDashboard = lazy(() => import('./MilpResultsDashboard'))
const BendersResultsSummary = lazy(() => import('./BendersResultsSummary'))
const QlearningResultsSummary = lazy(() => import('./QlearningResultsSummary'))

interface MethodExplorerProps {
  comparison: ComparisonData
  onExplain: (title: string, content: string) => void
}

type ExplanationLevel = 'business' | 'algorithm' | 'math'
const levelLabels: Record<ExplanationLevel, string> = { business: '业务解释', algorithm: '算法解释', math: '数学细节' }

function StatusPill({ status, text }: { status: 'real' | 'mock' | 'planned'; text: string }) {
  return <span className={`status-pill ${status}`}>{status === 'real' ? '●' : '◌'} {text}</span>
}

function DecisionMap({ method }: { method: MethodContent }) {
  return (
    <div className="decision-map">
      {method.decisionMappings.map((mapping, index) => (
        <article key={mapping.decision} className="decision-map-row">
          <div className="decision-name"><span>决策 {String(index + 1).padStart(2, '0')}</span><h4>{mapping.decision}</h4><p>{mapping.businessMeaning}</p></div>
          <div className="variable-block"><span className="mapping-label">对应变量 / 动作</span>{mapping.variables.map((variable) => <div key={variable.symbol}><code>{variable.symbol}</code><p>{variable.meaning}</p></div>)}</div>
          <div className="constraint-block"><span className="mapping-label">直接对应的核心约束</span>{mapping.constraints.map((constraint) => <div key={constraint.name}><b>{constraint.name}</b><code>{constraint.formula}</code><p>{constraint.meaning}</p></div>)}</div>
        </article>
      ))}
    </div>
  )
}

function ObjectiveMap({ method }: { method: MethodContent }) {
  return (
    <div className="objective-map">
      <div className="objective-formula"><span>OBJECTIVE</span><code>{method.objective.formula}</code><p>{method.objective.note}</p></div>
      <div className="objective-terms">
        {method.objective.terms.map((term) => (
          <article key={term.symbol}><div><code>{term.symbol}</code><h4>{term.label}</h4></div><code className="term-formula">{term.formula}</code><p>{term.meaning}</p><small>关联决策：{term.linkedDecisions.join('、')}</small></article>
        ))}
      </div>
    </div>
  )
}

export default function MethodExplorer({ comparison, onExplain }: MethodExplorerProps) {
  const [selectedId, setSelectedId] = useState<MethodId>('milp')
  const [level, setLevel] = useState<ExplanationLevel>('business')
  const method = methodContents.find((item) => item.id === selectedId)!

  return (
    <section className="page-section methods-section" id="methods">
      <SectionHeading index="02" kicker="三种解决方案" title="同一问题，三种解决方案" description="MILP联合决策、Benders分解＋列生成和Q-learning—LP两层混合方法均已完成同一批12例测试。" />
      <div className="method-tabs" role="tablist" aria-label="求解方法">
        {methodContents.map((item, index) => (
          <button key={item.id} role="tab" aria-selected={item.id === selectedId} className={item.id === selectedId ? 'active' : ''} onClick={() => setSelectedId(item.id)}>
            <span>0{index + 1}</span>{item.label}
          </button>
        ))}
      </div>
      <article className="method-panel" key={method.id}>
        <div className="method-intro">
          <div><StatusPill status={method.dataStatus} text={method.statusText} /><h3>{method.label}</h3><p className="method-tagline"><ExplainableText text={method.tagline} onExplain={onExplain} /></p></div>
          <div className="why-box"><span>WHY THIS METHOD</span><p><ExplainableText text={method.why} onExplain={onExplain} /></p></div>
        </div>

        <div className="subsection-title numbered"><span><i>01</i> 做哪些决策：变量与核心约束对应表</span><small>从业务决策一路追溯到数学表达</small></div>
        <DecisionMap method={method} />
        <div className="subsection-title numbered"><span><i>02</i> 目标函数与每一项成本的含义</span><small>每项成本标明公式和关联决策</small></div>
        <ObjectiveMap method={method} />
        <div className="subsection-title numbered"><span><i>03</i> 完整技术路线</span><small>从当前业务状态到方案发布</small></div>
        {method.id === 'milp' ? <MilpBusinessFlow onExplain={onExplain} /> : <FlowDiagram method={method} onExplain={onExplain} />}

        <div className="subsection-title numbered"><span><i>04</i> 参数、停止条件与解释</span><small>支持业务、算法、数学三级阅读</small></div>
        <div className="method-detail-grid">
          <div className="explanation-card">
            <div className="level-tabs" role="tablist" aria-label="解释深度">
              {(Object.keys(levelLabels) as ExplanationLevel[]).map((item) => <button key={item} role="tab" aria-selected={level === item} className={level === item ? 'active' : ''} onClick={() => setLevel(item)}>{levelLabels[item]}</button>)}
            </div>
            <div className="level-copy" key={`${method.id}-${level}`}><ul>{method.explanations[level].map((item) => <li key={item}><ExplainableText text={item} onExplain={onExplain} /></li>)}</ul></div>
          </div>
          <div className="settings-card"><h4>参数与停止条件</h4><dl>{method.settings.map((item) => <div key={item.label}><dt>{item.label}</dt><dd>{item.value}</dd></div>)}</dl></div>
        </div>

        <div className="subsection-title numbered"><span><i>05</i> 结果、正确性与改进</span><small>验证结论、适用范围和下一步方案</small></div>
        {method.id === 'milp' && <Suspense fallback={<div className="chart-loading">正在加载MILP结果…</div>}><MilpResultsDashboard data={comparison} /></Suspense>}
        {method.id === 'benders-cg' && <Suspense fallback={<div className="chart-loading">正在加载Benders结果…</div>}><BendersResultsSummary data={comparison} /></Suspense>}
        {method.id === 'tabular-hrl' && <Suspense fallback={<div className="chart-loading">正在加载Q-learning结果…</div>}><QlearningResultsSummary data={comparison} /></Suspense>}

        <div className="evidence-grid">
          <div className="verification-card"><span className="eyebrow">VERIFICATION</span><h4>正确性与验证</h4><ul>{method.verification.map((item) => <li key={item}>{item}</li>)}</ul></div>
          <div className="strength-card"><span className="eyebrow">STRENGTHS</span><h4>优势与适用范围</h4><ul>{method.advantages.map((item) => <li key={item}>{item}</li>)}</ul></div>
          <div className="improvement-card"><span className="eyebrow">LIMITS & NEXT</span><h4>缺点与改进方案</h4><ul>{method.limitations.map((item) => <li key={item}>{item}</li>)}</ul></div>
        </div>
      </article>
    </section>
  )
}
