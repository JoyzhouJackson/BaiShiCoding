import { useCallback, useEffect, useState } from 'react'
import { loadInitialData } from './data/api'
import type { AnimationManifest, CaseSummary, ComparisonData, FoundationData } from './data/types'
import ComparisonSection from './components/ComparisonSection'
import ConclusionSection from './components/ConclusionSection'
import DetailDrawer from './components/DetailDrawer'
import FoundationSection from './components/FoundationSection'
import Header from './components/Header'
import MethodExplorer from './components/MethodExplorer'
import SimulationSection from './components/SimulationSection'

interface AppData {
  foundation: FoundationData
  cases: CaseSummary[]
  comparison: ComparisonData
  animationManifest: AnimationManifest
}

export default function App() {
  const [data, setData] = useState<AppData | null>(null)
  const [error, setError] = useState('')
  const [selectedCaseId, setSelectedCaseId] = useState('test_urgent_insert_002')
  const [drawer, setDrawer] = useState({ open: false, title: '', content: '' })

  useEffect(() => {
    loadInitialData()
      .then(([foundation, caseData, comparison, animationManifest]) => {
        setData({ foundation, cases: caseData.cases, comparison, animationManifest })
        setSelectedCaseId(animationManifest.defaultCaseId)
      })
      .catch((reason: Error) => setError(reason.message))
  }, [])

  const explain = useCallback((title: string, content: string) => setDrawer({ open: true, title, content }), [])
  const closeDrawer = useCallback(() => setDrawer((value) => ({ ...value, open: false })), [])

  if (error) return <main className="fatal-state"><h1>页面数据读取失败</h1><p>{error}</p><p>请使用 <code>npm run dev</code> 或静态服务器访问，不要直接双击HTML文件。</p></main>
  if (!data) return <main className="boot-state"><div className="boot-mark">F</div><p>正在加载动态快运网络实验…</p></main>

  return (
    <>
      <Header />
      <main>
        <FoundationSection foundation={data.foundation} cases={data.cases} selectedCaseId={selectedCaseId} onSelectCase={setSelectedCaseId} onExplain={explain} />
        <MethodExplorer onExplain={explain} />
        <ComparisonSection data={data.comparison} />
        <SimulationSection cases={data.cases} selectedCaseId={selectedCaseId} onSelectCase={setSelectedCaseId} manifest={data.animationManifest} />
        <ConclusionSection data={data.comparison} />
      </main>
      <footer><div><b>动态快运网络优化演示</b><span>静态结果展示 · 数据与算法执行完全分离</span></div><a href="#top">返回顶部 ↑</a></footer>
      <DetailDrawer {...drawer} onClose={closeDrawer} />
    </>
  )
}
