import { useEffect, useMemo, useState } from 'react'
import { loadAnimation, loadAnimationUrl } from '../data/api'
import type { AnimationData, AnimationManifest, CaseSummary, DataStatus, MethodId } from '../data/types'
import NetworkPanel from './NetworkPanel'
import SectionHeading from './SectionHeading'

interface SimulationSectionProps {
  cases: CaseSummary[]
  selectedCaseId: string
  onSelectCase: (caseId: string) => void
  manifest: AnimationManifest
}

const eventLabels: Record<string, string> = { urgent_insert: '紧急插单', urgent_cancel: '紧急撤单', vehicle_breakdown: '车辆故障', none: '无异常' }

export default function SimulationSection({ cases, selectedCaseId, onSelectCase, manifest }: SimulationSectionProps) {
  const [methodData, setMethodData] = useState<Partial<Record<MethodId, AnimationData>>>({})
  const [error, setError] = useState('')
  const [slot, setSlot] = useState(0)
  const [playing, setPlaying] = useState(false)
  const [speed, setSpeed] = useState(1)

  useEffect(() => {
    let active = true
    setPlaying(false)
    setSlot(0)
    setMethodData({})
    setError('')
    const entries = manifest.methods?.map((method) => ({
      methodId: method.methodId,
      url: method.cases.find((item) => item.caseId === selectedCaseId)?.url,
    })).filter((item): item is { methodId: MethodId; url: string } => Boolean(item.url))
    const loaders = entries?.length
      ? entries.map((item) => loadAnimationUrl(item.url).then((value) => [item.methodId, value] as const))
      : [loadAnimation(selectedCaseId).then((value) => ['milp', value] as const)]
    Promise.all(loaders).then((values) => { if (active) setMethodData(Object.fromEntries(values)) }).catch((reason: Error) => { if (active) setError(reason.message) })
    return () => { active = false }
  }, [manifest.methods, selectedCaseId])

  const data = methodData.milp ?? Object.values(methodData)[0] ?? null

  useEffect(() => {
    if (!playing || !data) return
    const timer = window.setInterval(() => setSlot((current) => Math.min(data.observationSlots, current + 1)), 950 / speed)
    return () => window.clearInterval(timer)
  }, [data, playing, speed])

  useEffect(() => {
    if (data && slot >= data.observationSlots) setPlaying(false)
  }, [data, slot])

  const snapshot = useMemo(() => {
    if (!data) return null
    return [...data.snapshots].reverse().find((item) => item.decisionSlot <= slot) ?? data.snapshots[0]
  }, [data, slot])
  const methodStatus = (methodId: MethodId): DataStatus => manifest.methods?.find((item) => item.methodId === methodId)?.dataStatus ?? (methodId === 'milp' ? 'real' : 'mock')
  const panel = (methodId: MethodId, label: string) => {
    const panelData = methodData[methodId] ?? data
    if (!panelData) return null
    const panelSnapshot = [...panelData.snapshots].reverse().find((item) => item.decisionSlot <= slot) ?? panelData.snapshots[0]
    const status = methodStatus(methodId)
    return <NetworkPanel methodId={methodId} label={label} dataStatus={status === 'real' ? 'real' : 'mock'} data={panelData} snapshot={panelSnapshot} slot={slot} />
  }
  const eventSlot = Number(data?.event.slot ?? -1)
  const currentStep = data?.rollingSteps.find((step) => step.slot === slot)
  const currentNodes = snapshot?.nodes.map((node) => node.timeline.find((item) => item.slot === slot)).filter(Boolean) ?? []
  const totalInventory = currentNodes.reduce((sum, node) => sum + (node?.inventoryTons ?? 0), 0)
  const maxUtilNode = snapshot?.nodes.map((node) => ({ nodeId: node.nodeId, state: node.timeline.find((item) => item.slot === slot) })).sort((a, b) => (b.state?.handlingUtilization ?? 0) - (a.state?.handlingUtilization ?? 0))[0]

  return (
    <section className="page-section simulation-section" id="simulation">
      <SectionHeading
        index="04"
        kicker="同步决策回放"
        title="同一案例、同一时钟、三联网络动画"
        description="MILP与Benders面板分别还原各自保存的真实计划快照；强化学习尚未完成实验，继续使用带水印的组件占位。"
      />
      <div className="simulation-toolbar">
        <label>回放案例<select value={selectedCaseId} onChange={(event) => onSelectCase(event.target.value)}>{cases.map((item) => <option key={item.caseId} value={item.caseId}>{item.caseId} · {item.categoryLabel}{item.eventHour == null ? '' : ` @ ${item.eventHour}h`}</option>)}</select></label>
        <div className="play-controls">
          <button type="button" onClick={() => setSlot((value) => Math.max(0, value - 1))} aria-label="后退一步">‹</button>
          <button className="play-button" type="button" onClick={() => setPlaying((value) => !value)}>{playing ? '暂停' : '播放'}</button>
          <button type="button" onClick={() => setSlot((value) => Math.min(data?.observationSlots ?? 24, value + 1))} aria-label="前进一步">›</button>
        </div>
        <div className="speed-controls" aria-label="播放速度">{[.5, 1, 2].map((value) => <button key={value} className={speed === value ? 'active' : ''} type="button" onClick={() => setSpeed(value)}>{value}×</button>)}</div>
      </div>
      {error && <div className="error-panel">动画数据读取失败：{error}</div>}
      {!data && !error && <div className="animation-loading">正在按需加载动画分片…</div>}
      {data && snapshot && (
        <>
          <div className="timeline-wrap">
            <div className="time-display"><b>{slot * data.slotHours}</b><span>小时</span></div>
            <div className="timeline-control">
              <input type="range" min="0" max={data.observationSlots} step="1" value={slot} onChange={(event) => { setPlaying(false); setSlot(Number(event.target.value)) }} aria-label="共同动画时间轴" />
              <div className="timeline-markers">
                {Array.from({ length: Math.floor(data.observationSlots / 2) + 1 }, (_, index) => index * 2).map((value) => <span key={value} className={value === eventSlot ? 'event' : 'rolling'} style={{ left: `${value / data.observationSlots * 100}%` }}><i />{value === eventSlot ? `${value * data.slotHours}h 异常` : value % 4 === 0 ? `${value * data.slotHours}h` : ''}</span>)}
                {eventSlot >= 0 && eventSlot % 2 !== 0 && <span className="event" style={{ left: `${eventSlot / data.observationSlots * 100}%` }}><i />{eventSlot * data.slotHours}h 异常</span>}
              </div>
            </div>
          </div>
          <div className="network-triptych">
            {panel('milp', 'MILP联合决策')}
            {panel('benders-cg', 'Benders＋列生成')}
            {panel('tabular-hrl', '分层表格强化学习')}
          </div>
          <aside className="moment-explanation">
            <div><span className="eyebrow">T = {slot * data.slotHours} HOURS</span><h3>{currentStep ? (currentStep.decisionType === 'event' ? '异常触发重调度' : '固定滚动更新') : '执行当前已发布方案'}</h3></div>
            <dl>
              <div><dt>当前事件</dt><dd>{slot === eventSlot ? eventLabels[String(data.event.type)] ?? String(data.event.type) : '无新事件'}</dd></div>
              <div><dt>计划快照</dt><dd>{snapshot.snapshotId}</dd></div>
              <div><dt>节点积压</dt><dd>{totalInventory.toFixed(1)} 等效吨</dd></div>
              <div><dt>最高处理利用率</dt><dd>{maxUtilNode?.nodeId ?? '—'} · {((maxUtilNode?.state?.handlingUtilization ?? 0) * 100).toFixed(0)}%</dd></div>
              <div><dt>本次方案变化</dt><dd>{currentStep ? `变更成本 ${currentStep.changeCost.toFixed(1)}` : '沿用上一版方案'}</dd></div>
            </dl>
            <p>已执行班车和货物流保持锁定；当前快照只重排决策时点以后的班车开行、车辆来源与货物路线。</p>
          </aside>
        </>
      )}
    </section>
  )
}
