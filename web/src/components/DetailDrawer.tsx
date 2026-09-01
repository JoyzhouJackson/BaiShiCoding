import { useEffect } from 'react'

interface DetailDrawerProps {
  title: string
  content: string
  open: boolean
  onClose: () => void
}

export default function DetailDrawer({ title, content, open, onClose }: DetailDrawerProps) {
  useEffect(() => {
    if (!open) return
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [open, onClose])

  if (!open) return null
  return (
    <div className="drawer-layer" role="presentation" onMouseDown={onClose}>
      <aside
        className="detail-drawer"
        role="dialog"
        aria-modal="true"
        aria-label={title}
        onMouseDown={(event) => event.stopPropagation()}
      >
        <div className="drawer-head">
          <div>
            <span className="eyebrow">详细解释</span>
            <h3>{title}</h3>
          </div>
          <button className="icon-button" type="button" onClick={onClose} aria-label="关闭详细解释">×</button>
        </div>
        <p>{content}</p>
        <div className="drawer-tip">按 Esc 或点击抽屉外区域关闭</div>
      </aside>
    </div>
  )
}
