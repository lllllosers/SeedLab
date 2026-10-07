<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { onBeforeRouteLeave, useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { api, errorMessage } from '../../../shared/api/client'
import type { MeasurementMaterial, MeasurementTask, MeasurementTasks, MeasurementWorklist } from '../index'
import {
  measurementStatusLabels,
  measurementValue,
  nextPendingTask,
  materialProgressTasks,
} from '../utils/measurement'
import { normalizedDag } from '../utils/measurementQuery'
import MeasurementEditor from './MeasurementEditor.vue'
import MeasurementRecords from './MeasurementRecords.vue'
import MeasurementRecordsTable from './MeasurementRecordsTable.vue'
import MeasurementEditDialog from './MeasurementEditDialog.vue'
const route = useRoute(),
  base = computed(() => `/experiments/${route.params.id}`)
const historyOpen = ref(false)
const tab = ref('worklist'),
  search = ref(''),
  status = ref('pending'),
  dag = ref<number | null>(null)
const page = ref(1),
  pageSize = ref(25),
  data = ref<MeasurementWorklist | null>(null)
const current = ref<MeasurementMaterial | null>(null),
  tasks = ref<MeasurementTask[]>([]),
  selected = ref<MeasurementTask | null>(null),
  editing = ref<MeasurementTask | null>(null)
const editor = ref<InstanceType<typeof MeasurementEditor> | null>(null),
  dialog = ref<InstanceType<typeof MeasurementEditDialog> | null>(null),
  records = ref<InstanceType<typeof MeasurementRecords> | null>(null)
const pending = computed(() =>
  tasks.value.filter(
    (t) => !t.measurement_id && (dag.value === null || t.day_after_germination === dag.value),
  ),
)
const measured = computed(() => tasks.value.filter((t) => !!t.measurement_id))
const progressTasks = computed(() => materialProgressTasks(tasks.value))
const reference = computed(() =>
  measured.value.filter((t) => t.day_after_germination === selected.value?.day_after_germination),
)
function taskRowClass({ row }: { row: MeasurementTask }) {
  return row.sample_id === selected.value?.sample_id &&
    row.timepoint_id === selected.value?.timepoint_id
    ? 'measurement-current-row'
    : ''
}
const due = computed(() => tasks.value.filter((t) => t.status === 'due_today').length),
  overdue = computed(() => tasks.value.filter((t) => t.status === 'overdue').length)
let sequence = 0
async function load() {
  const request = ++sequence,
    params = new URLSearchParams({
      status: status.value,
      q: search.value,
      page: String(page.value),
      page_size: String(pageSize.value),
    })
  if (dag.value !== null) params.set('dag', String(dag.value))
  try {
    const result = (
      await api.get<MeasurementWorklist>(`${base.value}/measurement-worklist?${params}`)
    ).data
    if (request === sequence) data.value = result
  } catch (error) {
    ElMessage.error(errorMessage(error))
  }
}
// Searching only refreshes the material list; it never touches the active editor.
watch([search, pageSize], () => {
  if (page.value !== 1) page.value = 1
  else void load()
})
watch(page, () => void load())
async function loadTasks() {
  const id = current.value?.material_id
  if (!id) return
  const result = (
    await api.get<MeasurementTasks>(`${base.value}/measurement-tasks?material_id=${id}`)
  ).data
  if (current.value?.material_id === id) tasks.value = result.tasks
}
async function confirmDiscard() {
  return (
    (!editor.value || (await editor.value.confirmDiscard())) &&
    (!dialog.value || (await dialog.value.confirmDiscard())) &&
    (!records.value || (await records.value.confirmDiscard()))
  )
}
defineExpose({ confirmDiscard })
async function chooseMaterial(material: MeasurementMaterial, automatic = false) {
  if (!automatic && !(await confirmDiscard())) return
  try {
    historyOpen.value = false
    current.value = material
    await loadTasks()
    if (current.value?.material_id !== material.material_id) return
    selected.value = nextPendingTask(tasks.value, dag.value) || pending.value[0] || null
  } catch (error) {
    ElMessage.error(errorMessage(error))
  }
}
async function chooseTask(task: MeasurementTask) {
  if (task === selected.value || !(await confirmDiscard())) return
  selected.value = task
}
async function changeFilter(value: string) {
  if (!(await confirmDiscard())) return
  status.value = value
  editor.value?.reset()
  page.value = 1
  await load()
}
async function changeDag(value: number | string | null | undefined) {
  if (!(await confirmDiscard())) return
  dag.value = normalizedDag(value)
  selected.value = nextPendingTask(tasks.value, dag.value) || pending.value[0] || null
  page.value = 1
  await load()
}
async function afterSave() {
  try {
    await loadTasks()
    await load()
    const next = nextPendingTask(tasks.value, dag.value)
    if (next) {
      selected.value = next
      return
    }
    ElMessage({
      message: `${current.value?.experiment_number} ${current.value?.common_name || current.value?.scientific_name}今日任务已完成`,
      type: 'success',
      duration: 1800,
    })
    const params = new URLSearchParams({
      status: 'pending',
      page: '1',
      page_size: '25',
      q: search.value,
    })
    if (dag.value !== null) params.set('dag', String(dag.value))
    const result = (
      await api.get<MeasurementWorklist>(`${base.value}/measurement-worklist?${params}`)
    ).data
    const material = result.materials.find((m) => m.material_id !== current.value?.material_id)
    if (material) {
      await chooseMaterial(material, true)
      ElMessage({
        message: `继续测定 ${material.experiment_number} ${material.common_name || material.scientific_name}`,
        duration: 1500,
      })
    } else selected.value = null
  } catch (error) {
    ElMessage.error(errorMessage(error))
  }
}
async function refreshRecords() {
  const old = selected.value
  try {
    await loadTasks()
    await load()
    if (old)
      selected.value =
        tasks.value.find(
          (t) => t.sample_id === old.sample_id && t.timepoint_id === old.timepoint_id,
        ) || null
  } catch (error) {
    ElMessage.error(errorMessage(error))
  }
}
async function edit(task: MeasurementTask) {
  if (!(await confirmDiscard())) return
  editor.value?.reset()
  editing.value = task
}
watch(tab, () => editor.value?.reset())
onBeforeRouteLeave(confirmDiscard)
function beforeUnload(event: BeforeUnloadEvent) {
  if (editor.value?.dirty || dialog.value?.dirty() || records.value?.dirty()) {
    event.preventDefault()
    event.returnValue = ''
  }
}
onMounted(() => {
  void load()
  window.addEventListener('beforeunload', beforeUnload)
})
onUnmounted(() => window.removeEventListener('beforeunload', beforeUnload))
</script>
<template>
  <p class="wizard-help">
    按材料连续测定根长、苗长。发芽后测定时间（DAG）按单株发芽判定日期安排；空白、实测 0
    和无法测量分别记录。
  </p>
  <el-tabs v-model="tab" :before-leave="confirmDiscard"
    ><el-tab-pane label="待测工作台" name="worklist" /><el-tab-pane label="测定记录" name="records"
  /></el-tabs>
  <MeasurementRecords
    v-if="tab === 'records' && data"
    ref="records"
    :experiment-id="String(route.params.id)"
    :status="data.experiment_status"
    :days="data.dag_days"
  />
  <p v-else-if="data && data.experiment_status !== 'active'" class="wizard-empty">
    {{
      ['completed', 'cancelled'].includes(data.experiment_status)
        ? '实验已结束，无当前执行待办；请打开“测定记录”查看历史数据。'
        : '实验尚未开始，无当前执行待办。'
    }}
  </p>
  <div v-else-if="data" class="measurement-workbench">
    <div class="execution-overview-stats measurement-stats">
      <div>
        <small>今日待测</small><strong>{{ data.summary.due_today_count }}</strong>
      </div>
      <div>
        <small>已逾期</small><strong>{{ data.summary.overdue_count }}</strong>
      </div>
      <div>
        <small>今日完成</small><strong>{{ data.summary.completed_today_count }}</strong>
      </div>
      <div>
        <small>后续任务</small><strong>{{ data.summary.upcoming_count }}</strong>
      </div>
      <div>
        <small>涉及材料数</small><strong>{{ data.summary.material_count }}</strong>
      </div>
    </div>
    <p v-if="data.summary.unschedulable_count" class="execution-alert">
      有 {{ data.summary.unschedulable_count }} 项测定缺少发芽判定时间，请核对历史幼苗。
    </p>
    <div class="measurement-layout material-workbench">
      <aside class="measurement-queue">
        <h3>实验材料</h3>
        <el-input
          v-model="search"
          clearable
          placeholder="搜索材料、培养皿或幼苗编号（001-01 / 001-1-01）、中文名或学名"
        />
        <div class="material-worklist-filters">
          <el-select :model-value="status" @change="changeFilter"
            ><el-option label="当前待处理" value="pending" /><el-option
              label="有逾期"
              value="overdue" /><el-option label="今日待测" value="due_today" /><el-option
              label="全部有任务"
              value="all" /></el-select
          ><el-select :model-value="dag" clearable placeholder="全部测定时间" @change="changeDag"
            ><el-option
              v-for="day in data.dag_days"
              :key="day"
              :value="day"
              :label="`发芽后第 ${day} 天`"
          /></el-select>
        </div>
        <button
          v-for="material in data.materials"
          :key="material.material_id"
          type="button"
          class="measurement-task material-worklist-item"
          :class="{ selected: current?.material_id === material.material_id }"
          @click="chooseMaterial(material)"
        >
          <b
            ><span class="experiment-number-badge">{{ material.experiment_number }}</span>
            {{ material.common_name || material.scientific_name }}</b
          ><small v-if="material.common_name">{{ material.scientific_name }}</small
          ><span>今日待测 {{ material.due_today_count }} · 已逾期 {{ material.overdue_count }}</span
          ><small
            ><span v-for="count in material.dag_counts" :key="count.day_after_germination"
              >DAG{{ count.day_after_germination }} {{ count.pending_count }}　</span
            ></small
          >
        </button>
        <p v-if="!data.materials.length" class="wizard-empty">
          没有符合条件的材料，请调整筛选或先完成发芽巡检。
        </p>
        <el-pagination
          v-model:current-page="page"
          v-model:page-size="pageSize"
          :page-sizes="[25, 50, 100]"
          :total="data.total_materials"
          layout="total, sizes, prev, next"
          small
        />
      </aside>
      <div class="measurement-detail">
        <template v-if="current"
          ><section class="measurement-current-work">
            <strong>当前工作</strong>
            <h3>
              {{ current.experiment_number }} · {{ current.common_name || current.scientific_name }}
            </h3>
            <small v-if="current.common_name">{{ current.scientific_name }}</small>
            <div class="measurement-work-status">
              <el-tag v-if="selected">DAG {{ selected.day_after_germination }}</el-tag
              ><span
                >今日剩余 {{ due }} 株<span v-if="overdue"> · 逾期 {{ overdue }} 株</span></span
              >
            </div>
            <p v-if="selected">当前：幼苗 {{ selected.sample_display_number || '编号未确认' }}</p>
            <small>完成本材料后将自动进入下一份待测材料。</small>
          </section>
          <el-table
            class="measurement-task-table"
            :data="pending"
            max-height="220"
            :row-class-name="taskRowClass"
            @row-click="chooseTask"
            ><el-table-column label="幼苗编号" min-width="145"
              ><template #default="{ row }"
                >幼苗 {{ row.sample_display_number || '编号未确认' }}</template
              ></el-table-column
            ><el-table-column label="DAG" prop="day_after_germination" width="65" /><el-table-column
              label="计划日期"
              prop="scheduled_date"
              min-width="110"
            /><el-table-column label="状态" min-width="95"
              ><template #default="{ row }">{{
                measurementStatusLabels[row.status as keyof typeof measurementStatusLabels]
              }}</template></el-table-column
            ></el-table
          >
          <div class="measurement-entry-context">
            <MeasurementEditor
              v-if="selected"
              ref="editor"
              :task="selected"
              :status="data.experiment_status"
              advance
              @saved="afterSave"
              @cleared="refreshRecords"
            />
            <p v-else class="wizard-empty">
              该材料当前没有待处理测定。可查看下方已测历史，或选择另一份材料。
            </p>
            <section v-if="selected" class="measurement-reference">
              <h3>同材料 DAG {{ selected.day_after_germination }} 已测参考</h3>
              <p>用于录入时核对数量级，仅显示原始测定值。</p>
              <el-table :data="reference" max-height="240"
                ><el-table-column label="幼苗编号" min-width="170"
                  ><template #default="{ row }"
                    >幼苗 {{ row.sample_display_number || '编号未确认' }}</template
                  ></el-table-column
                ><el-table-column label="根长（mm）"
                  ><template #default="{ row }">{{
                    measurementValue(row.root_length_mm, row.root_unavailable, true)
                  }}</template></el-table-column
                ><el-table-column label="苗长（mm）"
                  ><template #default="{ row }">{{
                    measurementValue(row.shoot_length_mm, row.shoot_unavailable, true)
                  }}</template></el-table-column
                ></el-table
              >
            </section>
          </div>
        </template>
        <p v-else class="wizard-empty">从左侧选择一份材料，开始连续测定幼苗。</p>
      </div>
    </div>
    <section v-if="current" class="measurement-history">
      <el-button
        class="measurement-history-toggle"
        :aria-expanded="historyOpen"
        @click="historyOpen = !historyOpen"
        >{{ historyOpen ? '收起' : '展开' }}本材料测定进度与记录（已完成 {{ measured.length }} /
        {{ tasks.length }}）</el-button
      >
      <template v-if="historyOpen">
        <p>
          按培养皿、幼苗和发芽后测定时间（DAG）查看全部任务。0 为真实零值，NA 为无法测量，—
          为未测；只有已测记录可修改。
        </p>
        <MeasurementRecordsTable
          :items="progressTasks"
          compact
          :readonly="data.experiment_status === 'cancelled'"
          :current-id="selected?.measurement_id || undefined"
          :current-sample="selected?.sample_id"
          :current-dag="selected?.day_after_germination"
          @edit="edit"
        />
      </template>
    </section>
    <MeasurementEditDialog
      ref="dialog"
      :task="editing"
      :status="data.experiment_status"
      @close="editing = null"
      @changed="refreshRecords"
    />
  </div>
  <p v-else class="wizard-empty">正在加载材料测定工作台…</p>
</template>
