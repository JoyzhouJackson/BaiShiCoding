import { useEffect } from 'react'
import { qActions, qCargoRules, qStateRows, qVehicleRules } from '../data/qlearningMechanics'

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
  const isStateDetail = title === '5维离散状态'
  const isActionDetail = title === '9种组合规则'
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
        {isStateDetail && <div className="drawer-structured-detail">
          <p>状态按 <code>时间阶段｜运力压力｜服务风险｜车辆紧张度｜异常类型</code> 排列，并以竖线连接保存。</p>
          <div className="drawer-table-scroll"><table><thead><tr><th>维度</th><th>计算方法</th><th>离散编码</th></tr></thead><tbody>
            {qStateRows.map((row) => <tr key={row.dimension}><td>{row.dimension}</td><td>{row.calculation}</td><td>{row.encoding}</td></tr>)}
          </tbody></table></div>
          <div className="drawer-example"><b>状态示例</b><code>2|0|0|1|3</code><span>12小时以后、运力压力低、服务风险低、车辆紧张度中、车辆故障。</span></div>
        </div>}
        {isActionDetail && <div className="drawer-structured-detail">
          <div className="drawer-rule-groups">
            <section><h4>3种班车规则</h4>{qVehicleRules.map((rule) => <p key={rule.name}><b>{rule.name}</b>{rule.meaning}</p>)}</section>
            <section><h4>3种货物规则</h4>{qCargoRules.map((rule) => <p key={rule.name}><b>{rule.name}</b>{rule.meaning}</p>)}</section>
          </div>
          <h4>3×3形成9个Q表动作</h4>
          <ol className="drawer-action-list">{qActions.map((action) => <li key={action.index}><code>a{action.index}</code><span>{action.label}</span></li>)}</ol>
          <p className="drawer-note">动作选择的是规则组合，不是直接指定某一辆班车；规则解码器据此生成班车方案，下层LP再连续分配货量。</p>
        </div>}
        <div className="drawer-tip">按 Esc 或点击抽屉外区域关闭</div>
      </aside>
    </div>
  )
}
