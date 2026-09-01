import { glossary } from '../data/content'

interface TermProps {
  children: string
  term?: string
  onExplain?: (title: string, content: string) => void
}

export default function Term({ children, term = children, onExplain }: TermProps) {
  const explanation = glossary[term]
  if (!explanation) return <>{children}</>
  return (
    <button
      className="term"
      type="button"
      aria-label={`${children}：${explanation}`}
      data-tooltip={explanation}
      onClick={() => onExplain?.(children, explanation)}
    >
      {children}
    </button>
  )
}
