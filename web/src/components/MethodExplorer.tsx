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
      <SectionHeading index="02" kicker="三条真实求解路线" title="同一问题，三种不同的决策机制" description="MILP负责联合优化，Benders–列生成负责结构化分解，两层Q-learning负责快速规则选择；三种方法均已完成同一批12例测试。" />
      <div className="method-tabs" role="tablist" aria-label="求解方法">
        {methodContents.map((item, index) => (
          <button key={item.id} role="tab" aria-selected={item.id === selectedId} className={item.id === selectedId ? 'active' : ''} onClick={() => setSelectedId(item.id)}>
            <span>0{index + 1}</span>{item.label}<small>{item.dataStatus === 'real' ? 'REAL' : 'PLANNED'}</small>
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
        <div className="subsection-title numbered"><span><i>03</i> 完整技术路线</span><small>{method.id === 'milp' ? '按已保存的Gurobi业务流程图重构' : method.id === 'benders-cg' ? '按真实分解求解过程展示' : '按真实训练与贪心测试流程展示'}</small></div>
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

        <div className="subsection-title numbered"><span><i>05</i> 验证与测试结果</span><small>真实结果与待实验方法严格分开</small></div>
        {method.id === 'milp' && <Suspense fallback={<div className="chart-loading">正在加载真实MILP结果组件…</div>}><MilpResultsDashboard data={comparison} /></Suspense>}
        {method.id === 'benders-cg' && <Suspense fallback={<div className="chart-loading">正在加载真实Benders结果组件…</div>}><BendersResultsSummary data={comparison} /></Suspense>}
        {method.id === 'tabular-hrl' && <Suspense fallback={<div className="chart-loading">正在加载真实Q-learning结果组件…</div>}><QlearningResultsSummary data={comparison} /></Suspense>}

        <div className="evidence-grid">
          <div><span className="eyebrow">VERIFICATION</span><h4>正确性与验证</h4><ul>{method.verification.map((item) => <li key={item}>{item}</li>)}</ul></div>
          <div><span className="eyebrow">STRENGTHS</span><h4>优势与适用范围</h4><ul>{method.advantages.map((item) => <li key={item}>{item}</li>)}</ul></div>
          <div><span className="eyebrow">LIMITS</span><h4>缺点与边界</h4><ul>{method.limitations.map((item) => <li key={item}>{item}</li>)}</ul></div>
        </div>
      </article>
    </section>
  )
}
