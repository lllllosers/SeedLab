<script setup lang="ts">
import { computed, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api, errorMessage } from '../../api/client'
import type { GerminationExecution } from '../../types'
import { dateTimeText } from '../../utils'
import { useClientPagination } from '../../composables/useClientPagination'

const props = defineProps<{ execution: GerminationExecution }>()
const emit = defineEmits<{ changed: [] }>()
const selected = ref<string[]>([])
const search = ref('')
const status = ref('all')
const busy = ref(false)
const now = () => {
  const date = new Date()
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}T${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}`
}
const localInputTime = (value: string) => {
  const date = new Date(value)
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}T${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}`
}
const sowAt = ref(now())
const groups = computed(() => props.execution.materials.map((material) => ({
  material, dishes: props.execution.dishes.filter((dish) => dish.material_id === material.id),
})))
const filteredGroups = computed(() => groups.value.filter(({ material }) => {
  const term = search.value.trim().toLocaleLowerCase()
  const matches = !term || [material.taxon_common_name, material.taxon_scientific_name,
    material.seed_lot_code, material.source_code,
    String(material.experiment_number || material.preview_number)]
    .some((value) => value?.toLocaleLowerCase().includes(term))
  const state = material.sown_count > 0 ? (material.sown_count + material.cancelled_count >= material.dish_count ? 'sown' : 'partial') : (material.cancelled_count >= material.dish_count ? 'cancelled' : 'pending')
  return matches && (status.value === 'all' || status.value === state)
}))
const { page, pageSize, pageItems, resetPage } = useClientPagination(filteredGroups)
function selectMaterial(id: string) {
  const ids = props.execution.dishes.filter((dish) => dish.material_id === id && !dish.sown_at && !dish.cancelled_at).map((dish) => dish.id)
  selected.value = [...new Set([...selected.value, ...ids])]
}
async function sow() {
  if (!selected.value.length) return ElMessage.warning('请先选择待置床培养皿')
  const parsed = new Date(sowAt.value)
  if (Number.isNaN(parsed.getTime())) return ElMessage.warning('请填写有效的实际置床时间')
  busy.value = true
  try {
    await api.post(`/experiments/${props.execution.experiment.id}/sowing/batch`, {
      dish_ids: selected.value, sown_at: parsed.toISOString(),
    })
    ElMessage.success(`已登记 ${selected.value.length} 个培养皿`)
    selected.value = []
    emit('changed')
  } catch (error) { ElMessage.error(errorMessage(error)) }
  finally { busy.value = false }
}
async function correct(dishId: string, oldTime: string) {
  try {
    const { value } = await ElMessageBox.prompt('请输入修正后的实际置床时间（例如 2026-09-29T09:00）',
      '修改置床时间', { inputValue: localInputTime(oldTime), confirmButtonText: '保存修改', cancelButtonText: '取消' })
    const parsed = new Date(value)
    if (Number.isNaN(parsed.getTime())) return ElMessage.warning('请填写有效的置床时间')
    await api.patch(`/experiments/${props.execution.experiment.id}/sowing/${dishId}`, { sown_at: parsed.toISOString() })
    ElMessage.success('置床时间已修正')
    emit('changed')
  } catch (error) { if (error !== 'cancel' && error !== 'close') ElMessage.error(errorMessage(error)) }
}
async function cancel(dishId: string) {
  try {
    const { value } = await ElMessageBox.prompt('取消后保留现场编号，后面的材料不会补号。请填写原因。',
      '取消培养皿', { confirmButtonText: '确认取消', cancelButtonText: '返回', inputValidator: (value) => !!value.trim() || '请填写取消原因' })
    await api.post(`/experiments/${props.execution.experiment.id}/sowing/${dishId}/cancel`, { reason: value })
    ElMessage.success('培养皿已取消，现场编号保留')
    emit('changed')
  } catch (error) { if (error !== 'cancel' && error !== 'close') ElMessage.error(errorMessage(error)) }
}
</script>

<template>
  <div class="execution-section-head"><div><h3>置床管理</h3>
    <p>现场编号已确认。选择任意材料或单个重复，分批登记真实置床时间；首次置床会自动开始实验。</p></div>
  </div>
  <div class="import-stats sowing-stats">
    <span>计划培养皿 <b>{{ execution.dish_count }}</b></span>
    <span>已置床 <b>{{ execution.sown_count }}</b></span>
    <span>待置床 <b>{{ execution.pending_count }}</b></span>
    <span>已取消 <b>{{ execution.cancelled_count }}</b></span>
  </div>
  <div class="sowing-batch-panel">
    <label>本批实际置床时间 <input v-model="sowAt" type="datetime-local" /></label>
    <div class="wizard-bulk-actions"><el-button @click="selected = execution.dishes.filter((dish) => !dish.sown_at && !dish.cancelled_at).map((dish) => dish.id)">全选待置床</el-button>
      <el-button @click="selected = []">取消全选</el-button>
      <el-button type="primary" :loading="busy" :disabled="!selected.length" @click="sow">登记置床（{{ selected.length }}）</el-button></div>
  </div>
  <div class="sowing-filter-row"><el-input v-model="search" clearable placeholder="搜索中文名、学名、实验编号或批次" @input="resetPage" /><el-select v-model="status" aria-label="筛选置床状态" @change="resetPage"><el-option label="全部状态" value="all" /><el-option label="待置床" value="pending" /><el-option label="部分置床" value="partial" /><el-option label="已置床" value="sown" /><el-option label="已取消" value="cancelled" /></el-select></div>
  <el-collapse class="sowing-groups">
    <el-collapse-item v-for="group in pageItems" :key="group.material.id" :name="group.material.id">
      <template #title><div class="sowing-group-title"><span class="wizard-order">{{ String(group.material.experiment_number || group.material.preview_number).padStart(3, '0') }}</span><div class="grow"><b>{{ group.material.taxon_common_name || group.material.taxon_scientific_name }}</b><small>{{ group.material.sown_count }} / {{ group.material.dish_count }} 已置床 · 原始材料编号：{{ group.material.source_code || '未填写' }}<template v-if="group.material.cancelled_count"> · {{ group.material.cancelled_count }} 已取消</template></small></div></div>
        <el-button size="small" :disabled="!group.dishes.some((dish) => !dish.sown_at && !dish.cancelled_at)" @click.stop="selectMaterial(group.material.id)">选择全部待置床重复</el-button>
      </template>
      <div v-for="dish in group.dishes" :key="dish.id" class="wizard-list-row">
        <el-checkbox v-model="selected" :value="dish.id" :disabled="!!dish.sown_at || !!dish.cancelled_at" aria-label="选择培养皿" />
        <div class="grow"><b>{{ dish.field_number || dish.code }}</b>
          <small>{{ dish.sown_at ? `已置床：${dateTimeText(dish.sown_at)}` : dish.cancelled_at ? `已取消：${dish.cancel_reason}` : '待置床' }} · {{ dish.seed_count }} 粒</small></div>
        <el-button v-if="dish.sown_at" link @click="correct(dish.id, dish.sown_at)">修改置床时间</el-button>
        <el-button v-if="!dish.sown_at && !dish.cancelled_at" link type="danger" @click="cancel(dish.id)">取消培养皿</el-button>
      </div>
    </el-collapse-item>
  </el-collapse>
  <div v-if="!filteredGroups.length" class="wizard-empty">没有符合条件的材料。请调整搜索词或状态筛选。</div>
  <el-pagination v-if="filteredGroups.length" v-model:current-page="page" v-model:page-size="pageSize" class="list-pagination" :page-sizes="[25, 50, 100]" layout="total, sizes, prev, pager, next" :total="filteredGroups.length" />
</template>
