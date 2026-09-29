<script setup lang="ts">
import { reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { api, errorMessage } from '../../api/client'
import type { GerminationExecution } from '../../types'
import { dateTimeText } from '../../utils'

const props = defineProps<{ execution: GerminationExecution }>()
const emit = defineEmits<{ saved: [] }>()
const values = reactive<Record<string, string>>({})
const notes = reactive<Record<string, string>>({})
const saving = ref(false)
const pad = (value: number) => String(value).padStart(2, '0')
function localNow() {
  const date = new Date()
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`
}
const observedAt = ref(localNow())
function focusNext(index: number) {
  const inputs = document.querySelectorAll<HTMLInputElement>('[data-germination-count]')
  inputs[index + 1]?.focus()
}
function sampleProgress(dish: GerminationExecution['dishes'][number]) {
  const current =
    props.execution.sample_scope === 'per_material' ? dish.material_sample_count : dish.sample_count
  return `${current} / ${dish.sample_target ?? '—'}`
}
async function save() {
  const entries = []
  for (const dish of props.execution.dishes) {
    const raw = values[dish.id]?.trim() ?? ''
    if (raw === '') continue
    const count = Number(raw)
    if (!Number.isInteger(count) || count < 0)
      return ElMessage.warning(`${dish.code} 的本次新增必须为非负整数`)
    entries.push({
      dish_id: dish.id,
      new_germinated_count: count,
      notes: notes[dish.id]?.trim() || null,
    })
  }
  if (!entries.length) return ElMessage.warning('请至少填写一个培养皿；空白表示本次未巡检')
  const date = new Date(observedAt.value)
  if (Number.isNaN(date.getTime())) return ElMessage.warning('请填写有效的巡检时间')
  saving.value = true
  try {
    await api.post(`/experiments/${props.execution.experiment.id}/observations/batch`, {
      observed_at: date.toISOString(),
      entries,
    })
    for (const dish of props.execution.dishes) {
      values[dish.id] = ''
      notes[dish.id] = ''
    }
    ElMessage.success(`已保存 ${entries.length} 个培养皿的巡检`)
    emit('saved')
  } catch (error) {
    ElMessage.error(errorMessage(error))
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <div class="execution-section-head">
    <div>
      <h3>快速巡检录入</h3>
      <p>共享巡检时间；空白表示未检查，明确填写 0 表示已检查但没有新增发芽。</p>
    </div>
    <div class="execution-time">
      <label>巡检时间</label><input v-model="observedAt" type="datetime-local" step="60" />
    </div>
  </div>
  <div class="execution-table-wrap">
    <table class="execution-table quick-entry-table">
      <thead>
        <tr>
          <th>培养皿 / 材料</th>
          <th>重复</th>
          <th>置床</th>
          <th>当前累计</th>
          <th>发芽率</th>
          <th>剩余</th>
          <th>取样进度</th>
          <th>本次新增</th>
          <th>备注</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="(dish, index) in execution.dishes" :key="dish.id">
          <td>
            <b>{{ dish.taxon_common_name || dish.taxon_scientific_name }}</b>
            <small v-if="dish.taxon_common_name">{{ dish.taxon_scientific_name }}</small>
            <small>{{ dish.code }} · {{ dish.seed_lot_code }}</small>
          </td>
          <td>R{{ dish.replicate_no }}</td>
          <td>{{ dish.seed_count }}</td>
          <td>
            <strong>{{ dish.cumulative_germinated }}</strong>
          </td>
          <td>{{ dish.germination_rate }}%</td>
          <td>{{ dish.remaining_ungerminated }}</td>
          <td>{{ sampleProgress(dish) }}</td>
          <td>
            <input
              v-model="values[dish.id]"
              data-germination-count
              type="number"
              min="0"
              step="1"
              inputmode="numeric"
              placeholder="—"
              aria-label="本次新增发芽数"
              @keydown.enter.prevent="focusNext(index)"
            />
          </td>
          <td>
            <input v-model="notes[dish.id]" type="text" placeholder="可选" aria-label="巡检备注" />
          </td>
        </tr>
      </tbody>
    </table>
  </div>
  <div class="quick-entry-foot">
    <span>置床于 {{ dateTimeText(execution.experiment.started_at) }} · 支持同一天多次巡检</span
    ><el-button
      type="primary"
      :loading="saving"
      :disabled="execution.experiment.status !== 'active'"
      @click="save"
      >保存本次巡检</el-button
    >
  </div>
</template>
