import type { AnimationData, AnimationSnapshot, MethodId } from '../data/types'

interface NetworkPanelProps {
  methodId: MethodId
  label: string
  dataStatus: 'real' | 'mock'
  data: AnimationData
  snapshot: AnimationSnapshot
  slot: number
}

const positions: Record<string, [number, number]> = {
  A: [58, 78], B: [190, 38], C: [200, 142], D: [340, 78],
  E: [350, 200], F: [510, 144], G: [648, 72], H: [670, 198],
}
const productColors = { urgent: '#e2574c', standard: '#3a79b8', economy: '#53a47c' }

function pointOnSegment(from: [number, number], to: [number, number], progress: number) {
  return [from[0] + (to[0] - from[0]) * progress, from[1] + (to[1] - from[1]) * progress]
}

export default function NetworkPanel({ methodId, label, dataStatus, data, snapshot, slot }: NetworkPanelProps) {
  const mockScale = dataStatus === 'mock' ? (methodId === 'benders-cg' ? 0.92 : methodId === 'tabular-hrl' ? 1.08 : 1) : 1
  const activeFlows = snapshot.cargoFlows.filter((flow) => flow.departureSlot <= slot && flow.arrivalSlot > slot)
  const activeSegments = snapshot.missions.flatMap((mission) => mission.segments
    .filter((segment) => segment.departureSlot <= slot && segment.arrivalSlot > slot)
    .map((segment) => ({ ...segment, mission })))

  return (
    <article className={`network-panel ${dataStatus === 'mock' ? 'is-mock' : ''}`}>
      <div className="network-panel-head"><div><span>{dataStatus === 'real' ? 'REAL REPLAY' : 'MOCK PREVIEW'}</span><h3>{label}</h3></div><b className={dataStatus}>{dataStatus === 'real' ? '真实方案' : '模拟占位'}</b></div>
      <div className="network-canvas">
        {dataStatus === 'mock' && <div className="animation-watermark">模拟占位<br /><small>不代表实验结果</small></div>}
        <svg viewBox="0 0 730 250" role="img" aria-label={`${label}在第${slot * data.slotHours}小时的网络决策图`}>
          {data.topology.edges.map((edge) => {
            const from = positions[edge.origin]
            const to = positions[edge.destination]
            return <line className="network-edge" key={`${edge.origin}-${edge.destination}`} x1={from[0]} y1={from[1]} x2={to[0]} y2={to[1]} />
          })}
          {activeFlows.map((flow, index) => {
            const from = positions[flow.origin]
            const to = positions[flow.destination]
            if (!from || !to) return null
            const offset = ((index % 5) - 2) * 1.4
            return <line key={`${flow.origin}-${flow.destination}-${flow.product}-${index}`} x1={from[0]} y1={from[1] + offset} x2={to[0]} y2={to[1] + offset} stroke={productColors[flow.product]} strokeWidth={Math.min(11, 1.2 + flow.tons * mockScale * .32)} strokeLinecap="round" opacity=".72"><title>{flow.origin}→{flow.destination} · {flow.product} · {(flow.tons * mockScale).toFixed(2)}吨</title></line>
          })}
          {activeSegments.map(({ mission, ...segment }, index) => {
            const from = positions[segment.origin]
            const to = positions[segment.destination]
            if (!from || !to) return null
            const progress = (slot - segment.departureSlot + .45) / Math.max(1, segment.arrivalSlot - segment.departureSlot)
            const [x, y] = pointOnSegment(from, to, Math.max(.08, Math.min(.92, progress)))
            return <g key={`${mission.missionId}-${index}`}><circle cx={x} cy={y} r={mission.vehicleSource === 'own' ? 5.5 : 6.5} fill={mission.vehicleSource === 'own' ? '#2774ae' : '#ea7a30'} stroke="white" strokeWidth="2"><title>{mission.vehicleSource === 'own' ? '自有车' : '外请车'} · {mission.vehicleCount}辆 · {segment.origin}→{segment.destination}</title></circle></g>
          })}
          {data.topology.nodes.map((nodeId) => {
            const [x, y] = positions[nodeId]
            const node = snapshot.nodes.find((item) => item.nodeId === nodeId)
            const state = node?.timeline.find((item) => item.slot === slot)
            const utilization = Math.max(0, Math.min(1, state?.handlingUtilization ?? 0))
            const inventory = state?.inventoryTons ?? 0
            return (
              <g className="network-node" key={nodeId} transform={`translate(${x} ${y})`}>
                <circle className="node-base" r="17" />
                <circle className="node-util" r="22" pathLength="100" strokeDasharray={`${utilization * 100} 100`} transform="rotate(-90)" />
                <text className="node-label" y="5">{nodeId}</text>
                <text className="vehicle-count" y="37">自有 {Math.max(0, state?.ownVehicles ?? 0).toFixed(0)}</text>
                {inventory > .01 && <g transform="translate(18 -25)"><circle className="inventory-bubble" r={Math.min(13, 6 + Math.sqrt(inventory))} /><text className="inventory-label" y="3">{inventory.toFixed(0)}</text></g>}
                <title>{nodeId}：处理利用率{(utilization * 100).toFixed(0)}%，留仓{inventory.toFixed(2)}吨，自有车{Math.max(0, state?.ownVehicles ?? 0).toFixed(0)}辆</title>
              </g>
            )
          })}
        </svg>
        <div className="network-legend"><span><i className="own-dot" />自有车</span><span><i className="external-dot" />外请车</span><span><i className="urgent-line" />加急</span><span><i className="standard-line" />普通</span><span><i className="economy-line" />经济</span></div>
      </div>
      <div className="network-stats"><span>在途班车 <b>{activeSegments.length}</b></span><span>活跃货流 <b>{activeFlows.reduce((sum, flow) => sum + flow.tons * mockScale, 0).toFixed(1)}t</b></span><span>当前方案 <b>{snapshot.decisionType === 'baseline' ? '日初' : snapshot.decisionType === 'event' ? '事件' : '滚动'}</b></span></div>
    </article>
  )
}
