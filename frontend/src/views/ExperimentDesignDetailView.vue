<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api, errorMessage } from '../api/client'
import type {
  AvailableLot,
  ExperimentConfiguration,
  ExperimentMaterial,
  ExperimentProtocol,
} from '../types'
import { dateText, statusLabels } from '../utils'
import StartExperimentDialog from './GerminationExecution/StartExperimentDialog.vue'
import PageBackButton from '../components/PageBackButton.vue'

const route = useRoute()
const router = useRouter()
const config = ref<ExperimentConfiguration | null>(null)
const item = computed(() => config.value?.experiment)
const editable = computed(() => item.value?.status === 'draft')
const canEditInfo = computed(() => item.value?.status === 'draft' || item.value?.status === 'ready')
const activeTab = ref('overview')
const infoOpen = ref(false)
const protocolOpen = ref(false)
const materialOpen = ref(false)
const addOpen = ref(false)
const dagOpen = ref(false)
const startOpen = ref(false)
const info = reactive({
  name: '',
  description: '',
  planned_start_date: '',
})
const protocol = reactive<ExperimentProtocol>({
  seeds_per_dish: 20,
  replicate_count: 3,
  observation_period_days: 14,
  sampling_rule: 'first_germinated',
  sample_count: 5,
  sample_scope: 'per_dish',
  germination_criterion: '',
  summary: null,
})
const material = reactive({
  id: '',
  seeds_per_dish_override: null as number | null,
  replicate_count_override: null as number | null,
  sample_count_override: null as number | null,
  label: '',
})
const available = ref<AvailableLot[]>([])
const search = ref('')
const selectedLot = ref('')
const dagText = ref('')
const base = computed(() => `/experiments/${route.params.id}`)
async function load() {
  try {
    config.value = (await api.get<ExperimentConfiguration>(`${base.value}/configuration`)).data
  } catch (error) {
    ElMessage.error(errorMessage(error))
  }
}
async function run(request: () => Promise<unknown>, message: string, close?: () => void) {
  try {
    await request()
    ElMessage.success(message)
    close?.()
    await load()
  } catch (error) {
    ElMessage.error(errorMessage(error))
  }
}
function editInfo() {
  if (!item.value) return
  Object.assign(info, {
    name: item.value.name,
    description: item.value.description || '',
    planned_start_date: item.value.planned_start_date || '',
  })
  infoOpen.value = true
}
function saveInfo() {
  if (!info.name.trim()) return ElMessage.warning('请填写实验名称')
  const patch = {
    name: info.name.trim(),
    description: info.description.trim() || null,
    planned_start_date: info.planned_start_date || null,
  }
  run(
    () => api.patch(base.value, patch),
    '实验信息已更新',
    () => (infoOpen.value = false),
  )
}
async function changeStatus(target: 'ready' | 'draft') {
  const preparing = target === 'ready'
  try {
    await ElMessageBox.confirm(
      preparing
        ? '标记后仍可返回草稿修改；正式开始实验后将不能再修改材料、重复数和测定时间。'
        : '返回草稿后可继续调整材料、方案和测定时间；调整完成后需要再次标记为已就绪。',
      preparing ? '确定将实验标记为“已就绪”吗？' : '确定将实验返回草稿吗？',
      { confirmButtonText: preparing ? '标记为已就绪' : '返回草稿', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  await run(() => api.patch(base.value, { status: target }),
    preparing ? '实验已标记为已就绪' : '实验已返回草稿')
}
function editProtocol() {
  Object.assign(protocol, config.value?.protocol || {})
  protocolOpen.value = true
}
function saveProtocol() {
  run(
    () => api.put(`${base.value}/protocol`, protocol),
    '默认方案已保存',
    () => (protocolOpen.value = false),
  )
}
function editMaterial(entry: ExperimentMaterial) {
  Object.assign(material, {
    id: entry.id,
    label: entry.label || '',
    seeds_per_dish_override: entry.seeds_per_dish_override,
    replicate_count_override: entry.replicate_count_override,
    sample_count_override: entry.sample_count_override,
  })
  materialOpen.value = true
}
function saveMaterial() {
  run(
    () =>
      api.patch(`${base.value}/materials/${material.id}`, {
        label: material.label || null,
        seeds_per_dish_override: material.seeds_per_dish_override,
        replicate_count_override: material.replicate_count_override,
        sample_count_override: material.sample_count_override,
      }),
    '材料参数已保存',
    () => (materialOpen.value = false),
  )
}
async function searchLots() {
  try {
    available.value = (
      await api.get<AvailableLot[]>('/experiments/available-seed-lots', {
        params: { q: search.value },
      })
    ).data
  } catch (error) {
    ElMessage.error(errorMessage(error))
  }
}
function openAdd() {
  selectedLot.value = ''
  search.value = ''
  searchLots()
  addOpen.value = true
}
function addMaterial() {
  if (!selectedLot.value) return ElMessage.warning('请选择种子批次')
  run(
    () => api.post(`${base.value}/materials`, { seed_lot_id: selectedLot.value }),
    '材料已加入',
    () => (addOpen.value = false),
  )
}
async function removeMaterial(entry: ExperimentMaterial) {
  try {
    await ElMessageBox.confirm(
      `确定从本实验移除种子批次 ${entry.seed_lot_code} 吗？该材料的单独设置也会一并移除。`,
      '移除实验材料',
    )
  } catch {
    return
  }
  run(() => api.delete(`${base.value}/materials/${entry.id}`), '材料已移除')
}
function moveMaterial(index: number, delta: number) {
  const ids = config.value?.materials.map((entry) => entry.id) || []
  const other = index + delta
  if (other < 0 || other >= ids.length) return
  ;[ids[index], ids[other]] = [ids[other]!, ids[index]!]
  run(() => api.put(`${base.value}/materials/order`, { material_ids: ids }), '材料顺序已更新')
}
function editDag() {
  dagText.value = config.value?.dag_days.join(', ') || ''
  dagOpen.value = true
}
function saveDag() {
  const parts = dagText.value.split(/[\s,，;；]+/).filter(Boolean)
  const days = parts.map(Number)
  if (!days.length || days.some((day) => !Number.isInteger(day) || day < 0))
    return ElMessage.warning('请填写发芽后第几天测定，天数不能小于 0')
  if (new Set(days).size !== days.length) return ElMessage.warning('同一天的测定时间只需填写一次')
  run(
    () => api.put(`${base.value}/dag`, { days }),
    'DAG 计划已保存',
    () => (dagOpen.value = false),
  )
}
onMounted(load)
</script>

<template>
  <PageBackButton to="/experiments" label="返回实验列表" />
  <div v-if="item" class="page-heading detail-heading">
    <div>
      <div class="eyebrow">实验编号 {{ item.code }}</div>
      <h1>{{ item.name }}</h1>
      <p>核对实验材料和测定方案，确认无误后开始实验。计划开始 {{ dateText(item.planned_start_date) }}</p>
    </div>
    <div class="heading-actions">
      <span class="experiment-current-status">当前状态：<span class="status-pill large" :class="item.status">{{ statusLabels[item.status] }}</span></span
      ><el-button v-if="item.status === 'draft'" type="primary" @click="changeStatus('ready')">标记为已就绪</el-button
      ><el-button v-if="item.status === 'ready'" @click="changeStatus('draft')">返回草稿</el-button
      ><el-button v-if="item.status === 'ready'" type="primary" @click="startOpen = true"
        >正式开始实验</el-button
      ><el-button
        v-if="item.status === 'active'"
        type="primary"
        plain
        @click="router.push(`/experiments/${item.id}/germination`)"
        >进入实验执行</el-button
      ><el-button v-if="canEditInfo" @click="editInfo">编辑信息</el-button>
    </div>
  </div>
  <p v-if="item" class="experiment-flow-hint">{{
    item.status === 'draft' ? '确认材料、方案和发芽后测定时间（DAG）后，可标记为已就绪。' :
    item.status === 'ready' ? '确认实际置床时间后正式开始；如需调整方案，请先返回草稿。' :
    item.status === 'active' ? '实验正在执行，进入发芽巡检页面记录数据。' :
    '该实验目前不再接受材料和测定方案修改。'
  }}</p>
  <div v-if="config" class="surface-panel design-detail">
    <el-tabs v-model="activeTab" class="design-tabs">
      <el-tab-pane label="概览" name="overview"
        ><div class="review-grid">
          <div>
            <small>实验材料</small><strong>{{ config.workload?.material_count ?? '—' }}</strong>
          </div>
          <div>
            <small>预计培养皿</small
            ><strong>{{ config.workload?.estimated_dish_count ?? '—' }}</strong>
          </div>
          <div>
            <small>预计置床种子</small
            ><strong>{{ config.workload?.estimated_seed_count ?? '—' }}</strong>
          </div>
          <div>
            <small>预计幼苗样本</small
            ><strong>{{ config.workload?.estimated_sample_count ?? '—' }}</strong>
          </div>
          <div>
            <small>预计测定记录</small
            ><strong>{{ config.workload?.estimated_measurement_count ?? '—' }}</strong>
          </div>
          <div>
            <small>预计最晚完成</small
            ><strong class="date">{{
              config.workload?.estimated_latest_finish_date || '未计算'
            }}</strong>
          </div>
        </div>
        <div class="design-note">
          <b>实验说明</b>
          <p>{{ item?.description || '暂无说明' }}</p>
          <b>计划日期与负责人</b>
          <p>{{ dateText(item?.planned_start_date) }} · {{ config.owner_name || '未指定' }}</p>
        </div></el-tab-pane
      >
      <el-tab-pane label="实验方案" name="protocol"
        ><div class="design-section-head">
          <div>
            <h3>默认方案</h3>
            <p>个别材料可单独设置每皿粒数、重复数和取样数</p>
          </div>
          <el-button v-if="editable" @click="editProtocol">编辑方案</el-button>
        </div>
        <dl v-if="config.protocol" class="info-list">
          <div>
            <dt>每皿种子数</dt>
            <dd>{{ config.protocol.seeds_per_dish }} 粒</dd>
          </div>
          <div>
            <dt>每材料重复数</dt>
            <dd>{{ config.protocol.replicate_count }} 次</dd>
          </div>
          <div>
            <dt>观察周期</dt>
            <dd>{{ config.protocol.observation_period_days }} 天</dd>
          </div>
          <div>
            <dt>取样方式</dt>
            <dd>按发芽顺序取前 N 株</dd>
          </div>
          <div>
            <dt>取样范围</dt>
            <dd>
              {{
                config.protocol.sample_scope === 'per_dish' ? '每个培养皿取' : '每个实验材料合计取'
              }}
              {{ config.protocol.sample_count }} 株
            </dd>
          </div>
          <div>
            <dt>发芽判定标准</dt>
            <dd>{{ config.protocol.germination_criterion }}</dd>
          </div>
          <div>
            <dt>方案备注</dt>
            <dd>{{ config.protocol.summary || '—' }}</dd>
          </div>
        </dl>
        <div v-else class="wizard-empty">尚未填写默认实验方案</div></el-tab-pane
      >
      <el-tab-pane label="实验材料" name="materials"
        ><div class="design-section-head">
          <div>
            <h3>本次实验材料</h3>
            <p>下列为每份材料实际使用的参数</p>
          </div>
          <el-button v-if="editable" type="primary" plain @click="openAdd">添加材料</el-button>
        </div>
        <div v-for="(entry, index) in config.materials" :key="entry.id" class="detail-material-row">
          <span class="wizard-order">{{ index + 1 }}</span>
          <div class="grow">
            <b>{{ entry.taxon_name }}</b
            ><small>{{ entry.seed_lot_code }} {{ entry.label || '' }}</small>
          </div>
          <div class="material-metrics">
            <span
              >每皿 <b>{{ entry.effective_seeds_per_dish }}</b> 粒</span
            ><span
              >重复 <b>{{ entry.effective_replicate_count }}</b> 次</span
            ><span
              >取样 <b>{{ entry.effective_sample_count }}</b> 株</span
            >
          </div>
          <div v-if="editable" class="material-actions">
            <el-button link :disabled="index === 0" @click="moveMaterial(index, -1)">上移</el-button
            ><el-button
              link
              :disabled="index === config.materials.length - 1"
              @click="moveMaterial(index, 1)"
              >下移</el-button
            ><el-button link @click="editMaterial(entry)">参数</el-button
            ><el-button link type="danger" @click="removeMaterial(entry)">移除</el-button>
          </div>
        </div>
        <div v-if="!config.materials.length" class="wizard-empty">
          尚未加入实验材料。请先添加种子批次，再标记为已就绪。
        </div></el-tab-pane
      >
      <el-tab-pane label="发芽后测定时间（DAG）" name="dag"
        ><div class="design-section-head">
          <div>
            <h3>发芽后测定时间点</h3>
            <p>以每株幼苗实际发芽时间为起点，设置发芽后第几天测定</p>
          </div>
          <el-button v-if="editable" @click="editDag">编辑 DAG</el-button>
        </div>
        <div class="dag-chips">
          <el-tag v-for="day in config.dag_days" :key="day" size="large">DAG {{ day }}</el-tag
          ><span v-if="!config.dag_days.length">尚未设置</span>
        </div></el-tab-pane
      >
      <el-tab-pane label="工作量估算" name="workload"
        ><div class="design-section-head">
          <div>
            <h3>设计工作量</h3>
            <p>根据材料数量、实际使用参数和测定次数估算</p>
          </div>
        </div>
        <div v-if="config.workload" class="review-grid">
          <div>
            <small>材料数</small><strong>{{ config.workload.material_count }}</strong>
          </div>
          <div>
            <small>培养皿数</small><strong>{{ config.workload.estimated_dish_count }}</strong>
          </div>
          <div>
            <small>置床种子</small><strong>{{ config.workload.estimated_seed_count }}</strong>
          </div>
          <div>
            <small>幼苗样本</small><strong>{{ config.workload.estimated_sample_count }}</strong>
          </div>
          <div>
            <small>测定记录</small
            ><strong>{{ config.workload.estimated_measurement_count }}</strong>
          </div>
          <div>
            <small>预计最晚完成</small
            ><strong class="date">{{
              config.workload.estimated_latest_finish_date || '未设置计划日期'
            }}</strong>
          </div>
        </div>
        <div v-else class="wizard-empty">请先填写实验方案并添加材料，再查看预计工作量。</div></el-tab-pane
      >
    </el-tabs>
  </div>
  <el-dialog v-model="infoOpen" title="编辑实验信息" width="560px"
    ><el-form label-position="top"
      ><el-form-item label="实验名称"><el-input v-model="info.name" /></el-form-item
      ><el-form-item label="实验说明"
        ><el-input v-model="info.description" type="textarea" :rows="3" /></el-form-item
      ><el-form-item label="计划开始日期"
        ><el-date-picker
          v-model="info.planned_start_date"
          type="date"
          value-format="YYYY-MM-DD" /></el-form-item
      ></el-form
    ><template #footer
      ><el-button @click="infoOpen = false">取消</el-button
      ><el-button type="primary" @click="saveInfo">保存实验信息</el-button></template
    ></el-dialog
  >
  <el-dialog v-model="protocolOpen" title="编辑默认方案" width="650px"
    ><el-form label-position="top"
      ><div class="wizard-form-grid">
        <el-form-item label="每皿种子数"
          ><el-input-number v-model="protocol.seeds_per_dish" :min="1" /></el-form-item
        ><el-form-item label="重复数"
          ><el-input-number v-model="protocol.replicate_count" :min="1" /></el-form-item
        ><el-form-item label="观察周期（天）"
          ><el-input-number v-model="protocol.observation_period_days" :min="1" /></el-form-item
        ><el-form-item label="取样数 N"
          ><el-input-number v-model="protocol.sample_count" :min="1"
        /></el-form-item>
      </div>
      <el-form-item label="取样范围"
        ><el-radio-group v-model="protocol.sample_scope"
          ><el-radio value="per_dish">每个培养皿取 N 株</el-radio
          ><el-radio value="per_material">每个实验材料合计取 N 株</el-radio></el-radio-group
        ></el-form-item
      ><el-form-item label="发芽判定标准"
        ><el-input v-model="protocol.germination_criterion" /></el-form-item
      ><el-form-item label="方案备注"
        ><el-input v-model="protocol.summary" type="textarea" :rows="3" /></el-form-item></el-form
    ><template #footer
      ><el-button @click="protocolOpen = false">取消</el-button
      ><el-button type="primary" @click="saveProtocol">保存</el-button></template
    ></el-dialog
  >
  <el-dialog v-model="materialOpen" title="材料特殊参数" width="620px"
    ><p class="wizard-help">留空表示继承默认方案。</p>
    <el-form label-position="top"
      ><div class="wizard-form-grid">
        <el-form-item label="每皿种子数"
          ><el-input-number v-model="material.seeds_per_dish_override" :min="1" /></el-form-item
        ><el-form-item label="重复数"
          ><el-input-number v-model="material.replicate_count_override" :min="1" /></el-form-item
        ><el-form-item label="取样数"
          ><el-input-number v-model="material.sample_count_override" :min="1"
        /></el-form-item>
      </div>
      <el-form-item label="本次实验材料标签"
        ><el-input v-model="material.label" /></el-form-item></el-form
    ><template #footer
      ><el-button @click="materialOpen = false">取消</el-button
      ><el-button type="primary" @click="saveMaterial">保存</el-button></template
    ></el-dialog
  >
  <el-dialog v-model="addOpen" title="添加实验材料" width="620px"
    ><div class="wizard-search-row">
      <el-input v-model="search" placeholder="搜索物种或批次" @keyup.enter="searchLots" /><el-button
        @click="searchLots"
        >搜索</el-button
      >
    </div>
    <el-select v-model="selectedLot" filterable placeholder="选择可用种子批次" style="width: 100%"
      ><el-option
        v-for="lot in available"
        :key="lot.id"
        :label="`${lot.taxon_name} · ${lot.code}`"
        :value="lot.id" /></el-select
    ><template #footer
      ><el-button @click="addOpen = false">取消</el-button
      ><el-button type="primary" @click="addMaterial">加入实验材料</el-button></template
    ></el-dialog
  >
  <el-dialog v-model="dagOpen" title="编辑 DAG 测定时间点" width="540px"
    ><p class="wizard-help">填写幼苗发芽后第几天测定；用逗号或空格分隔多个天数。</p>
    <el-input v-model="dagText" placeholder="例如 1, 3, 5, 7" /><template #footer
      ><el-button @click="dagOpen = false">取消</el-button
      ><el-button type="primary" @click="saveDag">保存</el-button></template
    ></el-dialog
  >
  <StartExperimentDialog
    v-if="config"
    v-model="startOpen"
    :experiment-id="config.experiment.id"
    :workload="config.workload"
    @started="router.push(`/experiments/${config.experiment.id}/germination`)"
  />
</template>
