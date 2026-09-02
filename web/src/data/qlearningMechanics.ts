export interface QRule {
  name: string
  meaning: string
}

export const qStateRows = [
  { dimension: '时间阶段', calculation: '当前决策时段', encoding: '0小时=0；3–9小时=1；12小时以后=2' },
  { dimension: '运力压力', calculation: '计划货运总吨数÷（班车车辆总数×20吨）', encoding: '≤0.8为0；0.8–1.0为1；>1.0为2' },
  { dimension: '服务风险', calculation: '服务不达标吨数÷服务统计总吨数', encoding: '≤0.2为0；0.2–0.4为1；>0.4为2' },
  { dimension: '车辆紧张度', calculation: '未来自有班车数÷当前全网可用自有车数', encoding: '≤0.8为0；0.8–1.0为1；>1.0为2' },
  { dimension: '异常类型', calculation: '当前已知异常', encoding: '无/插单/撤单/故障=0/1/2/3' },
]

export const qVehicleRules: QRule[] = [
  { name: '稳定优先', meaning: '优先保留上一版未来班车，减少方案变化' },
  { name: '成本优先', meaning: '优先单位需求运力成本较低的班车任务' },
  { name: '服务优先', meaning: '优先需求压力大、发车早且易保障服务的任务' },
]

export const qCargoRules: QRule[] = [
  { name: '成本优先', meaning: '优先每吨运输、装卸、留仓和延误成本较低的行程' },
  { name: '时限优先', meaning: '在基础成本上增加100×延误时段数＋3×等待时段数' },
  { name: '灵活性优先', meaning: '增加2×中转次数和班次稀缺惩罚，偏好替代班次较多的行程' },
]

export const qActions = qVehicleRules.flatMap((vehicle, vehicleIndex) =>
  qCargoRules.map((cargo, cargoIndex) => ({
    index: vehicleIndex * qCargoRules.length + cargoIndex,
    vehicle: vehicle.name,
    cargo: cargo.name,
    label: `班车${vehicle.name}＋货物${cargo.name}`,
  })),
)
