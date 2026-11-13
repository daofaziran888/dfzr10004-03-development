<template>
  <section class="page" data-module="taskplan">
    <header class="page-head">
      <div>
        <h2>采集任务编排管理</h2>
        <p class="page-desc">
          相邻业务页同步校验结论：展示每个计划最近一次校验批次与阻断原因，硬阻断未解除前不能进入下一批抓取，
          仅警告允许继续但保留待处理项；同批次重复试运行不会重复阻断。
        </p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记采集计划</button>
        <button class="btn" type="button" @click="exportRows">导出清单</button>
      </div>
    </header>

    <div class="panel">
      <div class="panel-head" style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">
        <p class="panel-title" style="margin:0">
          校验待处理清单
          <span class="panel-hint">跨计划汇总未解除的硬阻断 / 警告项，去重口径为计划 + 规则 + 批次</span>
        </p>
        <button class="btn" type="button" @click="loadPending">刷新待处理</button>
      </div>
      <div v-if="!pendingGuards.length" class="empty-state" style="padding:12px">暂无待处理项，所有已校验批次均已通过或处理完成</div>
      <div v-else class="scroll-box">
        <table class="mini-table">
          <thead>
            <tr><th>采集计划</th><th>规则</th><th>批次</th><th>阻断级别</th><th>结论</th><th>阻断原因</th><th>状态</th><th>更新时间</th><th>操作</th></tr>
          </thead>
          <tbody>
            <tr v-for="guard in pendingGuards" :key="guard.id">
              <td>{{ guard.plan_code }}</td>
              <td>{{ guard.rule_code }}</td>
              <td>{{ guard.batch_no }}</td>
              <td>{{ guard.block_level }}</td>
              <td><span class="badge" :class="verdictClass(guard.verdict)">{{ guard.verdict }}</span></td>
              <td style="max-width:280px">{{ guard.reason }}</td>
              <td><span class="badge" :class="stateClass(guard.state)">{{ guard.state }}</span></td>
              <td>{{ guard.updated_at }}</td>
              <td><button class="link" type="button" @click="handleResolve(guard.id)">标记处理</button></td>
            </tr>
          </tbody>
        </table>
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
          <th>校验门禁</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
          <td>
            <span v-if="guardMap[row.id]?.hard_blocked" class="badge red">硬阻断·禁下一批</span>
            <span v-else-if="guardMap[row.id]?.warning_count" class="badge amber">警告 {{ guardMap[row.id]?.warning_count }} 项</span>
            <span v-else class="badge green">可进入下一批</span>
          </td>
          <td class="row-actions">
            <button v-for="action in actions" :key="action" class="link" type="button" @click="runAction(action, row)">
              {{ action }}
            </button>
            <button class="link" type="button" @click="viewGuard(row)">校验看板</button>
            <button class="link" type="button" @click="applyNextBatch(row)">申请下一批</button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 2" class="empty-state">暂无采集计划数据</td>
        </tr>
      </tbody>
    </table>

    <div v-if="guardDetail" class="panel" style="margin-top:14px">
      <div class="panel-head" style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">
        <p class="panel-title" style="margin:0">
          {{ guardDetail.plan_code }} 校验看板
          <span class="panel-hint">下一批：{{ guardDetail.next_batch_no }}</span>
        </p>
        <button class="btn ghost" type="button" @click="guardDetail = null">收起</button>
      </div>
      <div class="grid-3" style="margin-bottom:10px">
        <div class="count-card block"><span class="num">{{ guardDetail.hard_block_count }}</span><span class="lbl">未解除硬阻断</span></div>
        <div class="count-card manual"><span class="num">{{ guardDetail.warning_count }}</span><span class="lbl">警告待处理</span></div>
        <div class="count-card pass"><span class="num">{{ guardDetail.allow_next_batch ? '允许' : '禁止' }}</span><span class="lbl">下一批门禁</span></div>
      </div>
      <div v-if="guardDetail.latest_trial" class="reason-box">
        最近一次校验批次：{{ guardDetail.latest_trial.batch_no }} · 规则 {{ guardDetail.latest_trial.rule_code }}
        （<span class="badge" :class="verdictClass(guardDetail.latest_trial.verdict)">{{ guardDetail.latest_trial.verdict }}</span>）
        <br />阻断原因：{{ guardDetail.latest_trial.reason }}
      </div>
      <div v-else class="reason-box">该计划还没有试运行批次。</div>
    </div>

    <footer class="page-foot">
      <span>共 {{ total }} 条采集计划</span>
      <span v-if="message" :class="messageError ? 'error-text' : 'success-text'">{{ message }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { request } from '@/api/client'
import {
  fetchGuardOverview,
  fetchPendingGuards,
  requestNextBatch,
  resolveGuard,
  stateClass,
  verdictClass,
} from '@/api/trial'
import type { GuardItem, GuardOverview, PlanRow } from '@/views/verify/trial-types'

const ENDPOINT = '/api/taskplan'
const columns = ['计划编号', '目标站点', '采集频率', '数据范围', '优先级', '资源配额', '预计用时', '计划状态']
const actions = ['启动计划', '暂停计划', '归档计划']
const filterFields = columns.slice(0, 2)

const rows = ref<PlanRow[]>([])
const total = ref(0)
const filters = ref<Record<string, string>>({})
const message = ref('')
const messageError = ref(false)
const pendingGuards = ref<GuardItem[]>([])
const guardOverviews = ref<GuardOverview[]>([])
const guardDetail = ref<GuardOverview | null>(null)

const guardMap = computed<Record<number, GuardOverview>>(() =>
  Object.fromEntries(guardOverviews.value.map((item) => [item.plan_id, item])),
)

const stats = computed(() => [
  { label: '采集计划总数', value: rows.value.length },
  { label: '硬阻断计划', value: guardOverviews.value.filter((item) => item.hard_blocked).length },
  { label: '待处理项', value: pendingGuards.value.length },
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
  notify('采集计划登记入口尚未接入审批流')
}

async function loadPending() {
  try {
    pendingGuards.value = await fetchPendingGuards()
  } catch (error) {
    notify(error instanceof Error ? error.message : '待处理清单读取失败', true)
  }
}

async function loadOverviews() {
  const overviews = await Promise.all(rows.value.map((row) => fetchGuardOverview(row.id).catch(() => null)))
  guardOverviews.value = overviews.filter((item): item is GuardOverview => item !== null)
}

async function viewGuard(row: PlanRow) {
  try {
    guardDetail.value = await fetchGuardOverview(row.id)
  } catch (error) {
    notify(error instanceof Error ? error.message : '校验看板读取失败', true)
  }
}

async function applyNextBatch(row: PlanRow) {
  try {
    const result = await requestNextBatch(row.id)
    notify(result.message, !result.ok)
    await Promise.all([reload(), loadPending()])
  } catch (error) {
    notify(error instanceof Error ? error.message : '下一批门禁校验失败', true)
  }
}

async function handleResolve(guardId: number) {
  try {
    const result = await resolveGuard(guardId)
    notify(result.message, !result.ok)
    await Promise.all([loadPending(), loadOverviews()])
    if (guardDetail.value) await viewGuard({ id: guardDetail.value.plan_id } as PlanRow)
  } catch (error) {
    notify(error instanceof Error ? error.message : '待处理项操作失败', true)
  }
}

async function runAction(action: string, row: PlanRow) {
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
    const payload = (await response.json()) as { items: PlanRow[]; total: number }
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
    await Promise.all([loadPending(), loadOverviews()])
  } catch (error) {
    notify(error instanceof Error ? error.message : '采集计划列表读取失败', true)
  }
}

onMounted(reload)
</script>
