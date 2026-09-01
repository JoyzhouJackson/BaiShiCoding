import { glossary } from '../data/content'
import Term from './Term'

interface ExplainableTextProps {
  text: string
  onExplain: (title: string, content: string) => void
}

const terms = Object.keys(glossary).sort((a, b) => b.length - a.length)
const escaped = terms.map((term) => term.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'))
const matcher = new RegExp(`(${escaped.join('|')})`, 'g')

export default function ExplainableText({ text, onExplain }: ExplainableTextProps) {
  return <>{text.split(matcher).filter(Boolean).map((part, index) => glossary[part]
    ? <Term key={`${part}-${index}`} term={part} onExplain={onExplain}>{part}</Term>
    : part)}</>
}
