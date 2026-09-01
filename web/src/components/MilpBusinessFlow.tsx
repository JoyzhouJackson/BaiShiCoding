interface MilpBusinessFlowProps {
  onExplain: (title: string, content: string) => void
}

interface FlowNodeProps {
  title: string
  subtitle: string
  kind?: 'input' | 'decision' | 'check' | 'output' | 'event'
  onClick?: () => void
}

function FlowNode({ title, subtitle, kind = 'decision', onClick }: FlowNodeProps) {
  return (
    <button className={`business-flow-node ${kind}`} type="button" onClick={onClick}>
      <b>{title}</b><span>{subtitle}</span>
    </button>
  )
}

function Arrow({ label }: { label?: string }) {
  return <div className="business-flow-arrow" aria-hidden="true"><span>{label}</span>↓</div>
}

export default function MilpBusinessFlow({ onExplain }: MilpBusinessFlowProps) {
  return (
    <div className="business-flow-wrap">
      <div className="business-flow-caption">
        <span>核心逻辑</span>
        <b>候选生成后，班车开行与货物路由在同一个 MILP 中联合选择</b>
        <small>不是先定班车再分货，也不是把问题切成两个独立模型</small>
      </div>
      <div className="business-flow" role="group" aria-label="Gurobi完整业务求解流程：输入、触发、候选生成、联合优化、可执行性判断、插单判断、发布与滚动循环">
        <FlowNode kind="input" title="输入当前业务状态" subtitle="需求与截止期 · 网络 · 车辆 · 节点能力 · 成本" onClick={() => onExplain('输入当前业务状态', '每轮只使用当前已知信息：需求预测或已核实实际量、货物截止期、网络时空结构、车辆位置、节点积压、剩余处理能力、成本参数与已经执行的决策。')} />
        <Arrow />
        <FlowNode kind="check" title="为什么现在制定计划？" subtitle="日初 / 每6小时 / 随机异常" onClick={() => onExplain('三类决策时点', '日初形成初始48小时计划；每6小时更新实际货量、车辆位置、节点积压和剩余运力；异常发生时立即额外重调度，但不改变原有6小时滚动点。')} />
        <div className="business-flow-branches trigger-branches">
          <FlowNode title="日初规划" subtitle="形成当前信息与资源状态" />
          <FlowNode title="6小时滚动" subtitle="核实货量并更新系统状态" />
          <FlowNode kind="event" title="随机异常" subtitle="故障 / 插单 / 撤单" onClick={() => onExplain('异常更新', '故障只在实际存在自有车的位置发生并减少可用车辆；撤单删除尚未发运货物；插单加入新需求并判断当前或未来能否接入。')} />
        </div>
        <Arrow label="汇合" />
        <FlowNode kind="check" title="锁定已执行决策" subtitle="过去不可回滚，只重新安排未来" />
        <Arrow />
        <div className="candidate-pair">
          <FlowNode title="生成候选班车任务" subtitle="原定 · 串点 · 临时自有 · 外请" onClick={() => onExplain('候选班车任务', '先枚举在时空网络上物理可执行的车辆任务，包括原定班车、最多1个中间节点的串点任务、临时自有车任务和外请车任务。')} />
          <span className="join-mark">＋</span>
          <FlowNode title="生成候选货物行程" subtitle="直达 · 串点直达 · 中转 · 留仓 · 延期" onClick={() => onExplain('候选货物行程', '每批货物最多生成36条合法候选行程。行程可以跨时段留仓或延期，但必须满足时序与产品中转次数上限。')} />
        </div>
        <Arrow label="同时进入同一模型" />
        <FlowNode kind="decision" title="Gurobi 联合优化" subtitle="同时选择班车 y 与货物流 x" onClick={() => onExplain('联合决策', '整数变量决定车辆任务开行数，连续变量决定各需求在候选行程上的吨位。二者通过“区段货量≤20吨×任务车辆数”直接耦合。')} />
        <Arrow />
        <FlowNode kind="check" title="能否满足全部硬物理约束？" subtitle="车辆 · 运力 · 处理 · 时序 · 中转 · 执行锁定" />
        <div className="business-flow-split">
          <div><Arrow label="否" /><FlowNode kind="output" title="报告不可行" subtitle="给出冲突原因；插单则继续测最早可接入时刻" /></div>
          <div><Arrow label="是" /><FlowNode kind="check" title="本轮是否包含紧急插单？" subtitle="普通滚动直接发布；插单检查接入结果" /></div>
        </div>
        <div className="business-flow-branches admission-branches">
          <FlowNode kind="output" title="当前可接入" subtitle="本轮加入并发布方案" />
          <FlowNode kind="output" title="未来可接入" subtitle="报告最早时刻并安排延期运输" />
          <FlowNode kind="output" title="观察期内不可接入" subtitle="拒绝并明确报告" />
        </div>
        <Arrow />
        <FlowNode kind="output" title="发布与完整记录" subtitle="班车表 · 车辆变化 · 批次路径 · 节点时间线 · 成本与服务" onClick={() => onExplain('发布与记录', '每次计划快照都保存节点逐时段状态、班车任务、车辆来源、货物流、事件、成本与服务指标，供后续动画还原。')} />
        <Arrow />
        <FlowNode kind="check" title="仍有未送达货物或后续决策时点？" subtitle="是：回到状态更新；否：结束72小时观察" />
        <div className="loop-note">↻ 下一轮继续执行“更新状态—锁定过去—生成候选—联合优化”</div>
      </div>
    </div>
  )
}
