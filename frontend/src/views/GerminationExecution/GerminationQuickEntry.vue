<script setup lang="ts">
import { computed, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { api, errorMessage } from '../../api/client'
import type { GerminationExecution } from '../../types'

const props = defineProps<{ execution: GerminationExecution }>()
const emit = defineEmits<{ saved: [] }>()
const values = reactive<Record<string, string | number>>({})
const notes = reactive<Record<string, string>>({})
const saving = ref(false)
const search = ref('')
const mode = ref('pending')
const sownDate = ref('')
const enteredCount = computed(() => props.execution.dishes.filter((dish) => String(values[dish.id] ?? '').trim() !== '').length)
function sampleDone(dish: GerminationExecution['dishes'][number]) {
  const count = props.execution.sample_scope === 'per_material' ? dish.material_sample_count : dish.sample_count
  return dish.sample_target !== null && count >= dish.sample_target
}
const visibleDishes = computed(() => props.execution.dishes.filter((dish) => {
  if (!dish.sown_at || dish.cancelled_at) return false
  const periodEnded = !!dish.observation_period_end_at && new Date(dish.observation_period_end_at).getTime() < Date.now()
  if (mode.value === 'pending' && (dish.today_observed || periodEnded)) return false
  if (mode.value === 'observed' && !dish.today_observed) return false
  if (mode.value === 'sampled' && !sampleDone(dish)) return false
  if (mode.value === 'ended' && !periodEnded) return false
  if (sownDate.value && dish.sown_at.slice(0, 10) !== sownDate.value) return false
  const term = search.value.trim().toLocaleLowerCase()
  return !term || [dish.field_number, dish.code, dish.experiment_number && String(dish.experiment_number).padStart(3, '0'),
    dish.taxon_common_name, dish.taxon_scientific_name, dish.source_code]
    .some((value) => String(value || '').toLocaleLowerCase().includes(term))
}))
const groups = computed(() => props.execution.materials.map((material) => ({
  material, dishes: visibleDishes.value.filter((dish) => dish.material_id === material.id),
})).filter((group) => group.dishes.length))
const pad = (value: number) => String(value).padStart(2, '0')
function localNow() {
  const date = new Date()
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`
}
const observedAt = ref(localNow())
function focusRelative(event: KeyboardEvent, delta: number) {
  const inputs = document.querySelectorAll<HTMLInputElement>('[data-germination-count]')
  const index = [...inputs].indexOf(event.target as HTMLInputElement)
  inputs[index + delta]?.focus()
}
function sampleProgress(dish: GerminationExecution['dishes'][number]) {
  const current =
    props.execution.sample_scope === 'per_material' ? dish.material_sample_count : dish.sample_count
  return `${current} / ${dish.sample_target ?? '—'}`
}
async function save() {
  const entries = []
  for (const dish of props.execution.dishes) {
    const raw = String(values[dish.id] ?? '').trim()
    if (raw === '') continue
    const count = Number(raw)
    if (!Number.isInteger(count) || count < 0)
      return ElMessage.warning(`${dish.field_number || dish.code} 的本次新增必须为非负整数`)
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
      <h3>发芽巡检工作台</h3>
      <p>共享巡检时间；空白表示未检查，明确填写 0 表示已检查但没有新增发芽。</p>
    </div>
    <div class="execution-time">
      <label>巡检时间</label><input v-model="observedAt" type="datetime-local" step="60" />
    </div>
  </div>
  <div class="import-stats">
    <span>培养皿总数 <b>{{ execution.dish_count }}</b></span>
    <span>已置床 <b>{{ execution.sown_count }}</b></span>
    <span>待置床 <b>{{ execution.pending_count }}</b></span>
    <span>今日已巡检 <b>{{ execution.today_observed_count }}</b></span>
    <span>今日待巡检 <b>{{ execution.today_pending_count }}</b></span>
    <span>已达到取样目标 <b>{{ execution.dishes.filter(sampleDone).length }}</b></span>
  </div>
  <div class="wizard-search-row">
    <el-input v-model="search" placeholder="搜索实验编号、培养皿现场编号、中文名、学名或原始材料编号" clearable />
    <el-select v-model="mode" style="width: 170px">
      <el-option label="今日待巡检" value="pending" /><el-option label="今日已巡检" value="observed" />
      <el-option label="全部已置床" value="all" /><el-option label="已达到取样目标" value="sampled" />
      <el-option label="观察期已结束" value="ended" />
    </el-select>
    <el-date-picker v-model="sownDate" type="date" value-format="YYYY-MM-DD" placeholder="按置床日期筛选" clearable />
  </div>
  <div class="execution-table-wrap">
    <table class="execution-table quick-entry-table">
      <thead>
        <tr>
          <th>培养皿 / 材料</th>
          <th>重复</th>
          <th>置床粒数</th>
          <th>累计发芽</th>
          <th>发芽率</th>
          <th>未发芽</th>
          <th>取样进度</th>
          <th>本次新增</th>
          <th>备注</th>
        </tr>
      </thead>
      <tbody v-for="group in groups" :key="group.material.id">
        <tr class="execution-group-row"><td colspan="9"><b>{{ String(group.material.experiment_number || group.material.preview_number).padStart(3, '0') }} {{ group.material.taxon_common_name || group.material.taxon_scientific_name }}</b> · {{ group.dishes.length }} 个培养皿 · 原始材料编号：{{ group.material.source_code || '未填写' }}</td></tr>
        <tr v-for="dish in group.dishes" :key="dish.id">
          <td>
            <b>{{ dish.field_number || dish.code }}</b>
            <small>{{ dish.seed_lot_code }} · {{ dish.taxon_scientific_name }}</small>
          </td>
          <td>R{{ dish.replicate_no }}</td>
          <td>{{ dish.seed_count }}</td>
          <td>
            <strong>{{ dish.cumulative_germinated }}</strong>
          </td>
          <td>{{ dish.germination_rate }}%</td>
          <td>{{ dish.remaining_ungerminated }}</td>
          <td>{{ sampleProgress(dish) }} <small v-if="sampleDone(dish)">取样完成 ✓；仍可继续巡检</small></td>
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
              @keydown.enter.prevent="focusRelative($event, 1)"
              @keydown.arrow-down.prevent="focusRelative($event, 1)"
              @keydown.arrow-up.prevent="focusRelative($event, -1)"
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
    <span>{{ enteredCount ? `本次将保存 ${enteredCount} 个培养皿` : '请至少填写一个培养皿；0 表示已检查但没有新增发芽。' }} · 同一天可多次巡检</span
    ><el-button
      type="primary"
      :loading="saving"
      :disabled="execution.experiment.status !== 'active' || !enteredCount"
      @click="save"
      >保存本次巡检（{{ enteredCount }}）</el-button
    >
  </div>
</template>
