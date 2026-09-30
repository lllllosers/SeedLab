<script setup lang="ts">
import type { MeasurementTask } from '../../types'
import { measurementValue } from '../../utils/measurement'
import { dateTimeText } from '../../utils'
const props = defineProps<{
  items: MeasurementTask[]
  currentId?: string | null
  currentSample?: string
  currentDag?: number
  readonly?: boolean
}>()
defineEmits<{ edit: [task: MeasurementTask] }>()
function rowClass({ row }: { row: MeasurementTask }) {
  return row.measurement_id === props.currentId ||
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
  <el-table
    :data="items"
    :row-class-name="rowClass"
    empty-text="没有已录入的测定记录。可调整筛选，或在待测工作台录入。"
  >
    <el-table-column prop="experiment_number" label="实验编号" width="95" />
    <el-table-column label="物种" min-width="150"
      ><template #default="{ row }"
        ><b>{{ row.taxon_common_name || row.taxon_scientific_name }}</b
        ><small class="table-subtitle">{{
          row.taxon_common_name ? row.taxon_scientific_name : ''
        }}</small></template
      ></el-table-column
    >
    <el-table-column label="培养皿 / 幼苗" width="155"
      ><template #default="{ row }"
        >{{ row.field_number }} · 幼苗{{ String(row.sample_number).padStart(2, '0') }}</template
      ></el-table-column
    >
    <el-table-column prop="day_after_germination" label="DAG" width="65" />
    <el-table-column label="根长（mm）" width="105"
      ><template #default="{ row }">{{
        measurementValue(row.root_length_mm, row.root_unavailable, true)
      }}</template></el-table-column
    >
    <el-table-column label="苗长（mm）" width="105"
      ><template #default="{ row }">{{
        measurementValue(row.shoot_length_mm, row.shoot_unavailable, true)
      }}</template></el-table-column
    >
    <el-table-column prop="scheduled_date" label="计划日期" width="120" />
    <el-table-column label="实际测定时间" width="175"
      ><template #default="{ row }">{{ dateTimeText(row.measured_at) }}</template></el-table-column
    >
    <el-table-column label="延迟" width="80"
      ><template #default="{ row }">{{
        row.delay_days === null ? '—' : `${row.delay_days}天`
      }}</template></el-table-column
    >
    <el-table-column prop="notes" label="备注" min-width="130"
      ><template #default="{ row }">{{ row.notes || '—' }}</template></el-table-column
    >
    <el-table-column v-if="!readonly" label="操作" fixed="right" width="85"
      ><template #default="{ row }"
        ><el-button link type="primary" @click="$emit('edit', row)">修改</el-button></template
      ></el-table-column
    >
  </el-table>
</template>
