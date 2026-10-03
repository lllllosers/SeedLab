<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { api, errorMessage } from '../api/client'
import type { GerminationExecution } from '../types'
import { dateTimeText, statusLabels } from '../utils'
import GerminationQuickEntry from './GerminationExecution/GerminationQuickEntry.vue'
import SowingManagement from './GerminationExecution/SowingManagement.vue'
import DishStatusTable from './GerminationExecution/DishStatusTable.vue'
import ObservationHistory from './GerminationExecution/ObservationHistory.vue'
import SeedlingMeasurementWorkbench from './GerminationExecution/SeedlingMeasurementWorkbench.vue'
import PageBackButton from '../components/PageBackButton.vue'

const route = useRoute()
const execution = ref<GerminationExecution | null>(null)
const tab = ref('overview')
const measurementRef = ref<{ confirmDiscard: () => Promise<boolean> } | null>(null)
async function beforeTabLeave() {
  return !measurementRef.value || (await measurementRef.value.confirmDiscard())
}
watch(
  () => route.query.tab,
  (value) => {
    if (value === 'measurement') tab.value = 'measurement'
  },
  { immediate: true },
)
const overviewSearch = ref('')
const overviewStatus = ref('all')
const overviewPage = ref(1)
const overviewPageSize = 15
const selectedMaterialId = ref<string | null>(null)
function inspectMaterial(id: string) {
  selectedMaterialId.value = id
  tab.value = 'dishes'
}
const filteredMaterials = computed(() => {
  const term = overviewSearch.value.trim().toLocaleLowerCase()
  return (execution.value?.materials || []).filter((material) => {
    const matches =
      !term ||
      [
        material.taxon_common_name,
        material.taxon_scientific_name,
        material.taxon_code,
        material.seed_lot_code,
        material.source_code,
        String(material.experiment_number || material.preview_number),
      ].some((value) => value?.toLocaleLowerCase().includes(term))
    const state =
      material.sown_count > 0
        ? material.sown_count + material.cancelled_count >= material.dish_count
          ? 'sown'
          : 'partial'
        : material.cancelled_count >= material.dish_count
          ? 'cancelled'
          : 'pending'
    return matches && (overviewStatus.value === 'all' || overviewStatus.value === state)
  })
})
const overviewMaterials = computed(() =>
  filteredMaterials.value.slice(
    (overviewPage.value - 1) * overviewPageSize,
    overviewPage.value * overviewPageSize,
  ),
)
watch([overviewSearch, overviewStatus], () => {
  overviewPage.value = 1
})
const loading = ref(false)
async function load() {
  loading.value = true
  try {
    execution.value = (
      await api.get<GerminationExecution>(`/experiments/${route.params.id}/execution`)
    ).data
  } catch (error) {
    ElMessage.error(errorMessage(error))
  } finally {
    loading.value = false
  }
}
onMounted(load)
</script>
<template>
  <PageBackButton :to="`/experiments/${route.params.id}`" label="返回实验详情" />
  <div v-if="execution" class="page-heading detail-heading">
    <div>
      <div class="eyebrow">发芽实验执行 · {{ execution.experiment.code }}</div>
      <h1>{{ execution.experiment.name }}</h1>
      <p>
        先在置床管理中登记每个培养皿的实际时间，再记录发芽巡检。首次置床
        {{ dateTimeText(execution.experiment.started_at) }} ·
        {{ execution.dish_count }} 个计划培养皿
      </p>
    </div>
    <div class="heading-actions">
      <span class="status-pill large" :class="execution.experiment.status">{{
        statusLabels[execution.experiment.status]
      }}</span>
    </div>
  </div>
  <template v-if="execution"
    ><div v-if="execution.observation_period_overdue" class="execution-alert">
      <b>超过计划观察期限</b><span>仍可继续记录真实巡检与晚期发芽；实验不会自动完成。</span>
    </div>
    <section class="surface-panel execution-workspace">
      <el-tabs v-model="tab" :before-leave="beforeTabLeave"
        ><el-tab-pane label="概览" name="overview">
          <p class="wizard-help">
            查看整个实验的执行进度，按名称或状态查找材料。具体操作请切换到置床管理、发芽巡检或培养皿状态。
          </p>
          <div class="execution-overview-scope">整个实验</div>
          <div class="execution-overview-stats">
            <div>
              <small>计划培养皿</small><strong>{{ execution.dish_count }}</strong>
            </div>
            <div>
              <small>已置床</small
              ><strong>{{ execution.sown_count }} / {{ execution.dish_count }}</strong>
            </div>
            <div>
              <small>今日待巡检</small><strong>{{ execution.today_pending_count }}</strong>
            </div>
            <div>
              <small>已选幼苗</small><strong>{{ execution.sample_count }}</strong>
            </div>
          </div>
          <p v-if="execution.experiment.status !== 'active'" class="wizard-help">
            {{
              ['completed', 'cancelled'].includes(execution.experiment.status)
                ? '实验已结束，无当前执行待办；历史数据仍可查看。'
                : '实验尚未开始，无当前执行待办。'
            }}
          </p>
          <div class="execution-overview-toolbar">
            <div>
              <h3>实验材料进度总览</h3>
              <p>共 {{ filteredMaterials.length }} 份材料；点击材料可查看培养皿状态。</p>
            </div>
            <el-input
              v-model="overviewSearch"
              placeholder="搜索中文名、学名、实验编号或批次"
              clearable
            />
            <el-select v-model="overviewStatus" aria-label="筛选材料状态"
              ><el-option label="全部状态" value="all" /><el-option
                label="待置床"
                value="pending" /><el-option label="部分置床" value="partial" /><el-option
                label="已置床"
                value="sown" /><el-option label="已取消" value="cancelled"
            /></el-select>
          </div>
          <div class="execution-overview-tiles">
            <button
              v-for="material in overviewMaterials"
              :key="material.id"
              type="button"
              class="execution-overview-tile"
              @click="inspectMaterial(material.id)"
            >
              <span class="experiment-number-badge">{{
                String(material.experiment_number || material.preview_number).padStart(3, '0')
              }}</span
              ><b>{{ material.taxon_common_name || material.taxon_scientific_name }}</b
              ><small>{{ material.sown_count }}/{{ material.dish_count }} 已置床</small>
            </button>
          </div>
          <div v-if="!filteredMaterials.length" class="wizard-empty">
            没有符合条件的材料。请调整搜索词或状态筛选。
          </div>
          <el-pagination
            v-if="filteredMaterials.length"
            v-model:current-page="overviewPage"
            class="list-pagination"
            layout="prev, pager, next, jumper"
            :page-size="overviewPageSize"
            :total="filteredMaterials.length"
          />
          <p v-if="filteredMaterials.length" class="pagination-caption">
            {{ overviewPage }} / {{ Math.ceil(filteredMaterials.length / overviewPageSize) }} 页
          </p> </el-tab-pane
        ><el-tab-pane label="置床管理" name="sowing"
          ><SowingManagement :execution="execution" @changed="load" /></el-tab-pane
        ><el-tab-pane label="发芽巡检" name="entry"
          ><GerminationQuickEntry
            v-if="execution.experiment.status === 'active'"
            :execution="execution"
            @saved="load"
          />
          <div v-else class="wizard-empty">
            {{
              ['completed', 'cancelled'].includes(execution.experiment.status)
                ? '实验已结束，不能新增巡检。已有数据可在培养皿状态和巡检历史中查阅。'
                : '请先确认置床编号，并在置床管理登记至少一个培养皿的实际置床时间，再开始巡检。'
            }}
          </div></el-tab-pane
        ><el-tab-pane label="幼苗测定" name="measurement"
          ><SeedlingMeasurementWorkbench
            v-if="tab === 'measurement'"
            ref="measurementRef" /></el-tab-pane
        ><el-tab-pane label="培养皿状态" name="dishes"
          ><DishStatusTable
            :execution="execution"
            :material-id="selectedMaterialId"
            @show-all="selectedMaterialId = null" /></el-tab-pane
        ><el-tab-pane label="巡检历史" name="history"
          ><ObservationHistory :execution="execution" @changed="load" /></el-tab-pane
      ></el-tabs>
    </section>
  </template>
  <div v-else-if="loading" class="surface-panel wizard-empty">正在加载实验执行数据…</div>
</template>
