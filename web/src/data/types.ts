export type MethodId = 'milp' | 'benders-cg' | 'tabular-hrl'
export type DataStatus = 'real' | 'mock' | 'planned'
export type Category = 'normal' | 'urgent_insert' | 'urgent_cancel' | 'vehicle_breakdown'

export interface FoundationData {
  schemaVersion: number
  storagePolicy: string
  time: Record<string, number | number[]>
  network: {
    nodeCount: number
    undirectedEdgeCount: number
    maxStringStops: number
    nodes: Array<{
      nodeId: string
      initialOwnVehicles: number
      handlingMin: number
      handlingMax: number
      handlingAverage: number
      externalVehicleMax: number
    }>
    edges: Array<{
      origin: string
      destination: string
      travelSlots: number
      normalCost: number
      addedCost: number
      outsourcedCost: number
    }>
  }
  vehicle: Record<string, number | boolean | number[]>
  products: Record<string, ProductConfig>
  cost: Record<string, number>
  demand: Record<string, number | number[]>
  events: Record<string, number[] | number>
  datasets: {
    frozenMasterCases: number
    activeTestCases: number
    activePerCategory: number
    validationCases: number
  }
}

export interface ProductConfig {
  share: number
  deadline_slots: number
  max_transfers: number
  allow_overnight_hold: boolean
  minimum_on_time_rate: number
  delay_cost_per_ton_slot: number
  service_shortfall_penalty_per_ton: number
}

export interface CaseSummary {
  caseId: string
  category: Category
  categoryLabel: string
  eventType: string
  eventSlot: number | null
  eventHour: number | null
  forecastTotal: number
  actualTotal: number
  forecastErrorRate: number
  completionHour: number
  batches: Array<{ releaseHour: number; forecast: number; actual: number }>
  products: Record<string, { forecast: number; actual: number }>
}

export interface CaseDetail {
  caseId: string
  category: Category
  event: Record<string, unknown>
  nodes: Array<{
    id: string
    handling_capacity: number[]
    storage_capacity: number
    initial_own_vehicles: number
    external_vehicle_limit: number[]
  }>
  demands: Array<{
    id: string
    origin: string
    destination: string
    product: string
    releaseHour: number
    forecastTons: number
    actualTons: number
  }>
}

export interface ComparisonMetric {
  methodId: MethodId
  methodLabel: string
  dataStatus: DataStatus
  caseId: string
  category: Category
  totalCost: number
  transportCost: number
  handlingCost: number
  inventoryCost: number
  transferCost: number
  delayCost: number
  serviceShortfallCost: number
  changeCost: number
  runtimeSeconds: number
  completionHour: number
  urgentOnTimeRate: number
  standardOnTimeRate: number
  economyOnTimeRate: number
  changedMissionTasks: number
  reroutedTons: number
  caseStatus: string
  validationStatus: string
  baselineStatus: string
  finalStatus: string
}

export interface ComparisonData {
  schemaVersion: number
  methods: Array<{ methodId: MethodId; label: string; dataStatus: DataStatus }>
  metrics: ComparisonMetric[]
  mockPolicy: string
}

export interface AnimationManifest {
  defaultCaseId: string
  cases: Array<{ caseId: string; category: Category; url: string; bytes: number }>
  methods?: Array<{
    methodId: MethodId
    dataStatus: DataStatus
    cases: Array<{ caseId: string; category: Category; url: string; bytes: number }>
  }>
}

export interface NodeTimelineState {
  slot: number
  ownVehicles: number
  handlingTons: number
  handlingCapacityTons: number | null
  handlingUtilization: number | null
  inventoryTons: number
  inventoryCost: number
  releasedTons: number
  cargoDepartureTons: number
  cargoArrivalTons: number
  deliveredTons: number
  ownVehicleDepartures: number
  externalVehicleDepartures: number
}

export interface AnimationSnapshot {
  snapshotId: string
  decisionSlot: number
  decisionHour: number
  decisionType: string
  triggerReasons: string[]
  objective: number
  objectiveComponents: Record<string, number>
  serviceRates: Record<string, { on_time_rate: number }>
  nodes: Array<{ nodeId: string; timeline: NodeTimelineState[] }>
  missions: Array<{
    missionId: string
    vehicleSource: 'own' | 'external'
    mode: string
    route: string[]
    vehicleCount: number
    departureSlot: number
    arrivalSlot: number
    segments: Array<{
      origin: string
      destination: string
      departureSlot: number
      arrivalSlot: number
    }>
  }>
  cargoFlows: Array<{
    origin: string
    destination: string
    departureSlot: number
    arrivalSlot: number
    product: 'urgent' | 'standard' | 'economy'
    tons: number
  }>
}

export interface AnimationData {
  schemaVersion: number
  caseId: string
  category: Category
  slotHours: number
  observationSlots: number
  event: Record<string, unknown> & { type?: string; slot?: number }
  completionHour: number
  topology: {
    nodes: string[]
    edges: Array<{ origin: string; destination: string; travelSlots: number }>
  }
  rollingSteps: Array<{
    slot: number
    hour: number
    decisionType: string
    reasons: string[]
    status: string
    changeCost: number
    before: string
    after: string
  }>
  snapshots: AnimationSnapshot[]
}

export interface MethodContent {
  id: MethodId
  label: string
  shortLabel: string
  dataStatus: DataStatus
  statusText: string
  tagline: string
  why: string
  decides: string[]
  notDecides: string[]
  settings: Array<{ label: string; value: string }>
  verification: string[]
  advantages: string[]
  limitations: string[]
  explanations: {
    business: string[]
    algorithm: string[]
    math: string[]
  }
  flowNodes: Array<{
    id: string
    title: string
    subtitle: string
    x: number
    y: number
    detail: string
    kind?: 'input' | 'decision' | 'check' | 'output'
  }>
  flowEdges: Array<{ from: string; to: string; label?: string }>
}
