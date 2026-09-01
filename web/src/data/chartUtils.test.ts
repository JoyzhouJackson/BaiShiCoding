import { describe, expect, it } from 'vitest'
import { boxStats, metricValue, percentile, realMetricsForFindings } from './chartUtils'
import type { ComparisonMetric } from './types'

const baseMetric: ComparisonMetric = {
  methodId: 'milp', methodLabel: 'MILP', dataStatus: 'real', caseId: 'case_1', category: 'normal',
  totalCost: 100, transportCost: 70, handlingCost: 10, inventoryCost: 5, transferCost: 3,
  delayCost: 4, serviceShortfallCost: 2, changeCost: 6, runtimeSeconds: 20, completionHour: 42,
  urgentOnTimeRate: .98, standardOnTimeRate: .95, economyOnTimeRate: .9,
  changedMissionTasks: 2, reroutedTons: 8, caseStatus: 'complete', validationStatus: 'pass',
  baselineStatus: 'time_limit', finalStatus: 'optimal',
}

describe('comparison data guards', () => {
  it('keeps mock metrics out of conclusions', () => {
    const mock: ComparisonMetric = { ...baseMetric, methodId: 'benders-cg', dataStatus: 'mock' }
    expect(realMetricsForFindings([baseMetric, mock])).toEqual([baseMetric])
  })

  it('converts on-time rates to percentage values', () => {
    expect(metricValue(baseMetric, 'urgentOnTimeRate')).toBe(98)
    expect(metricValue(baseMetric, 'totalCost')).toBe(100)
  })
})

describe('box plot statistics', () => {
  it('calculates interpolated quartiles without mutating input', () => {
    const values = [8, 2, 6, 4]
    expect(boxStats(values)).toEqual([2, 3.5, 5, 6.5, 8])
    expect(values).toEqual([8, 2, 6, 4])
  })

  it('handles empty and singleton samples', () => {
    expect(boxStats([])).toEqual([0, 0, 0, 0, 0])
    expect(percentile([3], .75)).toBe(3)
  })
})
