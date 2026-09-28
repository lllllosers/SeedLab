<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { api, errorMessage } from '../api/client'
import type { SeedLot, Taxon } from '../types'
import { dateText } from '../utils'
import { Plus, Search } from '@element-plus/icons-vue'

const lots = ref<SeedLot[]>([]),
  taxa = ref<Taxon[]>([]),
  query = ref(''),
  loading = ref(false)
const editorOpen = ref(false),
  editingId = ref<string | null>(null)
const form = reactive({ taxon_id: '', source: '', quantity: null as number | null, notes: '' })
const taxonNames = computed(() =>
  Object.fromEntries(taxa.value.map((item) => [item.id, item.scientific_name])),
)
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
function openEditor(item?: SeedLot) {
  editingId.value = item?.id || null
  Object.assign(form, {
    taxon_id: item?.taxon_id || '',
    source: item?.source || '',
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
onMounted(load)
</script>
<template>
  <div class="page-heading">
    <div>
      <div class="eyebrow">RESOURCE LIBRARY / SEED LOTS</div>
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
          placeholder="搜索编号或来源"
          clearable
          :prefix-icon="Search"
          @input="load"
        />
      </div>
    </div>
    <el-table
      :data="lots"
      v-loading="loading"
      class="data-table"
      empty-text="暂无批次，请先新增物种并创建批次"
      ><el-table-column prop="code" label="批次编号" width="170" /><el-table-column
        label="所属物种"
        min-width="220"
        ><template #default="{ row }"
          ><router-link class="table-link" :to="`/taxa/${row.taxon_id}`"
            ><i>{{ taxonNames[row.taxon_id] || '未知物种' }}</i></router-link
          ></template
        ></el-table-column
      ><el-table-column prop="source" label="来源" min-width="180"
        ><template #default="{ row }">{{ row.source || '—' }}</template></el-table-column
      ><el-table-column label="数量" width="100"
        ><template #default="{ row }">{{ row.quantity ?? '—' }}</template></el-table-column
      ><el-table-column label="状态" width="100"
        ><template #default="{ row }"
          ><span class="status-pill" :class="row.is_active ? 'active' : 'cancelled'">{{
            row.is_active ? '使用中' : '已停用'
          }}</span></template
        ></el-table-column
      ><el-table-column label="创建日期" width="120"
        ><template #default="{ row }">{{ dateText(row.created_at) }}</template></el-table-column
      ><el-table-column label="操作" width="90"
        ><template #default="{ row }"
          ><el-button link type="primary" @click="openEditor(row)">编辑</el-button></template
        ></el-table-column
      ></el-table
    >
  </div>
  <el-dialog v-model="editorOpen" :title="editingId ? '编辑种子批次' : '新增种子批次'" width="540px"
    ><el-form label-position="top"
      ><el-form-item label="所属物种 *"
        ><el-select
          v-model="form.taxon_id"
          placeholder="选择物种"
          filterable
          style="width: 100%"
          :disabled="!!editingId"
          ><el-option
            v-for="item in taxa.filter((value) => value.is_active)"
            :key="item.id"
            :label="`${item.code} · ${item.scientific_name}`"
            :value="item.id" /></el-select></el-form-item
      ><el-form-item label="来源"
        ><el-input v-model="form.source" placeholder="采集地或来源说明" /></el-form-item
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
