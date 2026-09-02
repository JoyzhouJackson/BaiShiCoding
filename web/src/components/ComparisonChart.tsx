import { useEffect, useMemo, useRef } from 'react'
import * as echarts from 'echarts/core'
import { BoxplotChart, LineChart } from 'echarts/charts'
import { DataZoomComponent, GridComponent, LegendComponent, MarkAreaComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { boxStats, groupByMethod, metricValue, type MetricKey } from '../data/chartUtils'
import type { ComparisonMetric } from '../data/types'

echarts.use([LineChart, BoxplotChart, GridComponent, TooltipComponent, LegendComponent, DataZoomComponent, MarkAreaComponent, CanvasRenderer])

interface ComparisonChartProps {
  metrics: ComparisonMetric[]
  metricKey: MetricKey
  chartType: 'line' | 'box'
  unit: string
}

const colors = ['#183a58', '#e97935', '#70a78f']

export default function ComparisonChart({ metrics, metricKey, chartType, unit }: ComparisonChartProps) {
  const ref = useRef<HTMLDivElement>(null)
  const option = useMemo(() => {
    const methodIds = ['milp', 'benders-cg', 'tabular-hrl'] as const
    const labels = ['MILP', 'Benders＋CG', 'Q-learning—LP']
    const base = {
      animationDuration: 500,
      color: colors,
      grid: { left: 66, right: 28, top: 64, bottom: 80 },
      tooltip: { trigger: chartType === 'line' ? 'axis' : 'item' },
      legend: { top: 10, textStyle: { color: '#334d62' } },
    }
    if (chartType === 'box') {
      const grouped = groupByMethod(metrics, metricKey)
      return {
        ...base,
        xAxis: { type: 'category', data: labels, axisLabel: { color: '#52697a' } },
        yAxis: { type: 'value', name: unit, nameTextStyle: { color: '#718394' }, splitLine: { lineStyle: { color: '#e6edf1' } } },
        series: [{
          name: '12例分布', type: 'boxplot', data: grouped.map((group, index) => ({ value: boxStats(group.values), itemStyle: { color: `${colors[index]}33`, borderColor: colors[index] } })),
        }],
      }
    }
    const caseIds = [...new Set(metrics.map((item) => item.caseId))]
    const markArea = caseIds.length === 12 ? {
      silent: true,
      itemStyle: { color: 'rgba(24,58,88,.035)' },
      data: [[{ xAxis: caseIds[0], name: '正常' }, { xAxis: caseIds[2] }], [{ xAxis: caseIds[6], name: '撤单' }, { xAxis: caseIds[8] }]],
    } : undefined
    return {
      ...base,
      tooltip: {
        trigger: 'axis',
        formatter: (params: Array<{ axisValue: string; marker: string; seriesName: string; value: number }>) => {
          const body = params.map((item) => `${item.marker}${item.seriesName}：<b>${Number(item.value).toLocaleString('zh-CN', { maximumFractionDigits: 2 })}</b> ${unit}`).join('<br/>')
          return `<strong>${params[0]?.axisValue ?? ''}</strong><br/>${body}`
        },
      },
      xAxis: { type: 'category', data: caseIds.map((id) => id.replace('test_', '').replace('urgent_', 'u_').replace('vehicle_', 'v_')), axisLabel: { rotate: 32, color: '#52697a', fontSize: 10 } },
      yAxis: { type: 'value', name: unit, nameTextStyle: { color: '#718394' }, splitLine: { lineStyle: { color: '#e6edf1' } } },
      dataZoom: caseIds.length > 8 ? [{ type: 'inside' }, { type: 'slider', bottom: 18, height: 16, borderColor: 'transparent', backgroundColor: '#edf2f4' }] : [],
      series: labels.map((label, index) => {
        const methodId = methodIds[index]
        const methodRows = metrics.filter((item) => item.methodId === methodId)
        const map = new Map(methodRows.map((item) => [item.caseId, metricValue(item, metricKey)]))
        return {
          name: label, type: 'line', smooth: true, symbolSize: 7, connectNulls: false,
          lineStyle: { width: index === 0 ? 3 : 2, type: index === 0 ? 'solid' : 'dashed' },
          data: caseIds.map((caseId) => map.get(caseId) ?? null),
          markArea: index === 0 ? markArea : undefined,
        }
      }),
    }
  }, [chartType, metricKey, metrics, unit])

  useEffect(() => {
    if (!ref.current) return
    const chart = echarts.init(ref.current)
    chart.setOption(option)
    const observer = new ResizeObserver(() => chart.resize())
    observer.observe(ref.current)
    return () => { observer.disconnect(); chart.dispose() }
  }, [option])

  return <div className="comparison-chart" ref={ref} role="img" aria-label={`${chartType === 'line' ? '逐案例折线图' : '方法箱型图'}，比较MILP、Benders列生成和Q-learning—LP`} />
}
