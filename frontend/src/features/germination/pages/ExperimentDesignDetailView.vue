<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api, errorMessage } from '../../../shared/api/client'
import type { AvailableLot, ExperimentConfiguration, ExperimentMaterial, ExperimentProtocol } from '../index'
import { dateText, statusLabels } from '../../../shared/format'
import PageBackButton from '../../../shared/components/PageBackButton.vue'
import { useClientPagination } from '../../../shared/composables/useClientPagination'
import { defaultExperimentProtocol } from '../utils/experimentProtocol'

const route = useRoute()
const router = useRouter()
const config = ref<ExperimentConfiguration | null>(null)
const materialList = computed(() => config.value?.materials || [])
const {
  page: materialPage,
  pageSize: materialPageSize,
  pageItems: visibleMaterials,
} = useClientPagination(materialList)
const item = computed(() => config.value?.experiment)
const editable = computed(() => item.value?.status === 'draft')
const canEditInfo = computed(() => item.value?.status === 'draft' || item.value?.status === 'ready')
const activeTab = ref('overview')
const infoOpen = ref(false)
const protocolOpen = ref(false)
const materialOpen = ref(false)
const addOpen = ref(false)
const dagOpen = ref(false)
const info = reactive({
  name: '',
  description: '',
  planned_start_date: '',
})
const protocol = reactive<ExperimentProtocol>(defaultExperimentProtocol())
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
        ? '标记后仍可返回草稿修改；确认置床编号后须先解除确认才能修改材料、重复数和测定时间。'
        : '返回草稿后可继续调整材料、方案和测定时间；调整完成后需要再次标记为已就绪。',
      preparing ? '确定将实验标记为“已就绪”吗？' : '确定将实验返回草稿吗？',
      { confirmButtonText: preparing ? '标记为已就绪' : '返回草稿', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  await run(
    () => api.patch(base.value, { status: target }),
    preparing ? '实验已标记为已就绪' : '实验已返回草稿',
  )
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
async function confirmNumbers() {
  try {
    await ElMessageBox.confirm(
      '系统将先按中文名排序，再为材料和培养皿生成正式现场编号。请核对置床清单后确认。',
      '确认置床编号',
      { confirmButtonText: '确认置床编号', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  await run(() => api.post(`${base.value}/confirm-numbers`), '置床编号已确认')
}
async function reopenDesign() {
  try {
    await ElMessageBox.confirm(
      '解除编号确认后，当前001、002……编号方案将失效。调整完成后需要重新确认并重新打印置床清单。',
      '重新调整实验',
      { confirmButtonText: '重新调整实验', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  await run(() => api.post(`${base.value}/reopen-design`), '已返回可调整状态')
}
async function downloadSowingSheet() {
  try {
    const { data } = await api.get<Blob>(`${base.value}/sowing-sheet.xlsx`, {
      responseType: 'blob',
    })
    const url = URL.createObjectURL(data)
    const link = document.createElement('a')
    link.href = url
    link.download = 'seedlab-sowing-sheet.xlsx'
    link.click()
    URL.revokeObjectURL(url)
  } catch (error) {
    ElMessage.error(errorMessage(error))
  }
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
async function deleteExperiment() {
  try {
    await ElMessageBox.confirm(
      '永久删除会移除实验方案、材料、测定时间和未置床计划培养皿，无法恢复。已有真实置床或观测数据时不能删除。',
      '永久删除实验',
      { confirmButtonText: '永久删除', cancelButtonText: '保留实验', type: 'warning' },
    )
    await api.delete(base.value)
    ElMessage.success('实验已删除')
    await router.push('/experiments')
  } catch (error) {
    if (error !== 'cancel' && error !== 'close') ElMessage.error(errorMessage(error))
  }
}
async function completeExperiment() {
  try {
    const { data } = await api.get<{
      can_complete: boolean
      pending_dish_count: number
      observing_dish_count: number
      measurement_pending_count: number
    }>(`${base.value}/completion-check`)
    if (!data.can_complete) {
      await ElMessageBox.alert(
        `待置床 ${data.pending_dish_count} 个、幼苗测定待办 ${data.measurement_pending_count} 项。请先处理待置床培养皿并完成已有幼苗测定，再确认完成实验。`,
        '暂不能完成实验',
        { confirmButtonText: '继续实验' },
      )
      return
    }
    await ElMessageBox.confirm(
      '请确认本实验已正常完成。确认后不能新增巡检和测定，仍可复核修改已测值。',
      '完成实验',
      {
        confirmButtonText: '确认完成',
        cancelButtonText: '继续实验',
      },
    )
    await run(() => api.post(`${base.value}/complete`), '实验已完成')
  } catch (error) {
    if (error !== 'cancel' && error !== 'close') ElMessage.error(errorMessage(error))
  }
}
async function terminateExperiment() {
  try {
    const { value } = await ElMessageBox.prompt(
      '终止后保留全部实验数据，所有执行页面改为只读，不能恢复执行。请填写终止原因。',
      '终止实验',
      {
        confirmButtonText: '确认终止实验',
        cancelButtonText: '继续实验',
        inputValidator: (value) => !!value.trim() || '请填写终止原因',
        type: 'warning',
      },
    )
    await run(
      () => api.post(`${base.value}/terminate`, { reason: value }),
      '实验已终止，历史数据保留',
    )
  } catch (error) {
    if (error !== 'cancel' && error !== 'close') ElMessage.error(errorMessage(error))
  }
}
function moreAction(command: string) {
  if (command === 'delete') void deleteExperiment()
  if (command === 'draft') void changeStatus('draft')
  if (command === 'reopen') void reopenDesign()
  if (command === 'info') editInfo()
  if (command === 'complete') void completeExperiment()
  if (command === 'terminate') void terminateExperiment()
}
onMounted(load)
</script>

<template>
  <PageBackButton to="/experiments" label="返回实验列表" />
  <div v-if="item" class="page-heading detail-heading">
    <div>
      <div class="eyebrow">
        实验类型：{{ item.experiment_type_label }} · 实验编号 {{ item.code }}
      </div>
      <h1>{{ item.name }}</h1>
      <p>
        核对材料和方案，确认置床编号后可分批登记实际置床时间。计划开始
        {{ dateText(item.planned_start_date) }}
      </p>
    </div>
    <div class="heading-actions">
      <span class="experiment-current-status"
        >当前状态：<span class="status-pill large" :class="item.status">{{
          statusLabels[item.status]
        }}</span></span
      >
      <el-button v-if="item.status === 'draft'" type="primary" @click="changeStatus('ready')"
        >标记为已就绪</el-button
      >
      <el-button
        v-else-if="item.status === 'ready' && !item.numbering_locked_at"
        type="primary"
        @click="confirmNumbers"
        >确认置床编号</el-button
      >
      <el-button
        v-else
        type="primary"
        @click="router.push(`/experiments/${item.id}/germination`)"
        >{{
          item.status === 'active'
            ? '继续实验'
            : item.status === 'ready'
              ? '进入实验'
              : '查看实验数据'
        }}</el-button
      >
      <el-dropdown v-if="['draft', 'ready', 'active'].includes(item.status)" @command="moreAction"
        ><el-button>更多操作</el-button
        ><template #dropdown
          ><el-dropdown-menu>
            <el-dropdown-item v-if="canEditInfo" command="info">编辑实验信息</el-dropdown-item>
            <el-dropdown-item
              v-if="item.status === 'ready' && !item.numbering_locked_at"
              command="draft"
              >返回草稿</el-dropdown-item
            >
            <el-dropdown-item
              v-if="item.status === 'ready' && item.numbering_locked_at"
              command="reopen"
              >返回草稿并重新调整编号</el-dropdown-item
            >
            <el-dropdown-item v-if="['draft', 'ready'].includes(item.status)" command="delete"
              >永久删除实验</el-dropdown-item
            >
            <el-dropdown-item v-if="item.status === 'active'" command="complete"
              >完成实验</el-dropdown-item
            >
            <el-dropdown-item v-if="item.status === 'active'" command="terminate"
              >终止实验</el-dropdown-item
            >
          </el-dropdown-menu></template
        ></el-dropdown
      >
    </div>
  </div>
  <p v-if="item" class="experiment-flow-hint">
    {{
      item.status === 'draft'
        ? '确认材料、方案和发芽后测定时间（DAG）后，可标记为已就绪。'
        : item.status === 'ready'
          ? item.numbering_locked_at
            ? '置床编号已确认。可下载清单并分批置床；尚未置床时可以重新调整实验。'
            : '方案已就绪。请先预览置床清单，再确认置床编号。'
          : item.status === 'active'
            ? '实验正在执行，进入发芽巡检页面记录数据。'
            : '该实验目前不再接受材料和测定方案修改。'
    }}
  </p>
  <p v-if="item?.termination_reason" class="execution-alert">
    终止原因：{{ item.termination_reason }}
  </p>
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
            <dt>计划发芽观察天数</dt>
            <dd>
              {{
                config.protocol.observation_period_days === null
                  ? '未设置'
                  : `${config.protocol.observation_period_days} 天`
              }}
            </dd>
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
        <div v-for="entry in visibleMaterials" :key="entry.id" class="detail-material-row">
          <span class="experiment-number-badge">{{
            entry.experiment_number
              ? String(entry.experiment_number).padStart(3, '0')
              : `预计 ${String(entry.preview_number).padStart(3, '0')}`
          }}</span>
          <div class="grow">
            <b>{{ entry.taxon_common_name || entry.taxon_scientific_name }}</b>
            <small v-if="entry.taxon_common_name">{{ entry.taxon_scientific_name }}</small>
            <small
              >原始材料编号：{{ entry.source_code || '未填写' }} · {{ entry.seed_lot_code }}
              {{ entry.label || '' }}</small
            >
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
            <el-button link @click="editMaterial(entry)">参数</el-button
            ><el-button link type="danger" @click="removeMaterial(entry)">移除</el-button>
          </div>
        </div>
        <el-pagination
          v-if="config.materials.length"
          v-model:current-page="materialPage"
          v-model:page-size="materialPageSize"
          class="list-pagination"
          :page-sizes="[25, 50, 100]"
          layout="total, sizes, prev, pager, next"
          :total="config.materials.length"
        />
        <div v-if="!config.materials.length" class="wizard-empty">
          尚未加入实验材料。请先添加种子批次，再标记为已就绪。
        </div></el-tab-pane
      >
      <el-tab-pane label="置床清单" name="sowing">
        <div class="design-section-head">
          <div>
            <h3>置床清单</h3>
            <p>先按中文名排序，再编号。确认后可下载正式清单，现场编号不会因后续置床顺序改变。</p>
          </div>
          <el-button v-if="item?.numbering_locked_at" @click="downloadSowingSheet"
            >下载 Excel</el-button
          >
        </div>
        <el-table :data="config.materials" max-height="560">
          <el-table-column label="材料编号" width="100"
            ><template #default="{ row }"
              ><span class="experiment-number-badge">{{
                row.experiment_number
                  ? String(row.experiment_number).padStart(3, '0')
                  : `预计 ${String(row.preview_number).padStart(3, '0')}`
              }}</span></template
            ></el-table-column
          >
          <el-table-column label="物种" min-width="180"
            ><template #default="{ row }"
              ><div class="sowing-name">
                <b>{{ row.taxon_common_name || row.taxon_scientific_name }}</b
                ><small v-if="row.taxon_common_name"
                  ><i>{{ row.taxon_scientific_name }}</i></small
                >
              </div></template
            ></el-table-column
          >
          <el-table-column label="原始材料编号" width="120"
            ><template #default="{ row }">{{
              row.source_code || '未填写'
            }}</template></el-table-column
          >
          <el-table-column prop="seed_lot_code" label="系统批次编号" width="145" />
          <el-table-column label="来源" min-width="130"
            ><template #default="{ row }"
              ><span class="sowing-source">{{ row.source || '未填写' }}</span></template
            ></el-table-column
          >
          <el-table-column label="采集/获得日期" width="140"
            ><template #default="{ row }">{{
              row.collected_at?.slice(0, 10) || '未填写'
            }}</template></el-table-column
          >
          <el-table-column prop="effective_replicate_count" label="重复数" width="80" />
          <el-table-column prop="effective_seeds_per_dish" label="每皿种子数" width="105" />
        </el-table>
      </el-tab-pane>
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
        </div>
        <div v-else class="wizard-empty">
          请先填写实验方案并添加材料，再查看预计工作量。
        </div></el-tab-pane
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
          value-format="YYYY-MM-DD" /></el-form-item></el-form
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
        ><el-form-item label="计划发芽观察天数（可选）"
          ><el-input-number
            v-model="protocol.observation_period_days"
            :min="1"
            :precision="0"
            @change="protocol.observation_period_days = $event ?? null"
          />
          <p class="wizard-help">
            仅用于预计日期和超期提醒，不会自动结束观察；不确定时可留空。
          </p></el-form-item
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
      <el-input
        v-model="search"
        placeholder="搜索中文名、学名、物种编号或批次"
        @keyup.enter="searchLots"
      /><el-button @click="searchLots">搜索</el-button>
    </div>
    <el-select v-model="selectedLot" filterable placeholder="选择可用种子批次" style="width: 100%"
      ><el-option
        v-for="lot in available"
        :key="lot.id"
        class="taxon-select-option"
        :label="`${lot.taxon_common_name || lot.taxon_scientific_name} · ${lot.code}`"
        :value="lot.id"
      >
        <div class="taxon-option">
          <b>{{ lot.taxon_common_name || lot.taxon_scientific_name }}</b>
          <small>{{
            lot.taxon_common_name ? `${lot.taxon_scientific_name} · ${lot.code}` : lot.code
          }}</small>
        </div>
      </el-option></el-select
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
</template>
