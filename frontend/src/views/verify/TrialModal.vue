<template>
  <div v-if="open" class="modal-mask" @click.self="$emit('close')">
    <div class="modal">
      <div class="modal-head">
        <h3>规则试运行：{{ rule?.['规则编号'] }}</h3>
        <button class="btn ghost" type="button" @click="$emit('close')">关闭</button>
      </div>

      <div class="grid-2" style="margin-bottom: 12px">
        <div class="form-field">
          <label>采集计划 id（如 TASK-0002 对应 id=2）</label>
          <input v-model.number="planId" type="number" placeholder="输入采集计划 id" @change="loadBatches" />
        </div>
        <div class="form-field">
          <label>结果样本批次</label>
          <select v-model="batchNo" :disabled="!batches.length">
            <option value="" disabled>请选择批次</option>
            <option v-for="batch in batches" :key="batch.batch_no" :value="batch.batch_no">
              {{ batch.batch_no }}（{{ batch.total }} 条样本，字段：{{ batch.fields.join('、') }}）
            </option>
          </select>
        </div>
      </div>

      <div v-if="rule" class="reason-box" style="margin-bottom: 12px">
        本次将冻结当前规则 v{{ rule['当前版本号'] }}：表达式「{{ rule['校验表达式'] }}」、采样比例
        {{ rule['采样比例'] }}%、阻断级别「{{ rule['阻断级别'] }}」、阻断上限 {{ rule['阻断上限'] }}%，
        三项口径来自同一版本。
      </div>

      <p v-if="errorMessage" class="field-error">{{ errorMessage }}</p>

      <div style="display: flex; gap: 8px">
        <button class="btn primary" type="button" :disabled="loading || !planId || !batchNo" @click="submitTrial">
          {{ loading ? '试运行中…' : '开始试运行' }}
        </button>
        <button class="btn" type="button" :disabled="loading" @click="loadBatches">刷新样本批次</button>
      </div>

      <div v-if="result" style="margin-top: 16px">
        <div class="panel-head" style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">
          <p class="panel-title" style="margin:0">
            试运行结论
            <span class="badge" :class="verdictClass(result.verdict)">{{ result.verdict }}</span>
            <span v-if="result.reused" class="badge blue">复用既有结论·未重复阻断</span>
          </p>
          <span class="panel-hint">{{ result.trial_no }} · {{ result.created_at }}</span>
        </div>

        <p class="reason-box">{{ result.reason }}</p>

        <div class="grid-3" style="margin: 10px 0">
          <div class="count-card pass"><span class="num">{{ result.pass_count }}</span><span class="lbl">通过</span></div>
          <div class="count-card block"><span class="num">{{ result.block_count }}</span><span class="lbl">阻断</span></div>
          <div class="count-card manual"><span class="num">{{ result.manual_count }}</span><span class="lbl">待人工确认</span></div>
        </div>

        <div class="kv-list" style="margin-bottom: 10px">
          <span>样本总量：{{ result.sample_size_total }}</span>
          <span>实际抽样：{{ result.sample_size_checked }}（比例 {{ result.sample_ratio }}%）</span>
          <span>采集计划：{{ result.plan_code }}（id={{ result.plan_id }}）</span>
          <span>样本批次：{{ result.batch_no }}</span>
          <span>冻结版本：v{{ result.frozen_version.version_no }}</span>
          <span>阻断率：{{ (result.block_rate * 100).toFixed(1) }}%</span>
        </div>

        <div v-if="Object.keys(result.missing_fields).length" class="reason-box" style="margin-bottom:10px">
          缺少字段（不直接判通过，转待人工确认）：
          <span v-for="(count, field) in result.missing_fields" :key="field" class="badge amber" style="margin-right:6px">
            {{ field }} × {{ count }}
          </span>
        </div>

        <p class="panel-title">首批不满足表达式的记录（最多 {{ result.failed_preview.length }} 条）</p>
        <div class="scroll-box">
          <table class="mini-table">
            <thead>
              <tr><th>记录号</th><th>判定</th><th>说明</th><th>记录内容</th></tr>
            </thead>
            <tbody>
              <tr v-for="item in result.failed_preview" :key="item.record_id">
                <td>{{ item.record_id }}</td>
                <td><span class="badge red">{{ item.outcome }}</span></td>
                <td>{{ item.note }}</td>
                <td><code>{{ JSON.stringify(item.payload) }}</code></td>
              </tr>
              <tr v-if="!result.failed_preview.length">
                <td colspan="4" class="empty-state">本批次没有不满足表达式的记录</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'

import type { RuleRow, SampleBatch, TrialRecord } from './trial-types'
import { fetchSampleBatches, runTrial, verdictClass } from '@/api/trial'

const props = defineProps<{
  open: boolean
  rule: RuleRow | null
}>()

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'done'): void
}>()

const planId = ref<number | null>(null)
const batchNo = ref('')
const batches = ref<SampleBatch[]>([])
const result = ref<TrialRecord | null>(null)
const loading = ref(false)
const errorMessage = ref('')

watch(
  () => props.open,
  (open) => {
    if (!open) return
    planId.value = null
    batchNo.value = ''
    batches.value = []
    result.value = null
    errorMessage.value = ''
  },
)

async function loadBatches() {
  if (!planId.value) {
    batches.value = []
    return
  }
  errorMessage.value = ''
  try {
    batches.value = await fetchSampleBatches(planId.value)
    if (!batches.value.length) errorMessage.value = '该采集计划暂无结果样本批次'
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '样本批次读取失败'
  }
}

async function submitTrial() {
  if (!props.rule || !planId.value || !batchNo.value) return
  loading.value = true
  errorMessage.value = ''
  try {
    const response = await runTrial(props.rule.id, planId.value, batchNo.value)
    if (!response.ok) {
      errorMessage.value = response.message
      return
    }
    result.value = response.entry
    emit('done')
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '试运行失败'
  } finally {
    loading.value = false
  }
}
</script>
