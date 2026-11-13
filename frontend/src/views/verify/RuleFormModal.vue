<template>
  <div v-if="open" class="modal-mask" @click.self="$emit('close')">
    <div class="modal">
      <div class="modal-head">
        <h3>{{ isEdit ? `修改规则（${rule?.['规则编号']}）` : '登记校验规则' }}</h3>
        <button class="btn ghost" type="button" @click="$emit('close')">关闭</button>
      </div>

      <div v-if="policy" class="policy-strip" style="margin-bottom: 12px">
        <span>采样比例 {{ policy.sample_ratio.min }}~{{ policy.sample_ratio.max }}%</span>
        <span>阻断上限 {{ policy.block_limit.min }}~{{ policy.block_limit.max }}%</span>
        <span>阻断级别：{{ policy.block_levels.join(' / ') }}</span>
        <span>最少样本量 {{ policy.min_sample_size }}</span>
        <span>硬阻断率 &gt; {{ Math.round(policy.hard_block_rate * 100) }}%</span>
      </div>

      <form @submit.prevent="submit">
        <div class="grid-2">
          <div class="form-field">
            <label>规则编号</label>
            <input v-model="form['规则编号']" :disabled="isEdit" placeholder="如 VERI-0004" />
          </div>
          <div class="form-field">
            <label>校验对象</label>
            <input v-model="form['校验对象']" placeholder="如 采集结果记录" />
          </div>
          <div class="form-field" style="grid-column: 1 / -1">
            <label>校验表达式（白名单语法：字段、比较、and/or/not、+-*/%）</label>
            <textarea v-model="form['校验表达式']" placeholder="如 price >= 100 and stock >= 0"></textarea>
          </div>
          <div class="form-field">
            <label>采样比例（%）</label>
            <input v-model.number="form['采样比例']" type="number" :min="policy?.sample_ratio.min" :max="policy?.sample_ratio.max" />
          </div>
          <div class="form-field">
            <label>阻断上限（%）</label>
            <input v-model.number="form['阻断上限']" type="number" :min="policy?.block_limit.min" :max="policy?.block_limit.max" />
          </div>
          <div class="form-field">
            <label>阻断级别</label>
            <select v-model="form['阻断级别']">
              <option v-for="level in policy?.block_levels ?? []" :key="level" :value="level">{{ level }}</option>
            </select>
          </div>
          <div class="form-field">
            <label>阈值配置（说明文本）</label>
            <input v-model="form['阈值配置']" placeholder="如 阻断上限 20%" />
          </div>
        </div>

        <p v-if="errorMessage" class="field-error" style="margin-top: 10px">{{ errorMessage }}</p>

        <div v-if="isEdit && versions.length" class="panel" style="margin-top: 14px">
          <p class="panel-title">版本链 <span class="panel-hint">修改保存即追加新版本；旧试运行批次永久保留冻结版本的结论</span></p>
          <table class="mini-table">
            <thead>
              <tr><th>版本</th><th>表达式</th><th>采样比例</th><th>阻断上限</th><th>阻断级别</th></tr>
            </thead>
            <tbody>
              <tr v-for="version in versions" :key="version.version_no">
                <td>v{{ version.version_no }}</td>
                <td>{{ version['校验表达式'] }}</td>
                <td>{{ version['采样比例'] }}%</td>
                <td>{{ version['阻断上限'] }}%</td>
                <td>{{ version['阻断级别'] }}</td>
              </tr>
            </tbody>
          </table>
        </div>

        <div class="modal-actions">
          <button class="btn" type="button" @click="$emit('close')">取消</button>
          <button class="btn primary" type="submit">{{ isEdit ? '保存并生成新版本' : '登记规则' }}</button>
        </div>
      </form>
    </div>
  </div>
</template>

<script setup lang="ts">
import { reactive, ref, watch } from 'vue'

import type { FrozenVersion, PolicySpec } from '@/api/trial'
import { createRule, updateRule } from '@/api/trial'

interface RuleRow extends Record<string, unknown> {
  id: number
}

const props = defineProps<{
  open: boolean
  policy: PolicySpec | null
  rule: RuleRow | null
  versions: FrozenVersion[]
}>()

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'saved', message: string): void
}>()

interface RuleForm {
  规则编号: string
  校验对象: string
  校验表达式: string
  采样比例: number | null
  阻断上限: number | null
  阻断级别: string
  阈值配置: string
}

const isEdit = ref(false)
const errorMessage = ref('')
const form = reactive<RuleForm>({
  规则编号: '',
  校验对象: '',
  校验表达式: '',
  采样比例: null,
  阻断上限: null,
  阻断级别: '',
  阈值配置: '',
})

watch(
  () => props.open,
  (open) => {
    if (!open) return
    errorMessage.value = ''
    isEdit.value = props.rule !== null
    if (props.rule) {
      form['规则编号'] = String(props.rule['规则编号'] ?? '')
      form['校验对象'] = String(props.rule['校验对象'] ?? '')
      form['校验表达式'] = String(props.rule['校验表达式'] ?? '')
      form['采样比例'] = props.policy ? Number(props.rule['采样比例']) : null
      form['阻断上限'] = Number(props.rule['阻断上限'])
      form['阻断级别'] = String(props.rule['阻断级别'] ?? '')
      form['阈值配置'] = String(props.rule['阈值配置'] ?? '')
    } else {
      Object.assign(form, {
        规则编号: '',
        校验对象: '',
        校验表达式: '',
        采样比例: null,
        阻断上限: null,
        阻断级别: props.policy?.block_levels[0] ?? '',
        阈值配置: '',
      })
    }
  },
)

function localValidate(): string {
  const ratio = Number(form['采样比例'])
  const limit = Number(form['阻断上限'])
  const policy = props.policy
  if (!policy) return '统一口径尚未加载'
  if (!String(form['规则编号'] ?? '').trim()) return '规则编号不能为空'
  if (!String(form['校验表达式'] ?? '').trim()) return '校验表达式不能为空'
  if (!Number.isInteger(ratio) || ratio < policy.sample_ratio.min || ratio > policy.sample_ratio.max) {
    return `采样比例越界：允许保存范围 ${policy.sample_ratio.min}~${policy.sample_ratio.max}%，越界范围为 <=0 或 >100`
  }
  if (!Number.isInteger(limit) || limit < policy.block_limit.min || limit > policy.block_limit.max) {
    return `阻断上限越界：允许保存范围 ${policy.block_limit.min}~${policy.block_limit.max}%，越界范围为 <=0 或 >100`
  }
  if (!policy.block_levels.includes(String(form['阻断级别']))) return `阻断级别只允许 ${policy.block_levels.join(' / ')}`
  return ''
}

async function submit() {
  errorMessage.value = localValidate()
  if (errorMessage.value) return
  const payload: Record<string, unknown> = {
    ...form,
    校验类型: '表达式校验',
    阈值配置: String(form['阈值配置'] ?? `阻断上限 ${form['阻断上限']}%`),
  }
  try {
    const result = props.rule ? await updateRule(props.rule.id, payload) : await createRule(payload)
    if (!result.ok) {
      errorMessage.value = result.message
      return
    }
    emit('saved', result.message)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '规则保存失败'
  }
}
</script>
