<template>
  <section class="page" data-module="verify">
    <header class="page-head">
      <div>
        <h2>采集结果校验管理</h2>
        <p class="page-desc">
          维护校验规则并对采集计划结果样本试运行：按采样比例抽样，产出通过 / 阻断 / 待人工确认结论；
          硬阻断拦截下一批抓取，仅警告放行并登记待处理项。
        </p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记校验规则</button>
        <button class="btn" type="button" @click="exportRows">导出清单</button>
      </div>
    </header>

    <div v-if="policy" class="panel">
      <p class="panel-title">统一门槛口径 <span class="panel-hint">保存条件、采样阈值、阻断上限、判定标准与越界范围前后端共用一份</span></p>
      <div class="policy-strip">
        <span>采样比例：{{ policy.sample_ratio.min }}~{{ policy.sample_ratio.max }}%（整数）</span>
        <span>阻断上限：{{ policy.block_limit.min }}~{{ policy.block_limit.max }}%（整数）</span>
        <span>单批最少样本量：{{ policy.min_sample_size }}</span>
        <span>硬阻断率：&gt; {{ Math.round(policy.hard_block_rate * 100) }}% 拦截下一批</span>
        <span>告警率：&gt; {{ Math.round(policy.warn_rate * 100) }}% 仅警告留待处理</span>
        <span>待人工确认率：&gt; {{ Math.round(policy.manual_review_rate * 100) }}%</span>
        <span>首批不满足记录展示：{{ policy.failed_preview_limit }} 条</span>
        <span>{{ policy.out_of_range }}</span>
      </div>
    </div>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label v-for="field in filterFields" :key="field" class="filter-item">
        <span>{{ field }}</span>
        <input v-model="filters[field]" :placeholder="`按${field}检索`" />
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>状态动作</th>
          <th>试运行 / 版本</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
          <td class="row-actions">
            <button v-for="action in actions" :key="action" class="link" type="button" @click="runAction(action, row)">
              {{ action }}
            </button>
          </td>
          <td class="row-actions">
            <button class="link" type="button" @click="openTrial(row)">试运行</button>
            <button class="link" type="button" @click="openEdit(row)">修改 / 版本</button>
            <button class="link" type="button" @click="viewHistory(row)">历史</button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 2" class="empty-state">暂无校验规则，可先登记</td>
        </tr>
      </tbody>
    </table>

    <TrialHistoryPanel v-if="historyRule" :trials="historyTrials" @refresh="loadHistory" />

    <footer class="page-foot">
      <span>共 {{ total }} 条校验规则</span>
      <span v-if="message" :class="messageError ? 'error-text' : 'success-text'">{{ message }}</span>
    </footer>

    <RuleFormModal
      :open="formOpen"
      :policy="policy"
      :rule="editingRule"
      :versions="versions"
      @close="formOpen = false"
      @saved="onSaved"
    />
    <TrialModal :open="trialOpen" :rule="trialRule" @close="trialOpen = false" @done="onTrialDone" />
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { request } from '@/api/client'
import { fetchPolicy, fetchRuleVersions, fetchTrials } from '@/api/trial'
import type { FrozenVersion, PolicySpec, RuleRow, TrialRecord } from './trial-types'
import RuleFormModal from './RuleFormModal.vue'
import TrialModal from './TrialModal.vue'
import TrialHistoryPanel from './TrialHistoryPanel.vue'

const ENDPOINT = '/api/verify'
const columns = ['规则编号', '校验对象', '校验表达式', '采样比例', '阻断上限', '阻断级别', '当前版本号', '最近校验']
const actions = ['启动校验', '暂停校验', '归档规则']
const filterFields = columns.slice(0, 2)

const rows = ref<RuleRow[]>([])
const total = ref(0)
const filters = ref<Record<string, string>>({})
const message = ref('')
const messageError = ref(false)
const policy = ref<PolicySpec | null>(null)

const formOpen = ref(false)
const editingRule = ref<RuleRow | null>(null)
const versions = ref<FrozenVersion[]>([])
const trialOpen = ref(false)
const trialRule = ref<RuleRow | null>(null)
const historyRule = ref<RuleRow | null>(null)
const historyTrials = ref<TrialRecord[]>([])

const stats = computed(() => [
  { label: '校验规则总数', value: rows.value.length },
  { label: '运行中规则', value: rows.value.filter((row) => row.status === '运行中').length },
  { label: '已暂停规则', value: rows.value.filter((row) => row.status === '已暂停').length },
])

function notify(text: string, isError = false) {
  message.value = text
  messageError.value = isError
}

function resetFilters() {
  filters.value = {}
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  editingRule.value = null
  versions.value = []
  formOpen.value = true
}

async function openEdit(row: RuleRow) {
  editingRule.value = row
  try {
    versions.value = await fetchRuleVersions(row.id)
  } catch (error) {
    versions.value = []
    notify(error instanceof Error ? error.message : '版本读取失败', true)
  }
  formOpen.value = true
}

function openTrial(row: RuleRow) {
  trialRule.value = row
  trialOpen.value = true
}

async function viewHistory(row: RuleRow) {
  historyRule.value = row
  await loadHistory()
}

async function loadHistory() {
  if (!historyRule.value) return
  try {
    historyTrials.value = await fetchTrials(historyRule.value.id)
  } catch (error) {
    notify(error instanceof Error ? error.message : '试运行历史读取失败', true)
  }
}

function onSaved(text: string) {
  formOpen.value = false
  notify(text)
  void reload()
}

function onTrialDone() {
  notify('试运行结论已生成，并同步到采集计划页待处理清单')
  void reload()
  if (historyRule.value) void loadHistory()
}

async function runAction(action: string, row: RuleRow) {
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values: { action } }),
    })
    const payload = (await response.json()) as { ok: boolean; message: string }
    notify(payload.message, !payload.ok)
    await reload()
  } catch (error) {
    notify(error instanceof Error ? error.message : '动作执行失败', true)
  }
}

async function reload() {
  const query = new URLSearchParams(filters.value as Record<string, string>).toString()
  try {
    const response = await request(`${ENDPOINT}?${query}`)
    const payload = (await response.json()) as { items: RuleRow[]; total: number }
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    notify(error instanceof Error ? error.message : '校验规则列表读取失败', true)
  }
}

onMounted(async () => {
  try {
    policy.value = await fetchPolicy()
  } catch (error) {
    notify(error instanceof Error ? error.message : '统一口径加载失败', true)
  }
  await reload()
})
</script>
