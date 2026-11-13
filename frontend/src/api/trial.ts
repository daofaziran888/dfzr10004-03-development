/** 校验试运行相关接口封装与类型，采集结果校验页与采集任务编排页共用。 */
import { request } from '@/api/client'

export interface PolicySpec {
  sample_ratio: { min: number; max: number; unit: string }
  block_limit: { min: number; max: number; unit: string }
  min_sample_size: number
  hard_block_rate: number
  warn_rate: number
  manual_review_rate: number
  failed_preview_limit: number
  block_levels: string[]
  out_of_range: string
}

export interface FrozenVersion {
  version_no: number
  校验表达式: string
  采样比例: number
  阻断级别: string
  阻断上限: number
  [key: string]: string | number
}

export interface FailedRecord {
  record_id: string
  outcome: string
  note: string | null
  missing_fields: string[]
  payload: Record<string, unknown>
}

export interface TrialRecord {
  id: number
  trial_no: string
  rule_id: number
  rule_code: string
  plan_id: number
  plan_code: string
  batch_no: string
  frozen_version: FrozenVersion
  sample_size_total: number
  sample_size_checked: number
  sample_ratio: number
  pass_count: number
  block_count: number
  manual_count: number
  block_rate: number
  verdict: string
  reason: string
  required_fields: string[]
  missing_fields: Record<string, number>
  failed_preview: FailedRecord[]
  record_details: FailedRecord[]
  reused: boolean
  created_at: string
}

export interface SampleBatch {
  batch_no: string
  plan_id: number
  plan_code: string
  total: number
  fields: string[]
}

export interface GuardItem {
  id: number
  plan_id: number
  plan_code: string
  rule_id: number
  rule_code: string
  batch_no: string
  trial_id: number
  block_level: string
  verdict: string
  reason: string
  state: string
  blocked_count: number
  manual_count: number
  resolved: boolean
  created_at: string
  updated_at: string
}

export interface GuardOverview {
  plan_id: number
  plan_code: string
  next_batch_no: string
  hard_blocked: boolean
  allow_next_batch: boolean
  open_count: number
  hard_block_count: number
  warning_count: number
  latest_trial: {
    batch_no: string
    rule_code: string
    verdict: string
    reason: string
    updated_at: string
  } | null
  pending_items: GuardItem[]
}

async function readJson<T>(response: Response): Promise<T> {
  const body = (await response.json()) as { message?: string } & Record<string, unknown>
  if (!response.ok) {
    throw new Error(body.message ?? `接口返回 ${response.status}`)
  }
  return body as T
}

export async function fetchPolicy(): Promise<PolicySpec> {
  return readJson<PolicySpec>(await request('/api/verify/policy'))
}

export async function fetchSampleBatches(planId?: number): Promise<SampleBatch[]> {
  const query = planId ? `?plan_id=${planId}` : ''
  const body = await readJson<{ items: SampleBatch[] }>(await request(`/api/verify/samples/batches${query}`))
  return body.items
}

export async function runTrial(ruleId: number, planId: number, batchNo: string): Promise<{ ok: boolean; message: string; entry: TrialRecord }> {
  return readJson<{ ok: boolean; message: string; entry: TrialRecord }>(
    await request(`/api/verify/${ruleId}/trial`, {
      method: 'POST',
      body: JSON.stringify({ values: { plan_id: planId, batch_no: batchNo } }),
    }),
  )
}

export async function fetchTrials(ruleId: number): Promise<TrialRecord[]> {
  const body = await readJson<{ items: TrialRecord[] }>(await request(`/api/verify/${ruleId}/trials`))
  return body.items
}

export async function fetchRuleVersions(ruleId: number): Promise<FrozenVersion[]> {
  const body = await readJson<{ versions: FrozenVersion[] }>(await request(`/api/verify/${ruleId}/versions`))
  return body.versions
}

export async function createRule(values: Record<string, unknown>): Promise<{ ok: boolean; message: string }> {
  return readJson<{ ok: boolean; message: string }>(
    await request('/api/verify', { method: 'POST', body: JSON.stringify({ values }) }),
  )
}

export async function updateRule(ruleId: number, values: Record<string, unknown>): Promise<{ ok: boolean; message: string }> {
  return readJson<{ ok: boolean; message: string }>(
    await request(`/api/verify/${ruleId}`, { method: 'PUT', body: JSON.stringify({ values }) }),
  )
}

export async function fetchGuardOverview(planId: number): Promise<GuardOverview> {
  return readJson<GuardOverview>(await request(`/api/taskplan/${planId}/guard`))
}

export async function fetchPendingGuards(): Promise<GuardItem[]> {
  const body = await readJson<{ items: GuardItem[] }>(await request('/api/taskplan/guards/pending'))
  return body.items
}

export async function resolveGuard(guardId: number): Promise<{ ok: boolean; message: string }> {
  return readJson<{ ok: boolean; message: string }>(
    await request(`/api/taskplan/guards/${guardId}/resolve`, { method: 'POST' }),
  )
}

export async function requestNextBatch(planId: number): Promise<{ ok: boolean; message: string }> {
  return readJson<{ ok: boolean; message: string }>(
    await request(`/api/taskplan/${planId}/next-batch`, { method: 'POST' }),
  )
}

export function verdictClass(verdict: string): string {
  if (verdict === '通过') return 'green'
  if (verdict === '硬阻断') return 'red'
  if (verdict === '告警') return 'amber'
  if (verdict === '待人工确认' || verdict === '样本不足') return 'blue'
  return 'gray'
}

export function stateClass(state: string): string {
  if (state === '硬阻断') return 'red'
  if (state === '待处理') return 'amber'
  if (state === '已通过') return 'green'
  return 'gray'
}
