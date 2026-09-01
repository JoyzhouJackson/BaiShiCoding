import type { MethodContent } from '../data/types'

interface FlowDiagramProps {
  method: MethodContent
  onExplain: (title: string, content: string) => void
}

const kindLabels = { input: '输入', decision: '决策', check: '判断', output: '输出' }

export default function FlowDiagram({ method, onExplain }: FlowDiagramProps) {
  const byId = new Map(method.flowNodes.map((node) => [node.id, node]))
  return (
    <div className="flow-wrap">
      <svg className="flow-diagram" viewBox="0 0 960 410" role="img" aria-label={`${method.label}业务技术路线图`}>
        <defs>
          <marker id={`arrow-${method.id}`} viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
            <path d="M 0 0 L 10 5 L 0 10 z" />
          </marker>
        </defs>
        {method.flowEdges.map((edge, index) => {
          const from = byId.get(edge.from)
          const to = byId.get(edge.to)
          if (!from || !to) return null
          const x1 = from.x + 150
          const y1 = from.y + 34
          const x2 = to.x
          const y2 = to.y + 34
          const curve = Math.abs(y2 - y1) > 30
          const path = curve
            ? `M ${x1} ${y1} C ${x1 + 38} ${y1}, ${x2 - 38} ${y2}, ${x2} ${y2}`
            : `M ${x1} ${y1} L ${x2} ${y2}`
          return (
            <g className="flow-edge" key={`${edge.from}-${edge.to}-${index}`}>
              <path d={path} markerEnd={`url(#arrow-${method.id})`} />
              {edge.label && <text x={(x1 + x2) / 2} y={(y1 + y2) / 2 - 7}>{edge.label}</text>}
            </g>
          )
        })}
        {method.flowNodes.map((node) => (
          <g
            className={`flow-node ${node.kind ?? 'decision'}`}
            key={node.id}
            transform={`translate(${node.x} ${node.y})`}
            role="button"
            tabIndex={0}
            aria-label={`${node.title}：${node.detail}`}
            onClick={() => onExplain(node.title, node.detail)}
            onKeyDown={(event) => {
              if (event.key === 'Enter' || event.key === ' ') onExplain(node.title, node.detail)
            }}
          >
            <title>{node.detail}</title>
            <rect width="150" height="68" rx="12" />
            <text className="node-kind" x="12" y="16">{kindLabels[node.kind ?? 'decision']}</text>
            <text className="node-title" x="12" y="39">{node.title}</text>
            <text className="node-subtitle" x="12" y="57">{node.subtitle}</text>
          </g>
        ))}
      </svg>
      <div className="flow-hint">悬停查看摘要 · 点击节点打开详细解释 · 键盘可聚焦</div>
    </div>
  )
}
