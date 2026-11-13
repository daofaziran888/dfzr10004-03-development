<template>
  <div class="panel">
    <div class="panel-head" style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">
      <p class="panel-title" style="margin:0">
        试运行批次记录
        <span class="panel-hint">同一规则 + 同一批样本只保留一次结论；规则修改后旧批次保留冻结版本结论</span>
      </p>
      <button class="btn" type="button" @click="$emit('refresh')">刷新</button>
    </div>

    <div v-if="!trials.length" class="empty-state" style="padding:16px">该规则还没有试运行记录</div>

    <div v-else class="scroll-box">
      <table class="mini-table">
        <thead>
          <tr>
            <th>试运行号</th><th>采集计划</th><th>样本批次</th><th>冻结版本</th>
            <th>抽样</th><th>通过</th><th>阻断</th><th>待确认</th><th>结论</th><th>时间</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="trial in trials" :key="trial.id">
            <td>{{ trial.trial_no }}</td>
            <td>{{ trial.plan_code }}</td>
            <td>{{ trial.batch_no }}</td>
            <td>v{{ trial.frozen_version.version_no }}</td>
            <td>{{ trial.sample_size_checked }}/{{ trial.sample_size_total }}</td>
            <td>{{ trial.pass_count }}</td>
            <td>{{ trial.block_count }}</td>
            <td>{{ trial.manual_count }}</td>
            <td><span class="badge" :class="verdictClass(trial.verdict)">{{ trial.verdict }}</span></td>
            <td>{{ trial.created_at }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<script setup lang="ts">
import type { TrialRecord } from '@/api/trial'
import { verdictClass } from '@/api/trial'

defineProps<{ trials: TrialRecord[] }>()
defineEmits<{ (e: 'refresh'): void }>()
</script>
