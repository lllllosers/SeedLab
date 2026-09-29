<script setup lang="ts">
import { ref } from 'vue'
import { ElMessage } from 'element-plus'
const days = defineModel<number[]>({ required: true })
const input = ref('')
function addDays() {
  const parts = input.value.split(/[\s,，;；]+/).filter(Boolean)
  if (!parts.length) return
  const parsed = parts.map(Number)
  if (parsed.some((day) => !Number.isInteger(day) || day < 0))
    return ElMessage.warning('DAG 只能填写大于或等于 0 的整数')
  if (new Set([...days.value, ...parsed]).size !== days.value.length + parsed.length)
    return ElMessage.warning('同一实验不能设置重复的 DAG 时间点')
  days.value = [...days.value, ...parsed].sort((a, b) => a - b)
  input.value = ''
}
</script>
<template>
  <div class="wizard-step-copy">
    <h2>DAG 测定计划</h2>
    <p>DAG 是 Days After Germination，即每株幼苗实际发芽后的第 N 天。可自由设置非负整数时间点。</p>
  </div>
  <div class="wizard-search-row">
    <el-input
      v-model="input"
      placeholder="输入 1, 3, 5, 7；可批量添加"
      @keyup.enter="addDays"
    /><el-button type="primary" @click="addDays">添加时间点</el-button>
  </div>
  <div class="dag-chips">
    <el-tag
      v-for="day in days"
      :key="day"
      size="large"
      closable
      @close="days = days.filter((item) => item !== day)"
      >DAG {{ day }}</el-tag
    ><span v-if="!days.length">至少添加一个时间点</span>
  </div>
  <p class="wizard-help">实际测定日期将以每株幼苗被判定发芽的时间为起点计算。</p>
</template>
