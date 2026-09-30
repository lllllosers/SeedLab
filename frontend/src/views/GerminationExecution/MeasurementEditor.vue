<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api, errorMessage } from '../../api/client'
import type { ExperimentStatus, MeasurementTask } from '../../types'
import {
  createMeasurementPayload,
  focusNextRoot,
  updateMeasurementPayload,
} from '../../utils/measurement'
import { dateTimeText } from '../../utils'
const props = defineProps<{ task: MeasurementTask; status: ExperimentStatus; advance?: boolean }>()
const emit = defineEmits<{ saved: []; cleared: [] }>()
const rootInput = ref<{ focus: () => void } | null>(null)
const shootInput = ref<{ focus: () => void } | null>(null)
const busy = ref(false)
const form = ref({ root: '', shoot: '', rootNA: false, shootNA: false, measuredAt: '', notes: '' })
const initial = ref('')
const canSave = computed(
  () => props.status === 'active' || (props.status === 'completed' && !!props.task.measurement_id),
)
const dirty = computed(() => JSON.stringify(form.value) !== initial.value)
function localInput(value: string | null) {
  const date = value ? new Date(value) : new Date(),
    pad = (n: number) => String(n).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`
}
function reset() {
  form.value = {
    root: props.task.root_length_mm === null ? '' : String(props.task.root_length_mm),
    shoot: props.task.shoot_length_mm === null ? '' : String(props.task.shoot_length_mm),
    rootNA: props.task.root_unavailable,
    shootNA: props.task.shoot_unavailable,
    measuredAt: localInput(props.task.measured_at),
    notes: props.task.notes || '',
  }
  initial.value = JSON.stringify(form.value)
}
watch(
  () => props.task,
  async () => {
    reset()
    await focusNextRoot(nextTick, () => rootInput.value?.focus())
  },
  { immediate: true },
)
async function confirmDiscard() {
  if (!dirty.value) return true
  try {
    await ElMessageBox.confirm('当前测定值尚未保存，是否放弃？', '放弃未保存的测定值', {
      confirmButtonText: '放弃修改',
      cancelButtonText: '继续填写',
      type: 'warning',
    })
    return true
  } catch {
    return false
  }
}
defineExpose({ confirmDiscard, dirty, reset })
async function save() {
  if (busy.value || !canSave.value) return
  try {
    const payload = props.task.measurement_id
      ? updateMeasurementPayload(form.value)
      : createMeasurementPayload(props.task, form.value)
    busy.value = true
    const base = `/experiments/${props.task.experiment_id}/measurements`
    if (props.task.measurement_id) await api.patch(`${base}/${props.task.measurement_id}`, payload)
    else await api.post(base, payload)
    initial.value = JSON.stringify(form.value)
    ElMessage({ message: '测定已保存', type: 'success', duration: 900 })
    emit('saved')
  } catch (error) {
    ElMessage.error(
      error instanceof Error && !(error as { response?: unknown }).response
        ? error.message
        : errorMessage(error),
    )
  } finally {
    busy.value = false
  }
}
async function clear() {
  try {
    await ElMessageBox.confirm(
      `清除后，该幼苗的 DAG ${props.task.day_after_germination} 将恢复为待测状态。`,
      '清除本阶段测定',
      { confirmButtonText: '确认清除', cancelButtonText: '保留记录', type: 'warning' },
    )
    await api.delete(
      `/experiments/${props.task.experiment_id}/measurements/${props.task.measurement_id}`,
    )
    initial.value = JSON.stringify(form.value)
    emit('cleared')
  } catch (error) {
    if (error !== 'cancel' && error !== 'close') ElMessage.error(errorMessage(error))
  }
}
async function savePosition(value: string) {
  try {
    await api.patch(
      `/experiments/${props.task.experiment_id}/samples/${props.task.sample_id}/position`,
      { position_label: value.trim() || null },
    )
    ElMessage({ message: '位置标签已保存', type: 'success', duration: 900 })
  } catch (error) {
    ElMessage.error(errorMessage(error))
  }
}
</script>
<template>
  <div class="measurement-editor">
    <h3>
      {{ task.field_number }} · 幼苗{{ String(task.sample_number).padStart(2, '0') }}
      <el-tag>DAG {{ task.day_after_germination }}</el-tag>
    </h3>
    <p>
      发芽判定 {{ dateTimeText(task.germinated_at) }} · 计划
      {{ task.scheduled_date || '缺少发芽判定时间，无法安排' }}
    </p>
    <div class="measurement-primary-fields">
      <label
        >根长（mm）
        <div>
          <el-input
            ref="rootInput"
            v-model="form.root"
            :disabled="form.rootNA || !canSave"
            inputmode="decimal"
            placeholder="实测值，允许 0"
            @keydown.enter.prevent="shootInput?.focus()"
          /><el-checkbox v-model="form.rootNA" :disabled="!canSave" @change="form.root = ''"
            >无法测量</el-checkbox
          >
        </div></label
      >
      <label
        >苗长（mm）
        <div>
          <el-input
            ref="shootInput"
            v-model="form.shoot"
            :disabled="form.shootNA || !canSave"
            inputmode="decimal"
            placeholder="实测值，允许 0"
            @keydown.enter.prevent="save"
          /><el-checkbox v-model="form.shootNA" :disabled="!canSave" @change="form.shoot = ''"
            >无法测量</el-checkbox
          >
        </div></label
      >
    </div>
    <div class="measurement-secondary-fields">
      <label
        >实际测定时间<input
          v-model="form.measuredAt"
          type="datetime-local"
          :disabled="!canSave" /></label
      ><label
        >备注<el-input
          v-model="form.notes"
          type="textarea"
          :rows="2"
          :disabled="!canSave"
          placeholder="例如根断裂、测量情况；可留空"
      /></label>
    </div>
    <div class="measurement-actions">
      <el-button
        type="primary"
        :loading="busy"
        :disabled="!canSave || task.status === 'unschedulable'"
        @click="save"
        >{{ advance ? '保存并下一株' : '保存修改' }}</el-button
      ><el-button v-if="task.measurement_id" @click="reset">取消修改</el-button
      ><el-button
        v-if="task.measurement_id && status === 'active'"
        type="danger"
        plain
        @click="clear"
        >清除本阶段测定</el-button
      >
    </div>
    <details class="measurement-position">
      <summary>幼苗位置标签（选填）</summary>
      <el-input
        :model-value="task.position_label || ''"
        :disabled="!canSave"
        maxlength="80"
        placeholder="例如 A1、托盘2-15"
        @change="savePosition"
      />
    </details>
  </div>
</template>
