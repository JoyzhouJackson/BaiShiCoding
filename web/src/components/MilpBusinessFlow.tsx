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
  return <button className={`business-flow-node ${kind}`} type="button" onClick={onClick}><b>{title}</b><span>{subtitle}</span></button>
}

function Arrow({ label }: { label?: string }) {
  return <div className="business-flow-arrow" aria-hidden="true"><span>{label}</span>↓</div>
}

function BranchArrow({ label }: { label: string }) {
  return <div className="branch-arrow" aria-hidden="true"><span>{label}</span><b>↓</b></div>
}

export default function MilpBusinessFlow({ onExplain }: MilpBusinessFlowProps) {
  return (
    <div className="business-flow-wrap">
      <div className="business-flow-caption">
        <span>核心逻辑</span>
        <b>生成班车开行和货物行程候选，联合决策班车开行与货物路由</b>
        <small>班车候选给出可能的时刻、线路和车辆来源；货物候选给出可衔接的直达、中转、等待与延期行程</small>
      </div>
      <div className="business-flow" role="group" aria-label="MILP从业务状态、决策触发、异常分类、候选生成、联合优化到方案发布的完整路线">
        <FlowNode kind="input" title="输入当前业务状态" subtitle="需求 · 车辆 · 积压 · 节点能力 · 已执行方案" onClick={() => onExplain('输入当前业务状态', '每轮只使用当时已经获得的信息，并保留车辆位置、货物状态和已经执行的决策。')} />
        <Arrow />
        <FlowNode kind="check" title="当前属于哪类决策时点？" subtitle="日初 / 每6小时滚动 / 随机异常" />
        <div className="business-flow-branches trigger-branches">
          <div className="branch-lane"><BranchArrow label="日初" /><FlowNode title="日初规划" subtitle="预测需求与初始资源" /></div>
          <div className="branch-lane"><BranchArrow label="无紧急插单" /><FlowNode title="定时滚动" subtitle="核实货量并更新状态" /></div>
          <div className="branch-lane"><BranchArrow label="发生异常" /><FlowNode kind="event" title="识别异常类型" subtitle="插单 / 撤单 / 车辆故障" /></div>
        </div>

        <div className="event-flow-block">
          <h4>异常发生后分别处理</h4>
          <div className="event-type-grid">
            <article>
              <FlowNode kind="event" title="紧急插单" subtitle="新增加急需求" />
              <div className="admission-paths">
                <div><BranchArrow label="立即可行" /><FlowNode kind="output" title="当前接入" subtitle="本轮加入并运输" /></div>
                <div><BranchArrow label="当前不可行" /><FlowNode kind="output" title="未来接入" subtitle="选择最早可行时点" /></div>
                <div><BranchArrow label="各时点均不可行" /><FlowNode kind="output" title="观察期内不接入" subtitle="记录无法接入" /></div>
              </div>
            </article>
            <article>
              <FlowNode kind="event" title="紧急撤单" subtitle="撤销尚未发运货量" />
              <BranchArrow label="更新需求" />
              <FlowNode kind="output" title="减少剩余需求" subtitle="已发运部分不回滚" />
            </article>
            <article>
              <FlowNode kind="event" title="车辆故障" subtitle="识别车辆及所在节点" />
              <BranchArrow label="更新资源" />
              <FlowNode kind="output" title="扣减可用自有车" subtitle="故障影响持续至观察期末" />
            </article>
          </div>
        </div>

        <Arrow label="日初、普通滚动与异常分支汇合" />
        <FlowNode kind="check" title="锁定已执行决策" subtitle="过去不可回滚，只重新安排未来" />
        <Arrow />
        <div className="candidate-pair">
          <FlowNode title="生成候选班车任务" subtitle="时刻 · 直达/串点 · 原定/临时自有/外请" onClick={() => onExplain('候选班车任务', '枚举在时空网络上可以执行的班车任务。每个候选明确发车时点、线路、是否经过一个中间节点以及车辆来源；进入模型后再决定开行数量。')} />
          <span className="join-mark">＋</span>
          <FlowNode title="生成候选货物行程" subtitle="直达 · 串点不换车 · 中转 · 等待 · 延期" onClick={() => onExplain('候选货物行程', '针对每个“起点—终点—产品—到货时点”批次生成最多36条合法行程；每条行程明确搭乘哪些班车、何时等待或中转以及何时到达。')} />
        </div>
        <Arrow label="同时进入同一模型" />
        <FlowNode kind="decision" title="Gurobi联合优化" subtitle="决定班车开行 y、货物行程选择与连续货量 x" onClick={() => onExplain('联合决策', '整数变量决定候选班车开行数和货物行程是否可用，连续变量决定每批货物在各行程上的吨位；二者通过区段运力约束直接耦合。')} />
        <Arrow />
        <FlowNode kind="check" title="检查并优化完整方案" subtitle="车辆 · 运力 · 处理 · 时间衔接 · 中转 · 服务 · 成本" />
        <div className="business-flow-split">
          <div><BranchArrow label="无可行方案" /><FlowNode kind="output" title="报告异常" subtitle="记录阶段、状态与诊断信息" /></div>
          <div><BranchArrow label="得到可行方案" /><FlowNode kind="output" title="发布并完整记录" subtitle="班车表 · 货物路由 · 节点状态 · 成本与服务" /></div>
        </div>
        <Arrow />
        <FlowNode kind="check" title="还有未送达货物或后续决策时点？" subtitle="是：更新状态继续滚动；否：结束72小时观察" />
        <div className="loop-note">↻ 下一轮继续执行“更新状态—分类处理—锁定过去—生成候选—联合优化”</div>
      </div>
    </div>
  )
}
