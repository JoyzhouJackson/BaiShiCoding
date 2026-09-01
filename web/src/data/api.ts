import type {
  AnimationData,
  AnimationManifest,
  CaseDetail,
  CaseSummary,
  ComparisonData,
  FoundationData,
} from './types'

const cache = new Map<string, Promise<unknown>>()

function dataUrl(path: string) {
  const clean = path.replace(/^\.?\//, '')
  return `${import.meta.env.BASE_URL}${clean}`
}

export function fetchJson<T>(path: string): Promise<T> {
  const url = dataUrl(path)
  if (!cache.has(url)) {
    cache.set(url, fetch(url).then((response) => {
      if (!response.ok) throw new Error(`无法加载 ${path}: ${response.status}`)
      return response.json() as Promise<T>
    }))
  }
  return cache.get(url) as Promise<T>
}

export function loadInitialData() {
  return Promise.all([
    fetchJson<FoundationData>('data/foundation.json'),
    fetchJson<{ cases: CaseSummary[] }>('data/cases.json'),
    fetchJson<ComparisonData>('data/comparison.json'),
    fetchJson<AnimationManifest>('data/animation-manifest.json'),
  ])
}

export function loadCaseDetail(caseId: string) {
  return fetchJson<CaseDetail>(`data/case-details/${caseId}.json`)
}

export function loadAnimation(caseId: string) {
  return fetchJson<AnimationData>(`data/animations/${caseId}.json`)
}

export function loadAnimationUrl(url: string) {
  return fetchJson<AnimationData>(url)
}
