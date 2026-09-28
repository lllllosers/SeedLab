<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { api, errorMessage } from '../api/client'
import type { GerminationExecution } from '../types'
import { dateTimeText, statusLabels } from '../utils'
import GerminationQuickEntry from './GerminationExecution/GerminationQuickEntry.vue'
import DishStatusTable from './GerminationExecution/DishStatusTable.vue'
import ObservationHistory from './GerminationExecution/ObservationHistory.vue'

const route = useRoute()
const router = useRouter()
const execution = ref<GerminationExecution | null>(null)
const tab = ref('entry')
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
const elapsedDays = computed(() => {
  const started = execution.value?.experiment.started_at
  return started
    ? Math.max(0, Math.floor((Date.now() - new Date(started).getTime()) / 86400000))
    : 0
})
const periodProgress = computed(() => {
  const period = execution.value?.observation_period_days
  return period ? Math.min(100, Math.round((elapsedDays.value / period) * 100)) : 0
})
onMounted(load)
</script>
<template>
  <button class="back-link" @click="router.push(`/experiments/${route.params.id}`)">
    ← 返回实验详情
  </button>
  <div v-if="execution" class="page-heading detail-heading">
    <div>
      <div class="eyebrow">{{ execution.experiment.code }} / GERMINATION EXECUTION</div>
      <h1>{{ execution.experiment.name }}</h1>
      <p>
        置床于 {{ dateTimeText(execution.experiment.started_at) }} ·
        {{ execution.dish_count }} 个培养皿
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
      <b>已超过计划观察期</b><span>仍可继续记录真实巡检与晚期发芽；实验不会自动完成。</span>
    </div>
    <div class="execution-hero surface-panel">
      <div>
        <span class="eyebrow">OBSERVATION WINDOW</span>
        <h2>计划观察期 {{ execution.observation_period_days ?? '—' }} 天</h2>
        <p>
          已运行 {{ elapsedDays }} 天 · 计划结束
          {{ dateTimeText(execution.observation_period_end_at) }}
        </p>
      </div>
      <div class="execution-hero-progress">
        <strong>{{ periodProgress }}%</strong
        ><el-progress :percentage="periodProgress" :show-text="false" :stroke-width="6" /><small
          >计划时间进度</small
        >
      </div>
    </div>
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
    </div>
    <section class="surface-panel material-overview">
      <div class="execution-section-head">
        <div>
          <h3>实验材料进度</h3>
          <p>
            {{
              execution.sample_scope === 'per_dish'
                ? '每皿独立选前 N 株'
                : '每材料跨重复合计选前 N 株'
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
          <b>{{ material.taxon_name }}</b
          ><small>{{ material.seed_lot_code }} · {{ material.dish_count }} 个重复</small>
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
        ><el-tab-pane label="快速巡检" name="entry"
          ><GerminationQuickEntry
            v-if="execution.experiment.status === 'active'"
            :execution="execution"
            @saved="load"
          />
          <div v-else class="wizard-empty">当前实验状态不允许新增巡检。</div></el-tab-pane
        ><el-tab-pane label="培养皿状态" name="dishes"
          ><DishStatusTable :execution="execution" /></el-tab-pane
        ><el-tab-pane label="最近巡检" name="history"
          ><ObservationHistory :execution="execution" @changed="load" /></el-tab-pane
      ></el-tabs>
    </section>
  </template>
  <div v-else-if="loading" class="surface-panel wizard-empty">正在加载实验执行数据…</div>
</template>
