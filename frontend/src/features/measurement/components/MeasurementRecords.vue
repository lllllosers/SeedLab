<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { api, errorMessage } from '../../../shared/api/client'
import type { ExperimentStatus } from '../../experiments/index'
import type { MeasurementTask, MeasurementWorklist } from '../index'
import type { Paged } from '../../../shared/types'
import { measurementQueryParams, normalizedDag } from '../utils/measurementQuery'
import MeasurementRecordsTable from './MeasurementRecordsTable.vue'
import MeasurementEditDialog from './MeasurementEditDialog.vue'
const props = defineProps<{ experimentId: string; status: ExperimentStatus; days: number[] }>()
const search = ref(''),
  dag = ref<number | string | null | undefined>(null),
  dates = ref<string[]>([]),
  materialIds = ref<string[]>([])
const page = ref(1),
  pageSize = ref(50),
  items = ref<MeasurementTask[]>([]),
  total = ref(0),
  materialCount = ref(0),
  loading = ref(false)
const materials = ref<MeasurementWorklist['materials']>([]),
  editing = ref<MeasurementTask | null>(null)
const dialog = ref<InstanceType<typeof MeasurementEditDialog> | null>(null)
const filterDescription = computed(() =>
  [
    search.value.trim() ? `搜索“${search.value.trim()}”` : '',
    materialIds.value.length ? `已选 ${materialIds.value.length} 份材料` : '',
    normalizedDag(dag.value) !== null ? `DAG ${normalizedDag(dag.value)}` : '',
    dates.value?.length === 2 ? dates.value.join('—') : '',
  ]
    .filter(Boolean)
    .join(' · '),
)
let sequence = 0
async function load() {
  const current = ++sequence
  const params = measurementQueryParams({
    search: search.value,
    dag: dag.value,
    dates: dates.value,
    materialIds: materialIds.value,
    page: page.value,
    pageSize: pageSize.value,
  })
  loading.value = true
  try {
    const result = (
      await api.get<Paged<MeasurementTask> & { material_count: number }>(
        `/experiments/${props.experimentId}/measurement-records?${params}`,
      )
    ).data
    if (current === sequence) {
      items.value = result.items
      total.value = result.total
      materialCount.value = result.material_count
    }
  } catch (error) {
    ElMessage.error(errorMessage(error))
  } finally {
    if (current === sequence) loading.value = false
  }
}
watch([search, dag, dates, materialIds, pageSize], () => {
  if (page.value !== 1) page.value = 1
  else void load()
})
watch(page, () => void load())
onMounted(async () => {
  void load()
  try {
    let index = 1,
      pages = 1
    do {
      const result = (
        await api.get<MeasurementWorklist>(
          `/experiments/${props.experimentId}/measurement-worklist?status=all&page_size=100&page=${index}`,
        )
      ).data
      materials.value.push(...result.materials)
      pages = result.total_pages
      index++
    } while (index <= pages)
  } catch (error) {
    ElMessage.error(errorMessage(error))
  }
})
defineExpose({
  confirmDiscard: async () => !dialog.value || (await dialog.value.confirmDiscard()),
  dirty: () => dialog.value?.dirty() || false,
})
</script>
<template>
  <p class="wizard-help">
    查询已经录入的原始测定值。可按多份材料、发芽后测定时间（DAG）和实际测定日期筛选；0
    为真实零值，NA 为无法测量。
  </p>
  <div class="measurement-record-filters">
    <el-input
      v-model="search"
      placeholder="搜索材料、培养皿或幼苗编号（001-01 / 001-1-01）、中文名或学名"
      clearable
    />
    <el-select
      v-model="materialIds"
      multiple
      clearable
      filterable
      collapse-tags
      collapse-tags-tooltip
      placeholder="全部材料"
      ><el-option
        v-for="material in materials"
        :key="material.material_id"
        :value="material.material_id"
        :label="`${material.experiment_number} · ${material.common_name || material.scientific_name}`"
    /></el-select>
    <el-select v-model="dag" clearable placeholder="全部测定时间"
      ><el-option v-for="day in days" :key="day" :value="day" :label="`发芽后第 ${day} 天`"
    /></el-select>
    <el-date-picker
      v-model="dates"
      type="daterange"
      value-format="YYYY-MM-DD"
      start-placeholder="测定开始日期"
      end-placeholder="测定结束日期"
    />
  </div>
  <p class="measurement-result-feedback">
    共 {{ total }} 条记录 · 涉及 {{ materialCount }} 份材料<span v-if="filterDescription">
      · 当前：{{ filterDescription }}</span
    >
  </p>
  <MeasurementRecordsTable
    v-loading="loading"
    :items="items"
    :readonly="status === 'cancelled'"
    @edit="editing = $event"
  />
  <el-pagination
    v-model:current-page="page"
    v-model:page-size="pageSize"
    :page-sizes="[25, 50, 100]"
    :total="total"
    layout="total, sizes, prev, pager, next"
  />
  <MeasurementEditDialog
    ref="dialog"
    :task="editing"
    :status="status"
    @close="editing = null"
    @changed="load"
  />
</template>
