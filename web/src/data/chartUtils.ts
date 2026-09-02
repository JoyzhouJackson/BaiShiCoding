import type { Category, ComparisonMetric, MethodId } from './types'

export type MetricKey = keyof Pick<
  ComparisonMetric,
  | 'totalCost'
  | 'transportCost'
  | 'handlingCost'
  | 'inventoryCost'
  | 'transferCost'
  | 'delayCost'
  | 'serviceShortfallCost'
  | 'changeCost'
  | 'runtimeSeconds'
  | 'completionHour'
  | 'urgentOnTimeRate'
  | 'standardOnTimeRate'
  | 'economyOnTimeRate'
  | 'changedMissionTasks'
  | 'reroutedTons'
>

export const metricOptions: Array<{ key: MetricKey; label: string; unit: string }> = [
  { key: 'totalCost', label: '总成本', unit: '成本单位' },
  { key: 'transportCost', label: '运输成本', unit: '成本单位' },
  { key: 'handlingCost', label: '装卸成本', unit: '成本单位' },
  { key: 'inventoryCost', label: '留仓库存成本', unit: '成本单位' },
  { key: 'transferCost', label: '中转成本', unit: '成本单位' },
  { key: 'delayCost', label: '延误成本', unit: '成本单位' },
  { key: 'serviceShortfallCost', label: '服务不达标惩罚', unit: '成本单位' },
  { key: 'changeCost', label: '方案变更成本', unit: '成本单位' },
  { key: 'urgentOnTimeRate', label: '加急准时率', unit: '%' },
  { key: 'standardOnTimeRate', label: '普通准时率', unit: '%' },
  { key: 'economyOnTimeRate', label: '经济准时率', unit: '%' },
  { key: 'runtimeSeconds', label: '运行时间', unit: '秒' },
  { key: 'completionHour', label: '完成时间', unit: '小时' },
  { key: 'changedMissionTasks', label: '改变班车任务数', unit: '项' },
  { key: 'reroutedTons', label: '改道吨数', unit: '等效吨' },
]

export const categoryLabels: Record<Category | 'all', string> = {
  all: '全部场景',
  normal: '正常',
  urgent_insert: '紧急插单',
  urgent_cancel: '紧急撤单',
  vehicle_breakdown: '车辆故障',
}

export function metricValue(metric: ComparisonMetric, key: MetricKey) {
  const value = Number(metric[key])
  return key.endsWith('OnTimeRate') ? value * 100 : value
}

export function percentile(sorted: number[], p: number) {
  if (sorted.length === 0) return 0
  const position = (sorted.length - 1) * p
  const base = Math.floor(position)
  const remainder = position - base
  return sorted[base + 1] === undefined
    ? sorted[base]
    : sorted[base] + remainder * (sorted[base + 1] - sorted[base])
}

export function boxStats(values: number[]) {
  const sorted = [...values].sort((a, b) => a - b)
  if (!sorted.length) return [0, 0, 0, 0, 0]
  return [sorted[0], percentile(sorted, 0.25), percentile(sorted, 0.5), percentile(sorted, 0.75), sorted.at(-1)!]
}

export function groupByMethod(metrics: ComparisonMetric[], key: MetricKey) {
  return (['milp', 'benders-cg', 'tabular-hrl'] as MethodId[]).map((methodId) => ({
    methodId,
    values: metrics.filter((item) => item.methodId === methodId).map((item) => metricValue(item, key)),
  }))
}

export function realMetricsForFindings(metrics: ComparisonMetric[]) {
  return metrics.filter((metric) => metric.dataStatus === 'real')
}
