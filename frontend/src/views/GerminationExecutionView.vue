<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { api, errorMessage } from '../api/client'
import type { GerminationExecution } from '../types'
import { dateTimeText, statusLabels } from '../utils'
import GerminationQuickEntry from './GerminationExecution/GerminationQuickEntry.vue'
import SowingManagement from './GerminationExecution/SowingManagement.vue'
import DishStatusTable from './GerminationExecution/DishStatusTable.vue'
import ObservationHistory from './GerminationExecution/ObservationHistory.vue'
import PageBackButton from '../components/PageBackButton.vue'

const route = useRoute()
const execution = ref<GerminationExecution | null>(null)
const tab = ref('entry')
const loading = ref(false)
const loadedOnce = ref(false)
async function load() {
  loading.value = true
  try {
    execution.value = (
      await api.get<GerminationExecution>(`/experiments/${route.params.id}/execution`)
    ).data
    if (!loadedOnce.value) {
      tab.value = execution.value.experiment.status === 'ready' ? 'sowing' : 'entry'
      loadedOnce.value = true
    }
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
      <p>先在置床管理中登记每个培养皿的实际时间，再记录发芽巡检。首次置床 {{ dateTimeText(execution.experiment.started_at) }} · {{ execution.dish_count }} 个计划培养皿</p>
    </div>
    <div class="heading-actions">
      <span class="status-pill large" :class="execution.experiment.status">{{
        statusLabels[execution.experiment.status]
      }}</span>
    </div>
  </div>
  <template v-if="execution"
    ><div v-if="execution.observation_period_overdue" class="execution-alert">
      <b>已超过计划观察期</b><span>仍可继续记录真实巡检与晚期发芽；实验不会自动完成。</span>
    </div>
    <div class="execution-hero surface-panel"><div>
      <span class="eyebrow">实际置床进度</span>
      <h2>已置床 {{ execution.sown_count }} / {{ execution.dish_count }} 个培养皿</h2>
      <p v-if="execution.pending_count">尚有 {{ execution.pending_material_count }} 个材料未完成置床，整个实验最终完成日期暂不能确定。</p>
      <p v-else-if="execution.sown_count">按已置床培养皿估算最晚完成：{{ dateTimeText(execution.latest_sown_estimated_finish_at) }}</p>
      <p v-else>尚无培养皿实际置床。</p>
      <p v-if="execution.sown_count && execution.pending_count">当前已置床部分预计最晚完成：{{ dateTimeText(execution.latest_sown_estimated_finish_at) }}</p>
    </div></div>
    <div class="execution-stats">
      <div class="surface-panel">
        <small>培养皿</small><strong>{{ execution.dish_count }}</strong>
      </div>
      <div class="surface-panel">
        <small>置床种子</small><strong>{{ execution.seed_count }}</strong>
      </div>
      <div class="surface-panel">
        <small>累计发芽</small><strong>{{ execution.cumulative_germinated }}</strong>
      </div>
      <div class="surface-panel">
        <small>当前发芽率</small><strong>{{ execution.germination_rate }}%</strong>
      </div>
      <div class="surface-panel">
        <small>已选幼苗</small><strong>{{ execution.sample_count }}</strong>
      </div>
      <div class="surface-panel"><small>待置床</small><strong>{{ execution.pending_count }}</strong></div>
    </div>
    <section class="surface-panel material-overview">
      <div class="execution-section-head">
        <div>
          <h3>实验材料进度</h3>
          <p>
            {{
              execution.sample_scope === 'per_dish'
                ? '每个培养皿分别按发芽顺序取样'
                : '每个实验材料合计按发芽顺序取样'
            }}
          </p>
        </div>
      </div>
      <div class="material-overview-grid">
        <div
          v-for="material in execution.materials"
          :key="material.id"
          class="material-progress-card"
        >
          <b>{{ material.taxon_common_name || material.taxon_scientific_name }}</b>
          <small v-if="material.taxon_common_name">{{ material.taxon_scientific_name }}</small>
          <small>{{ material.seed_lot_code }} · {{ material.dish_count }} 个重复</small>
          <div class="material-progress-numbers">
            <span>发芽 {{ material.cumulative_germinated }} / {{ material.seed_count }}</span
            ><strong>{{ material.germination_rate }}%</strong>
          </div>
          <el-progress
            :percentage="material.germination_rate"
            :show-text="false"
            :stroke-width="5"
          />
          <p>已选幼苗 {{ material.sample_count }} / {{ material.sample_target ?? '—' }}</p>
        </div>
      </div>
    </section>
    <section class="surface-panel execution-workspace">
      <el-tabs v-model="tab"
        ><el-tab-pane label="置床管理" name="sowing"><SowingManagement :execution="execution" @changed="load" /></el-tab-pane
        ><el-tab-pane label="发芽巡检" name="entry"
          ><GerminationQuickEntry
            v-if="execution.experiment.status === 'active'"
            :execution="execution"
            @saved="load"
          />
          <div v-else class="wizard-empty">当前实验还不能新增发芽巡检。请先确认置床编号，并在“置床管理”登记至少一个培养皿的实际置床时间。</div></el-tab-pane
        ><el-tab-pane label="培养皿状态" name="dishes"
          ><DishStatusTable :execution="execution" /></el-tab-pane
        ><el-tab-pane label="巡检历史" name="history"
          ><ObservationHistory :execution="execution" @changed="load" /></el-tab-pane
      ></el-tabs>
    </section>
  </template>
  <div v-else-if="loading" class="surface-panel wizard-empty">正在加载实验执行数据…</div>
</template>
