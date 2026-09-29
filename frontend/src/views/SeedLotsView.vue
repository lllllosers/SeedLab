<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox, type TableInstance } from 'element-plus'
import { api, errorMessage } from '../api/client'
import type { SeedLot, Taxon } from '../types'
import { dateText } from '../utils'
import { Plus, Search } from '@element-plus/icons-vue'
import { useClientPagination } from '../composables/useClientPagination'

const lots = ref<SeedLot[]>([]),
  taxa = ref<Taxon[]>([]),
  query = ref(''),
  loading = ref(false)
const editorOpen = ref(false),
  editingId = ref<string | null>(null)
const table = ref<TableInstance>()
const form = reactive({ taxon_id: '', source_code: '', source: '', collected_at: '', quantity: null as number | null, notes: '' })
const sort = ref<{ prop: string; order: string | null }>({ prop: 'default', order: null })
function onSortChange(value: { prop: string; order: string | null }) {
  sort.value = { prop: value.prop || 'default', order: value.order }
  resetPage()
}
const collator = new Intl.Collator('zh-Hans-CN-u-co-pinyin')
const groups = computed(() => {
  const result = new Map<string, { taxon: Taxon; lots: SeedLot[]; active: number }>()
  for (const lot of lots.value) {
    if (!result.has(lot.taxon_id)) result.set(lot.taxon_id, { taxon: lot.taxon, lots: [], active: 0 })
    const group = result.get(lot.taxon_id)!
    group.lots.push(lot)
    if (lot.is_active) group.active++
  }
  const rows = [...result.values()]
  const direction = sort.value.order === 'descending' ? -1 : 1
  return sort.value.prop === 'default' ? rows : rows.sort((a, b) => {
    const left = a.taxon, right = b.taxon
    const prop = sort.value.prop
    const comparison = prop === 'lot_count' ? a.lots.length - b.lots.length :
      prop === 'code' ? left.code.localeCompare(right.code) :
      prop === 'scientific_name' ? left.scientific_name.localeCompare(right.scientific_name) :
      collator.compare(left.common_name || left.scientific_name, right.common_name || right.scientific_name)
    return direction * (comparison || left.code.localeCompare(right.code))
  })
})
const { page, pageSize, pageItems, resetPage } = useClientPagination(groups)
function toggleGroup(row: (typeof groups.value)[number]) { table.value?.toggleRowExpansion(row) }
const taxonSearch = ref('')
const selectedTaxon = computed(() => taxa.value.find((item) => item.id === form.taxon_id))
const visibleTaxa = computed(() => taxa.value.filter((item) => {
  if (!item.is_active) return false
  const query = taxonSearch.value.trim().toLocaleLowerCase()
  return !query || [item.common_name, item.scientific_name, item.code]
    .some((value) => value?.toLocaleLowerCase().includes(query))
}))
async function load() {
  loading.value = true
  try {
    const [lotResponse, taxonResponse] = await Promise.all([
      api.get<SeedLot[]>('/seed-lots', { params: { q: query.value } }),
      api.get<Taxon[]>('/taxa', { params: { include_inactive: true } }),
    ])
    lots.value = lotResponse.data
    taxa.value = taxonResponse.data
  } catch (error) {
    ElMessage.error(errorMessage(error))
  } finally {
    loading.value = false
  }
}
function openEditor(item?: SeedLot, taxonId?: string) {
  editingId.value = item?.id || null
  taxonSearch.value = ''
  Object.assign(form, {
    taxon_id: item?.taxon_id || taxonId || '',
    source_code: item?.source_code || '',
    source: item?.source || '',
    collected_at: item?.collected_at?.slice(0, 10) || '',
    quantity: item?.quantity ?? null,
    notes: item?.notes || '',
  })
  editorOpen.value = true
}
async function save() {
  if (!form.taxon_id) return ElMessage.warning('请选择物种')
  try {
    const payload = {
      source: form.source.trim() || null,
      source_code: form.source_code.trim() || null,
      collected_at: form.collected_at ? new Date(`${form.collected_at}T00:00:00`).toISOString() : null,
      quantity: form.quantity,
      notes: form.notes.trim() || null,
    }
    if (editingId.value) await api.patch(`/seed-lots/${editingId.value}`, payload)
    else await api.post('/seed-lots', { ...payload, taxon_id: form.taxon_id })
    ElMessage.success('批次已保存')
    editorOpen.value = false
    await load()
  } catch (error) {
    ElMessage.error(errorMessage(error))
  }
}
async function remove(lot: SeedLot) {
  try {
    await ElMessageBox.confirm(`永久删除种子批次 ${lot.code}？此操作不能撤销；已用于实验的批次应停用并保留历史。`, '删除种子批次', { type: 'warning', confirmButtonText: '永久删除', cancelButtonText: '返回' })
    await api.delete(`/seed-lots/${lot.id}`)
    ElMessage.success('种子批次已删除')
    await load()
  } catch (error) { if (error !== 'cancel' && error !== 'close') ElMessage.error(errorMessage(error)) }
}
async function toggle(lot: SeedLot) {
  try {
    await ElMessageBox.confirm(lot.is_active
      ? `停用 ${lot.code} 后不能将其加入新实验，已有实验记录会保留。确定停用吗？`
      : `启用 ${lot.code} 后可以再次将其加入新实验。确定启用吗？`,
    lot.is_active ? '停用种子批次' : '启用种子批次', { confirmButtonText: lot.is_active ? '停用批次' : '启用批次', cancelButtonText: '返回' })
    await api.patch(`/seed-lots/${lot.id}`, { is_active: !lot.is_active })
    ElMessage.success(lot.is_active ? '批次已停用' : '批次已启用')
    await load()
  } catch (error) { if (error !== 'cancel' && error !== 'close') ElMessage.error(errorMessage(error)) }
}
onMounted(load)
</script>
<template>
  <div class="page-heading">
    <div>
      <div class="eyebrow">种子材料</div>
      <h1>种子批次</h1>
      <p>按来源管理种子材料，保留物种与采集批次之间的关系。</p>
    </div>
    <el-button type="primary" :icon="Plus" @click="openEditor()">新增批次</el-button>
  </div>
  <div class="surface-panel table-panel">
    <div class="table-toolbar">
      <div class="toolbar-title">
        <h3>批次档案</h3>
        <span>{{ lots.length }} 条记录</span>
      </div>
      <div class="toolbar-actions">
        <el-input
          v-model="query"
          placeholder="搜索中文名、学名、物种编号、批次编号、原始材料编号或来源"
          clearable
          :prefix-icon="Search"
          @input="() => { resetPage(); load() }"
        />
      </div>
    </div>
    <el-table
      ref="table"
      :data="pageItems"
      v-loading="loading"
      class="data-table seed-lot-group-table"
      row-key="taxon.id"
      @row-click="toggleGroup"
      @sort-change="onSortChange"
      empty-text="暂无批次，请先新增物种并创建批次"
      ><el-table-column type="expand" width="54"><template #default="{ row }">
        <div class="seed-lot-group-detail"><el-table :data="row.lots" size="small">
          <el-table-column prop="code" label="系统批次编号" width="145" />
          <el-table-column label="原始材料编号" width="125"><template #default="{ row: lot }">{{ lot.source_code || '未填写' }}</template></el-table-column>
          <el-table-column label="来源" min-width="130" show-overflow-tooltip><template #default="{ row: lot }">{{ lot.source || '未填写' }}</template></el-table-column>
          <el-table-column label="采集/获得日期" width="140"><template #default="{ row: lot }">{{ dateText(lot.collected_at) }}</template></el-table-column>
          <el-table-column label="数量" width="85"><template #default="{ row: lot }">{{ lot.quantity ?? '未填写' }}</template></el-table-column>
          <el-table-column label="状态" width="80"><template #default="{ row: lot }">{{ lot.is_active ? '使用中' : '已停用' }}</template></el-table-column>
          <el-table-column label="备注" min-width="130" show-overflow-tooltip><template #default="{ row: lot }">{{ lot.notes || '未填写' }}</template></el-table-column>
          <el-table-column label="操作" width="185"><template #default="{ row: lot }"><div class="seed-lot-actions" @click.stop><el-button link @click="openEditor(lot)">编辑</el-button><el-button link :type="lot.is_active ? 'warning' : 'success'" @click="toggle(lot)">{{ lot.is_active ? '停用' : '启用' }}</el-button><el-button link type="danger" @click="remove(lot)">删除</el-button></div></template></el-table-column>
        </el-table></div>
      </template></el-table-column>
      <el-table-column prop="common_name" label="中文名" min-width="200" sortable="custom"><template #default="{ row }"><router-link class="table-link strong" :to="`/taxa/${row.taxon.id}`" @click.stop>{{ row.taxon.common_name || row.taxon.scientific_name }}</router-link></template></el-table-column>
      <el-table-column prop="scientific_name" label="学名" min-width="190" sortable="custom"><template #default="{ row }"><i>{{ row.taxon.scientific_name }}</i></template></el-table-column>
      <el-table-column prop="code" label="物种编号" width="130" sortable="custom"><template #default="{ row }">{{ row.taxon.code }}</template></el-table-column>
      <el-table-column prop="lot_count" label="批次数" width="110" sortable="custom"><template #default="{ row }">{{ row.lots.length }}</template></el-table-column>
      <el-table-column label="可用批次数" width="115"><template #default="{ row }">{{ row.active }}</template></el-table-column>
      <el-table-column label="操作" width="110"><template #default="{ row }"><el-button link type="primary" @click.stop="openEditor(undefined, row.taxon.id)">新增批次</el-button></template></el-table-column>
    </el-table>
    <el-pagination v-model:current-page="page" v-model:page-size="pageSize" class="list-pagination" :page-sizes="[25, 50, 100]" layout="total, sizes, prev, pager, next" :total="groups.length" />
  </div>
  <el-dialog v-model="editorOpen" :title="editingId ? '编辑种子批次' : '新增种子批次'" width="540px"
    ><el-form label-position="top"
      ><el-form-item label="所属物种 *"
        ><el-select
          v-model="form.taxon_id"
          placeholder="选择物种"
          filterable
          :filter-method="(query: string) => (taxonSearch = query)"
          style="width: 100%"
          :disabled="!!editingId"
          ><el-option class="taxon-select-option"
            v-for="item in visibleTaxa"
            :key="item.id"
            :label="item.common_name || item.scientific_name"
            :value="item.id">
            <div class="taxon-option"><strong>{{ item.common_name || item.scientific_name }}</strong>
              <small>{{ item.common_name ? `${item.scientific_name} · ` : '' }}{{ item.code }}</small></div>
          </el-option></el-select></el-form-item
      ><div v-if="selectedTaxon" class="selected-taxon">
        <b>已选择物种：{{ selectedTaxon.common_name || selectedTaxon.scientific_name }}</b>
        <span><i v-if="selectedTaxon.common_name">{{ selectedTaxon.scientific_name }} · </i>{{ selectedTaxon.code }}</span>
      </div
      ><el-form-item label="来源"
        ><el-input v-model="form.source" placeholder="采集地或来源说明" /></el-form-item
      ><el-form-item label="原始材料编号"><el-input v-model="form.source_code" placeholder="例如 A027" /></el-form-item
      ><el-form-item label="采集/获得日期"><el-date-picker v-model="form.collected_at" type="date" value-format="YYYY-MM-DD" placeholder="选择日期" style="width: 100%" /></el-form-item
      ><el-form-item label="数量（粒）"
        ><el-input-number
          v-model="form.quantity"
          :min="0"
          :controls="false"
          style="width: 100%" /></el-form-item
      ><el-form-item label="备注"
        ><el-input v-model="form.notes" type="textarea" :rows="3" /></el-form-item></el-form
    ><template #footer
      ><el-button @click="editorOpen = false">取消</el-button
      ><el-button type="primary" @click="save">保存批次</el-button></template
    ></el-dialog
  >
</template>
