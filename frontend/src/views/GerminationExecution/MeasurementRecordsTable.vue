<script setup lang="ts">
import type { MeasurementTask } from '../../types'
import {
  measurementValue,
  measurementProgressTagTypes,
  progressStatusText,
} from '../../utils/measurement'
import { dateTimeText } from '../../utils'
const props = defineProps<{
  items: MeasurementTask[]
  compact?: boolean
  currentId?: string | null
  currentSample?: string
  currentDag?: number
  readonly?: boolean
}>()
defineEmits<{ edit: [task: MeasurementTask] }>()
function progressTagType(task: MeasurementTask) {
  return measurementProgressTagTypes[task.status]
}
function rowClass({ row }: { row: MeasurementTask }) {
  return (!!row.measurement_id && row.measurement_id === props.currentId) ||
    (row.sample_id === props.currentSample && row.day_after_germination === props.currentDag)
    ? 'measurement-current-row'
    : row.sample_id === props.currentSample
      ? 'measurement-current-sample'
      : row.day_after_germination === props.currentDag
        ? 'measurement-current-dag'
        : ''
}
</script>
<template>
  <div
    class="measurement-records-scroll"
    :class="{ 'measurement-records-compact': compact }"
    :aria-label="compact ? '本材料测定进度与记录' : '已录入的测定记录'"
  >
    <el-table
      :data="items"
      :row-class-name="rowClass"
      :empty-text="
        compact
          ? '该材料尚无幼苗测定任务，请先完成发芽巡检并核对取样。'
          : '没有已录入的测定记录。可调整筛选，或在待测工作台录入。'
      "
    >
      <el-table-column v-if="!compact" prop="experiment_number" label="实验编号" width="95" />
      <el-table-column v-if="!compact" label="物种" min-width="150">
        <template #default="{ row }"
          ><b>{{ row.taxon_common_name || row.taxon_scientific_name }}</b
          ><small v-if="row.taxon_common_name" class="table-subtitle">{{
            row.taxon_scientific_name
          }}</small></template
        >
      </el-table-column>
      <el-table-column label="幼苗编号" :min-width="compact ? 145 : 155">
        <template #default="{ row }">幼苗 {{ row.sample_display_number || '编号未确认' }}</template>
      </el-table-column>
      <el-table-column prop="day_after_germination" label="DAG" width="58" />
      <el-table-column label="根长（mm）" :min-width="compact ? 92 : 105">
        <template #default="{ row }">{{
          measurementValue(row.root_length_mm, row.root_unavailable, !!row.measurement_id)
        }}</template>
      </el-table-column>
      <el-table-column label="苗长（mm）" :min-width="compact ? 92 : 105">
        <template #default="{ row }">{{
          measurementValue(row.shoot_length_mm, row.shoot_unavailable, !!row.measurement_id)
        }}</template>
      </el-table-column>
      <el-table-column label="计划日期" :min-width="compact ? 108 : 120">
        <template #default="{ row }">{{ row.scheduled_date || '—' }}</template>
      </el-table-column>
      <el-table-column label="实际测定时间" :min-width="compact ? 140 : 175">
        <template #default="{ row }"
          ><span :class="{ 'measurement-compact-time': compact }">{{
            dateTimeText(row.measured_at)
          }}</span></template
        >
      </el-table-column>
      <el-table-column v-if="compact" label="状态 / 延迟" min-width="125">
        <template #default="{ row }"
          ><el-tag size="small" effect="light" :type="progressTagType(row)">{{
            progressStatusText(row)
          }}</el-tag></template
        >
      </el-table-column>
      <el-table-column v-else label="延迟" width="80">
        <template #default="{ row }">{{
          row.delay_days === null ? '—' : `${row.delay_days}天`
        }}</template>
      </el-table-column>
      <el-table-column label="备注" :min-width="compact ? 100 : 130">
        <template #default="{ row }">{{ row.notes || '—' }}</template>
      </el-table-column>
      <el-table-column v-if="!readonly" label="操作" fixed="right" :width="compact ? 70 : 85">
        <template #default="{ row }"
          ><el-button v-if="row.measurement_id" link type="primary" @click="$emit('edit', row)"
            >修改</el-button
          ><span v-else>—</span></template
        >
      </el-table-column>
    </el-table>
  </div>
</template>
