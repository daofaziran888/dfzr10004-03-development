/** 校验/计划视图共享类型，承接 api/trial.ts 的数据结构。 */
export type {
  FrozenVersion,
  GuardItem,
  GuardOverview,
  PolicySpec,
  SampleBatch,
  TrialRecord,
  FailedRecord,
} from '@/api/trial'

export interface RuleRow extends Record<string, unknown> {
  id: number
  status: string
  规则编号: string
  校验对象: string
  校验类型: string
  校验表达式: string
  阈值配置: string
  采样比例: number
  阻断级别: string
  阻断上限: number
  当前版本号: number
  最近校验: string
}

export interface PlanRow extends Record<string, unknown> {
  id: number
  status: string
  计划编号: string
  目标站点: string
  采集频率: string
}
