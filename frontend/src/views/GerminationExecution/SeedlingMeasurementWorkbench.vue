<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { onBeforeRouteLeave, useRoute } from 'vue-router'
import { api, errorMessage } from '../../api/client'
import type { MeasurementHistory, MeasurementTask, MeasurementTasks } from '../../types'
import { dateTimeText } from '../../utils'
import { historyValue, isResolved, measurementStatusLabels } from '../../utils/measurement'

const route = useRoute()
const base = computed(() => `/experiments/${route.params.id}`)
const data = ref<MeasurementTasks | null>(null)
const history = ref<MeasurementHistory | null>(null)
const filter = ref('pending')
const dag = ref<number | null>(null)
const search = ref('')
const selected = ref<MeasurementTask | null>(null)
const editing = ref(false)
const busy = ref(false)
const rootInput = ref<{ focus: () => void } | null>(null)
const shootInput = ref<{ focus: () => void } | null>(null)
const form = ref({ root: '', shoot: '', rootNA: false, shootNA: false, notes: '', measuredAt: '' })
const initial = ref('')

function localInput(value: string | null): string {
  const date = value ? new Date(value) : new Date()
  const pad = (number: number) => String(number).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`
}
function resetForm(task: MeasurementTask | null) {
  form.value = { root: task?.root_length_mm == null ? '' : String(task.root_length_mm),
    shoot: task?.shoot_length_mm == null ? '' : String(task.shoot_length_mm),
    rootNA: task?.root_unavailable || false, shootNA: task?.shoot_unavailable || false,
    notes: task?.notes || '', measuredAt: localInput(task?.measured_at || null) }
  initial.value = JSON.stringify(form.value)
  editing.value = !!task?.measurement_id
}
const dirty = computed(() => selected.value !== null && JSON.stringify(form.value) !== initial.value)
async function confirmDiscard(): Promise<boolean> {
  if (!dirty.value) return true
  try {
    await ElMessageBox.confirm('当前测定值尚未保存，是否放弃？', '放弃未保存的测定值', {
      confirmButtonText: '放弃修改', cancelButtonText: '继续填写', type: 'warning',
    })
    return true
  } catch { return false }
}
defineExpose({ confirmDiscard })
onBeforeRouteLeave(async () => await confirmDiscard())
function beforeUnload(event: BeforeUnloadEvent) { if (dirty.value) { event.preventDefault(); event.returnValue = '' } }
onMounted(() => { window.addEventListener('beforeunload', beforeUnload); void load() })
onUnmounted(() => window.removeEventListener('beforeunload', beforeUnload))

const filtered = computed(() => (data.value?.tasks || []).filter(task => {
  if (filter.value === 'pending' && !['overdue', 'due_today'].includes(task.status)) return false
  if (filter.value !== 'pending' && filter.value !== 'all' && task.status !== filter.value) return false
  if (dag.value !== null && task.day_after_germination !== dag.value) return false
  const term = search.value.trim().toLocaleLowerCase()
  if (!term) return true
  return [task.experiment_number, task.field_number, task.dish_code, task.sample_number,
    task.position_label, task.taxon_common_name, task.taxon_scientific_name, task.taxon_code,
    task.seed_lot_code, task.source_code].some(value => String(value ?? '').toLocaleLowerCase().includes(term))
}))
async function load(preferred?: { sample_id: string; timepoint_id: string }) {
  try {
    data.value = (await api.get<MeasurementTasks>(`${base.value}/measurement-tasks`)).data
    if (preferred) {
      const current = data.value.tasks.find(task => task.sample_id === preferred.sample_id && task.timepoint_id === preferred.timepoint_id)
      selected.value = current || null
      resetForm(selected.value)
    }
    if (selected.value) await loadHistory(selected.value.material_id)
  } catch (error) { ElMessage.error(errorMessage(error)) }
}
async function loadHistory(materialId: string) {
  try { history.value = (await api.get<MeasurementHistory>(`${base.value}/measurement-history/${materialId}`)).data }
  catch (error) { ElMessage.error(errorMessage(error)) }
}
async function choose(task: MeasurementTask) {
  if (selected.value?.sample_id === task.sample_id && selected.value.timepoint_id === task.timepoint_id) return
  if (!await confirmDiscard()) return
  selected.value = task
  resetForm(task)
  await loadHistory(task.material_id)
}
async function changeFilter(value: string) {
  if (!await confirmDiscard()) return
  filter.value = value
  selected.value = null; history.value = null
}
async function changeDag(value: number | null) {
  if (!await confirmDiscard()) return
  dag.value = value
  selected.value = null; history.value = null
}
async function changeSearch(value: string) {
  if (!await confirmDiscard()) return
  search.value = value
  selected.value = null; history.value = null
}
function inputPayload(task: MeasurementTask) {
  if (!isResolved(form.value.root, form.value.rootNA) || !isResolved(form.value.shoot, form.value.shootNA)) {
    throw new Error('根长和苗长都需要填写非负数值，或勾选“无法测量”；空白不能当作 0。')
  }
  const date = new Date(form.value.measuredAt)
  if (Number.isNaN(date.getTime())) throw new Error('请填写有效的实际测定时间。')
  return { sample_id: task.sample_id, timepoint_id: task.timepoint_id,
    root_length_mm: form.value.rootNA ? null : Number(form.value.root),
    shoot_length_mm: form.value.shootNA ? null : Number(form.value.shoot),
    root_unavailable: form.value.rootNA, shoot_unavailable: form.value.shootNA,
    measured_at: date.toISOString(), notes: form.value.notes.trim() || null }
}
async function save(next: boolean) {
  const task = selected.value
  if (!task || busy.value) return
  try {
    const payload = inputPayload(task)
    busy.value = true
    const nextTasks = filtered.value.filter(row => !row.measurement_id)
    const index = nextTasks.findIndex(row => row.sample_id === task.sample_id && row.timepoint_id === task.timepoint_id)
    const nextTask = nextTasks[index + 1] || nextTasks.find(row => row.sample_id !== task.sample_id || row.timepoint_id !== task.timepoint_id)
    if (task.measurement_id) await api.patch(`${base.value}/measurements/${task.measurement_id}`, payload)
    else await api.post(`${base.value}/measurements`, payload)
    ElMessage({ message: task.measurement_id ? '测定记录已更新' : '测定已保存', type: 'success', duration: 900 })
    await load()
    const pick = next && nextTask ? data.value?.tasks.find(row => row.sample_id === nextTask.sample_id && row.timepoint_id === nextTask.timepoint_id) :
      data.value?.tasks.find(row => row.sample_id === task.sample_id && row.timepoint_id === task.timepoint_id)
    selected.value = pick || null
    resetForm(selected.value)
    if (selected.value) await loadHistory(selected.value.material_id)
  } catch (error) { ElMessage.error(error instanceof Error && !(error as { response?: unknown }).response ? error.message : errorMessage(error)) }
  finally { busy.value = false }
}
async function clearMeasurement() {
  const task = selected.value
  if (!task?.measurement_id) return
  try {
    await ElMessageBox.confirm(`清除后，该幼苗的 DAG ${task.day_after_germination} 将恢复为待测状态。`,
      '清除本阶段测定', { confirmButtonText: '确认清除', cancelButtonText: '保留记录', type: 'warning' })
    await api.delete(`${base.value}/measurements/${task.measurement_id}`)
    ElMessage.success('本阶段测定已清除')
    await load({ sample_id: task.sample_id, timepoint_id: task.timepoint_id })
  } catch (error) { if ((error as string) !== 'cancel') ElMessage.error(errorMessage(error)) }
}
async function savePosition(value: string) {
  const task = selected.value
  if (!task) return
  try {
    await api.patch(`${base.value}/samples/${task.sample_id}/position`, { position_label: value.trim() || null })
    ElMessage.success('幼苗位置已保存')
    task.position_label = value.trim() || null
    const row = history.value?.samples.find(item => item.sample_id === task.sample_id)
    if (row) row.position_label = task.position_label
  } catch (error) { ElMessage.error(errorMessage(error)) }
}
async function rootEnter() { shootInput.value?.focus() }
async function shootEnter() { await save(true) }
</script>

<template>
  <p class="wizard-help">按发芽判定日期安排幼苗根长、苗长测定。发芽后测定时间（DAG）以本地自然日计算；空白、实测 0 和无法测量分别记录。</p>
  <div v-if="data" class="measurement-workbench">
    <div class="execution-overview-stats measurement-stats">
      <div><small>今日待测</small><strong>{{ data.summary.due_today_count }}</strong></div>
      <div><small>已逾期</small><strong>{{ data.summary.overdue_count }}</strong></div>
      <div><small>今日完成</small><strong>{{ data.summary.completed_today_count }}</strong></div>
      <div><small>后续任务</small><strong>{{ data.summary.upcoming_count }}</strong></div>
    </div>
    <div v-if="data.summary.unschedulable_count" class="execution-alert">有 {{ data.summary.unschedulable_count }} 项测定缺少发芽判定时间，暂时无法安排。请核对历史样本。</div>
    <div class="measurement-toolbar">
      <el-select :model-value="filter" aria-label="筛选测定任务" @change="changeFilter"><el-option label="当前待处理" value="pending" /><el-option label="今日待测" value="due_today" /><el-option label="已逾期" value="overdue" /><el-option label="后续任务" value="upcoming" /><el-option label="已完成" value="completed" /><el-option label="无法安排" value="unschedulable" /><el-option label="全部" value="all" /></el-select>
      <el-select :model-value="dag" aria-label="筛选发芽后测定时间" @change="changeDag"><el-option label="全部测定时间" :value="null" /><el-option v-for="day in data.dag_days" :key="day" :label="`发芽后第 ${day} 天`" :value="day" /></el-select>
      <el-input :model-value="search" placeholder="搜索编号、中文名、学名、培养皿或幼苗" clearable @change="changeSearch" />
    </div>
    <div class="measurement-layout">
      <div class="measurement-queue">
        <h3>测定任务 <small>共 {{ filtered.length }} 项</small></h3>
        <button v-for="task in filtered" :key="`${task.sample_id}:${task.timepoint_id}`" type="button" class="measurement-task" :class="{ selected: selected?.sample_id === task.sample_id && selected?.timepoint_id === task.timepoint_id }" @click="choose(task)">
          <b>{{ task.field_number }} · 幼苗 {{ String(task.sample_number).padStart(2, '0') }}</b>
          <span>{{ task.taxon_common_name || task.taxon_scientific_name }}</span>
          <small>发芽后第 {{ task.day_after_germination }} 天 · {{ task.scheduled_date || '缺少发芽时间' }} · {{ measurementStatusLabels[task.status] }}</small>
        </button>
        <div v-if="!filtered.length" class="wizard-empty">当前没有符合条件的测定任务。可调整筛选条件，或先完成发芽巡检。</div>
      </div>
      <div class="measurement-detail">
        <template v-if="selected">
          <h3>{{ editing ? '修改本阶段测定' : '记录幼苗测定' }}</h3>
          <p><b>{{ selected.field_number }} · 幼苗 {{ String(selected.sample_number).padStart(2, '0') }}</b> · {{ selected.taxon_common_name || selected.taxon_scientific_name }} <small>{{ selected.taxon_common_name ? selected.taxon_scientific_name : '' }}</small></p>
          <p>发芽判定：{{ dateTimeText(selected.germinated_at) }} · 发芽后第 {{ selected.day_after_germination }} 天 · 计划：{{ selected.scheduled_date || '无法安排' }}</p>
          <div class="measurement-form">
            <label>根长（mm）<el-input ref="rootInput" v-model="form.root" :disabled="form.rootNA || selected.status === 'unschedulable'" placeholder="填写实测值，0 表示真实零值" @keydown.enter.prevent="rootEnter" /></label>
            <el-checkbox v-model="form.rootNA" :disabled="selected.status === 'unschedulable'" @change="form.root = ''">无法测量</el-checkbox>
            <label>苗长（mm）<el-input ref="shootInput" v-model="form.shoot" :disabled="form.shootNA || selected.status === 'unschedulable'" placeholder="填写实测值，0 表示真实零值" @keydown.enter.prevent="shootEnter" /></label>
            <el-checkbox v-model="form.shootNA" :disabled="selected.status === 'unschedulable'" @change="form.shoot = ''">无法测量</el-checkbox>
            <label>实际测定时间<input v-model="form.measuredAt" type="datetime-local" :disabled="selected.status === 'unschedulable'" /></label>
            <label>备注<el-input v-model="form.notes" type="textarea" :rows="2" placeholder="可记录测量时的情况" /></label>
          </div>
          <div class="measurement-actions">
            <el-button type="primary" :loading="busy" :disabled="selected.status === 'unschedulable' || (data.experiment_status !== 'active' && !(editing && data.experiment_status === 'completed'))" @click="save(true)">{{ editing ? '保存修改并下一株' : '保存并下一株' }}</el-button>
            <el-button v-if="editing" @click="resetForm(selected)">取消修改</el-button>
            <el-button v-if="editing && data.experiment_status === 'active'" type="danger" plain @click="clearMeasurement">清除本阶段测定</el-button>
          </div>
          <div class="measurement-position"><label>幼苗位置标签</label><el-input :model-value="selected.position_label || ''" placeholder="例如 A1、托盘2-15；可留空" maxlength="80" @change="savePosition" /></div>
        </template>
        <div v-else class="wizard-empty">从左侧选择一项测定任务，开始填写根长和苗长。</div>
      </div>
    </div>
    <section v-if="history && selected" class="measurement-history"><h3>当前材料测定历史</h3><p>点击已测的阶段可同时修改根长、苗长、测定时间和备注。— 表示尚未测定，NA 表示无法测量。</p>
      <div class="measurement-table-scroll"><table><thead><tr><th>培养皿 / 幼苗</th><th>发芽判定时间</th><th v-for="day in history.dag_days" :key="day" :class="{ current: day === selected.day_after_germination }">DAG {{ day }} · 根长 / 苗长（mm）</th></tr></thead><tbody><tr v-for="sample in history.samples" :key="sample.sample_id" :class="{ current: sample.sample_id === selected.sample_id }"><td>{{ sample.field_number }} · {{ String(sample.sample_number).padStart(2, '0') }}<small v-if="sample.position_label"> · {{ sample.position_label }}</small></td><td>{{ dateTimeText(sample.germinated_at) }}</td><td v-for="day in history.dag_days" :key="day" :class="{ current: day === selected.day_after_germination }"><button v-if="sample.measurements[String(day)]?.measurement_id" type="button" class="measurement-history-link" @click="choose(sample.measurements[String(day)])">{{ historyValue(sample.measurements[String(day)]) }} · 修改</button><span v-else>{{ historyValue(sample.measurements[String(day)]) }}</span></td></tr></tbody></table></div>
    </section>
  </div>
  <div v-else class="wizard-empty">正在加载幼苗测定任务…</div>
</template>
