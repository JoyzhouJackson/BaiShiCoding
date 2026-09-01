import { lazy, Suspense, useMemo, useState } from 'react'
import { categoryLabels, metricOptions, type MetricKey } from '../data/chartUtils'
import type { Category, ComparisonData } from '../data/types'
import SectionHeading from './SectionHeading'

const ComparisonChart = lazy(() => import('./ComparisonChart'))

interface ComparisonSectionProps { data: ComparisonData }

export default function ComparisonSection({ data }: ComparisonSectionProps) {
  const [metricKey, setMetricKey] = useState<MetricKey>('totalCost')
  const [category, setCategory] = useState<Category | 'all'>('all')
  const [chartType, setChartType] = useState<'line' | 'box'>('line')
  const selectedMetric = metricOptions.find((item) => item.key === metricKey)!
  const metrics = useMemo(() => data.metrics.filter((item) => category === 'all' || item.category === category), [category, data.metrics])
  const real = metrics.filter((item) => item.dataStatus === 'real')
  const mockMethods = data.methods.filter((item) => item.dataStatus === 'mock')
  const passed = real.filter((item) => item.validationStatus === 'pass').length
  const optimal = real.filter((item) => item.finalStatus === 'optimal').length

  return (
    <section className="page-section comparison-section" id="comparison">
      <SectionHeading
        index="03"
        kicker="统一口径结果"
        title="逐案例看差异，也看整体分布"
        description="三种方法共享案例、成本和服务口径。当前只有MILP是真实实验；模拟值只用于验证图表接口与布局。"
      />
      <div className="truth-banner" role="note">
        <div><span>真实证据</span><b>MILP · {real.length}例</b><small>{passed}例独立验证通过 · {optimal}例最终状态最优</small></div>
        {mockMethods.length > 0 && <div className="mock-warning"><span>模拟占位</span><b>{mockMethods.map((item) => item.label).join(' / ')}</b><small>不参与排名、结论或显著性分析</small></div>}
      </div>
      <div className="chart-controls">
        <label>指标<select value={metricKey} onChange={(event) => setMetricKey(event.target.value as MetricKey)}>{metricOptions.map((item) => <option key={item.key} value={item.key}>{item.label}</option>)}</select></label>
        <label>场景<select value={category} onChange={(event) => setCategory(event.target.value as Category | 'all')}>{Object.entries(categoryLabels).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label>
        <div className="segmented" aria-label="图形类型">
          <button className={chartType === 'line' ? 'active' : ''} type="button" onClick={() => setChartType('line')}>逐案例折线</button>
          <button className={chartType === 'box' ? 'active' : ''} type="button" onClick={() => setChartType('box')}>方法箱型图</button>
        </div>
      </div>
      <div className={`chart-shell ${mockMethods.length ? 'mock-surface' : ''}`}>
        <Suspense fallback={<div className="chart-loading">正在加载可视化组件…</div>}>
          <ComparisonChart metrics={metrics} metricKey={metricKey} chartType={chartType} unit={selectedMetric.unit} />
        </Suspense>
      </div>
      <p className="stat-note">每类仅3个案例，箱型图和折线仅作描述性比较，不进行置信区间或显著性检验。接入真实JSON后，对应方法水印会由 <code>dataStatus</code> 自动控制移除。</p>
    </section>
  )
}
