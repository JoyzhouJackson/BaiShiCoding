import { useEffect, useMemo, useRef, useState } from 'react'
import * as echarts from 'echarts/core'
import type { EChartsCoreOption } from 'echarts/core'
import { BarChart, HeatmapChart, ScatterChart } from 'echarts/charts'
import { DataZoomComponent, GridComponent, LegendComponent, MarkLineComponent, TitleComponent, TooltipComponent, VisualMapComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { loadAnimation } from '../data/api'
import type { AnimationData, ComparisonData } from '../data/types'

echarts.use([BarChart, ScatterChart, HeatmapChart, GridComponent, TooltipComponent, LegendComponent, DataZoomComponent, MarkLineComponent, VisualMapComponent, TitleComponent, CanvasRenderer])

interface ChartCanvasProps {
  option: EChartsCoreOption
  label: string
  height?: number
}

function ChartCanvas({ option, label, height = 430 }: ChartCanvasProps) {
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!ref.current) return
    const chart = echarts.init(ref.current)
    chart.setOption(option)
    const observer = new ResizeObserver(() => chart.resize())
    observer.observe(ref.current)
    return () => { observer.disconnect(); chart.dispose() }
  }, [option])
  return <div ref={ref} className="milp-result-chart" style={{ height }} role="img" aria-label={label} />
}

function compactCaseId(caseId: string) {
  return caseId.replace('test_', '').replace('urgent_insert', '插单').replace('urgent_cancel', '撤单').replace('vehicle_breakdown', '故障').replace('normal', '正常')
}

function formatDuration(seconds: number) {
  const minutes = Math.floor(seconds / 60)
  const remain = Math.round(seconds % 60)
  return `${minutes}分${remain}秒`
}

export default function MilpResultsDashboard({ data }: { data: ComparisonData }) {
  const [animation, setAnimation] = useState<AnimationData | null>(null)
  const [animationError, setAnimationError] = useState('')
  const real = useMemo(() => data.metrics.filter((item) => item.methodId === 'milp' && item.dataStatus === 'real'), [data.metrics])
  const summary = data.experimentSummary

  useEffect(() => {
    let active = true
    loadAnimation('test_urgent_insert_002')
      .then((value) => { if (active) setAnimation(value) })
      .catch((error: Error) => { if (active) setAnimationError(error.message) })
    return () => { active = false }
  }, [])

  const caseLabels = useMemo(() => real.map((row) => compactCaseId(row.caseId)), [real])
  const commonGrid = { left: 115, right: 34, top: 70, bottom: 58 }
  const costOption = useMemo(() => {
    const parts = [
      ['运输', 'transportCost', '#183a58'], ['装卸', 'handlingCost', '#2d6689'],
      ['留仓', 'inventoryCost', '#70a78f'], ['中转', 'transferCost', '#a1be8d'],
      ['延误', 'delayCost', '#e97935'], ['服务不达标', 'serviceShortfallCost', '#d95848'],
      ['方案变更', 'changeCost', '#8269a8'],
    ] as const
    return {
      animationDuration: 500,
      color: parts.map((item) => item[2]),
      grid: commonGrid,
      legend: { top: 8, type: 'scroll' },
      tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' }, valueFormatter: (value: number) => value.toLocaleString('zh-CN', { maximumFractionDigits: 1 }) },
      xAxis: { type: 'value', name: '成本单位', splitLine: { lineStyle: { color: '#e6edf1' } } },
      yAxis: { type: 'category', data: caseLabels, inverse: true, axisLabel: { fontSize: 10 } },
      series: parts.map(([name, key]) => ({ name, type: 'bar', stack: 'cost', barMaxWidth: 22, data: real.map((row) => row[key]) })),
    }
  }, [caseLabels, real])

  const serviceOption = useMemo(() => {
    const products = [
      { name: '加急', key: 'urgentOnTimeRate', target: 0.98, color: '#d95848' },
      { name: '普通', key: 'standardOnTimeRate', target: 0.95, color: '#2d73a8' },
      { name: '经济', key: 'economyOnTimeRate', target: 0.90, color: '#58a178' },
    ] as const
    const grids = products.map((_, index) => ({ left: `${index * 33.3 + 3}%`, width: '28%', top: 68, bottom: 92 }))
    return {
      animationDuration: 500,
      title: products.map((product, index) => ({ text: `${product.name}（目标${product.target * 100}%）`, left: `${index * 33.3 + 11}%`, top: 22, textStyle: { fontSize: 12, color: '#25465c' } })),
      grid: grids,
      tooltip: { trigger: 'axis', valueFormatter: (value: number) => `${(value * 100).toFixed(2)}%` },
      xAxis: products.map((_, index) => ({ type: 'category', gridIndex: index, data: caseLabels, axisLabel: { rotate: 58, fontSize: 8 } })),
      yAxis: products.map((_, index) => ({ type: 'value', gridIndex: index, min: 0.82, max: 1, axisLabel: { formatter: (value: number) => `${Math.round(value * 100)}%`, fontSize: 9 }, splitLine: { lineStyle: { color: '#e8eef1' } } })),
      series: products.map((product, index) => ({
        name: product.name, type: 'bar', xAxisIndex: index, yAxisIndex: index, barMaxWidth: 16,
        data: real.map((row) => ({ value: row[product.key], itemStyle: { color: row[product.key] >= product.target ? '#70a78f' : product.color } })),
        markLine: { silent: true, symbol: 'none', label: { formatter: `目标${product.target * 100}%`, fontSize: 8 }, lineStyle: { color: '#e97935', type: 'dashed' }, data: [{ yAxis: product.target }] },
      })),
    }
  }, [caseLabels, real])

  const performanceOption = useMemo(() => {
    const hits = data.solverLimitHits ?? []
    const callColors = { day_start: '#183a58', periodic: '#70a78f', event: '#e97935' }
    const callLabels = { day_start: '日初规划', periodic: '6小时滚动', event: '事件重调度' }
    return {
      animationDuration: 500,
      grid: [{ left: 72, right: 35, top: 52, height: '35%' }, { left: 72, right: 35, top: '60%', bottom: 58 }],
      tooltip: { trigger: 'item' },
      xAxis: [
        { type: 'category', data: caseLabels, axisLabel: { show: false } },
        { type: 'category', gridIndex: 1, data: caseLabels, axisLabel: { rotate: 42, fontSize: 9 } },
      ],
      yAxis: [
        { type: 'value', name: '累计求解/分钟', splitLine: { lineStyle: { color: '#e8eef1' } } },
        { type: 'value', gridIndex: 1, name: '时间上限调用的Gap', axisLabel: { formatter: (value: number) => `${(value * 100).toFixed(0)}%` }, splitLine: { lineStyle: { color: '#e8eef1' } } },
      ],
      series: [
        { name: '累计Gurobi时间', type: 'bar', barMaxWidth: 24, itemStyle: { color: '#2d6689' }, data: real.map((row) => Number((row.runtimeSeconds / 60).toFixed(2))) },
        ...(['day_start', 'periodic', 'event'] as const).map((callType) => ({
          name: callLabels[callType], type: 'scatter', xAxisIndex: 1, yAxisIndex: 1, symbolSize: 9, itemStyle: { color: callColors[callType] },
          data: hits.filter((hit) => hit.callType === callType).map((hit) => [compactCaseId(hit.caseId), hit.gap, hit.hour]),
          tooltip: { formatter: (params: { value: [string, number, number] }) => `${params.value[0]}<br/>${callLabels[callType]} ${params.value[2]}h<br/>Gap ${(params.value[1] * 100).toFixed(2)}%` },
          markLine: callType === 'day_start' ? { silent: true, symbol: 'none', lineStyle: { color: '#e97935', type: 'dashed' }, label: { formatter: '目标Gap 5%' }, data: [{ yAxis: 0.05 }] } : undefined,
        })),
      ],
    }
  }, [caseLabels, data.solverLimitHits, real])

  const heatmapOption = useMemo(() => {
    if (!animation) return null
    const eventHour = Number(animation.event.slot ?? 5) * animation.slotHours
    const snapshot = [...animation.snapshots].reverse().find((item) => item.decisionHour >= eventHour) ?? animation.snapshots.at(-1)
    if (!snapshot) return null
    const nodes = snapshot.nodes.map((node) => node.nodeId)
    const hours = Array.from({ length: animation.observationSlots + 1 }, (_, slot) => `${slot * animation.slotHours}h`)
    const inventory: Array<[number, number, number]> = []
    const utilization: Array<[number, number, number]> = []
    snapshot.nodes.forEach((node, nodeIndex) => node.timeline.forEach((state) => {
      inventory.push([state.slot, nodeIndex, Number(state.inventoryTons.toFixed(2))])
      utilization.push([state.slot, nodeIndex, Number(((state.handlingUtilization ?? 0) * 100).toFixed(2))])
    }))
    return {
      animationDuration: 400,
      title: [{ text: '节点留仓量（吨）', left: 68, top: 13, textStyle: { fontSize: 12 } }, { text: '节点处理能力利用率（%）', left: 68, top: '52%', textStyle: { fontSize: 12 } }],
      tooltip: { position: 'top', formatter: (params: { value: [number, number, number]; seriesName: string }) => `${nodes[params.value[1]]} · ${hours[params.value[0]]}<br/>${params.seriesName}：${params.value[2]}` },
      grid: [{ left: 70, right: 72, top: 48, height: '32%' }, { left: 70, right: 72, top: '59%', bottom: 50 }],
      xAxis: [
        { type: 'category', data: hours, axisLabel: { interval: 3, fontSize: 9 } },
        { type: 'category', gridIndex: 1, data: hours, axisLabel: { interval: 3, fontSize: 9 } },
      ],
      yAxis: [{ type: 'category', data: nodes }, { type: 'category', gridIndex: 1, data: nodes }],
      visualMap: [
        { min: 0, max: Math.max(1, ...inventory.map((item) => item[2])), calculable: true, orient: 'vertical', right: 5, top: 62, itemHeight: 90, seriesIndex: 0, inRange: { color: ['#f4f8f8', '#6ca6a0', '#173b55'] } },
        { min: 0, max: 120, calculable: true, orient: 'vertical', right: 5, bottom: 45, itemHeight: 90, seriesIndex: 1, inRange: { color: ['#f7f5ea', '#f0aa5e', '#c84d42'] } },
      ],
      series: [
        { name: '留仓吨数', type: 'heatmap', data: inventory, emphasis: { itemStyle: { borderColor: '#173b55', borderWidth: 1 } }, markLine: { symbol: 'none', label: { formatter: `插单 ${eventHour}h` }, lineStyle: { color: '#d94e42', width: 2 }, data: [{ xAxis: `${eventHour}h` }] } },
        { name: '处理利用率%', type: 'heatmap', xAxisIndex: 1, yAxisIndex: 1, data: utilization, emphasis: { itemStyle: { borderColor: '#173b55', borderWidth: 1 } }, markLine: { symbol: 'none', label: { formatter: `插单 ${eventHour}h` }, lineStyle: { color: '#d94e42', width: 2 }, data: [{ xAxis: `${eventHour}h` }] } },
      ],
    }
  }, [animation])

  return (
    <section className="milp-results-dashboard" aria-labelledby="milp-results-title">
      <div className="subsection-title"><span id="milp-results-title">实验结果</span><small>12个统一口径案例</small></div>
      <div className="experiment-summary">
        <article><span>完成并验证</span><b>{summary?.completedCases ?? real.length}/{summary?.validatedCases ?? real.filter((row) => row.validationStatus === 'pass').length}</b><small>正式案例 / 独立校验通过</small></article>
        <article><span>Gurobi 调用</span><b>{summary?.gurobiCalls ?? '—'}</b><small>日初＋6小时滚动＋事件重调度</small></article>
        <article><span>累计求解器时间</span><b>{summary ? formatDuration(summary.sumSolverSeconds) : '—'}</b><small>96次调用的 runtime 求和，不是墙钟时间</small></article>
        <article className="inferred-card"><span>实际并行耗时</span><b>{summary?.parallelElapsedLabel ?? '—'}</b><small>{summary?.parallelElapsedIsInferred ? '时间戳推算 · 含写盘与独立验证' : '程序直接记录'}</small></article>
      </div>
      {summary?.parallelElapsedIsInferred && <details className="evidence-note"><summary>并行耗时证据与口径</summary><p>{summary.parallelElapsedEvidence} 该值用于描述本次实验墙钟耗时，不参与算法性能排名。</p></details>}
      <article className="result-figure"><header><div><h4>12个案例的总成本与分项构成</h4><p>横向堆叠后可直接判断成本差异来自运输、延期、服务不达标还是方案变更。</p></div></header><ChartCanvas option={costOption} label="12个MILP案例的成本分项堆叠图" height={500} /></article>
      <article className="result-figure"><header><div><h4>三类产品准时率与服务目标</h4><p>低于目标时记录不达标吨数并计入惩罚；所有未撤销货物仍须最终送达。</p></div></header><ChartCanvas option={serviceOption} label="加急普通经济三类产品准时率图" height={480} /></article>
      <article className="result-figure"><header><div><h4>求解性能与达到时间上限的调用</h4><p>上图为每个案例的累计Gurobi时间；下图只显示达到300秒上限的调用及其最终Gap。</p></div></header><ChartCanvas option={performanceOption} label="MILP累计运行时间与时间上限调用Gap图" height={560} /><p className="figure-footnote">12个日初规划均达到300秒上限；96次调用中共有 {summary?.timeLimitCalls ?? data.solverLimitHits?.length ?? 0} 次达到上限。12个案例最后一次滚动求解均为optimal，但该状态只对应当次剩余时域问题。</p></article>
      <article className="result-figure"><header><div><h4>节点留仓量与处理能力利用率示例</h4><p>示例固定采用test_urgent_insert_002，不随案例选择变化。留仓不仅可能来自处理能力，也可能来自班车运力、发车时机、中转衔接和成本权衡。</p></div></header>{heatmapOption ? <ChartCanvas option={heatmapOption} label="紧急插单示例的节点留仓量和处理能力利用率热力图" height={590} /> : <div className="chart-loading">{animationError ? `热力图数据读取失败：${animationError}` : '正在按需读取动画快照…'}</div>}</article>
    </section>
  )
}
