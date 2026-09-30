<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api, errorMessage } from '../api/client'
import type { Taxon } from '../types'
import { useClientPagination } from '../composables/useClientPagination'
import { Plus, Search } from '@element-plus/icons-vue'

const router = useRouter()
const items = ref<Taxon[]>([])
const query = ref('')
const includeInactive = ref(false)
const loading = ref(false)
const editorOpen = ref(false)
const editingId = ref<string | null>(null)
const form = reactive({ scientific_name: '', common_name: '', family: '', genus: '', life_form: '', notes: '' })
const sort = ref<{ prop: string; order: string | null }>({ prop: 'default', order: null })
function onSortChange(value: { prop: string; order: string | null }) {
  sort.value = { prop: value.prop || 'default', order: value.order }
  resetPage()
}
const collator = new Intl.Collator('zh-Hans-CN-u-co-pinyin')
const visibleItems = computed(() => sort.value.prop === 'default' ? items.value : [...items.value].sort((a, b) => {
  const direction = sort.value.order === 'descending' ? -1 : 1
  const prop = sort.value.prop
  const comparison = prop === 'code' ? a.code.localeCompare(b.code) :
    prop === 'scientific_name' ? a.scientific_name.localeCompare(b.scientific_name) :
    prop === 'family' ? (a.family || '').localeCompare(b.family || '') :
    prop === 'genus' ? (a.genus || '').localeCompare(b.genus || '') :
    prop === 'life_form' ? (a.life_form || '').localeCompare(b.life_form || '') :
    collator.compare(a.common_name || a.scientific_name, b.common_name || b.scientific_name)
  return direction * (comparison || a.code.localeCompare(b.code))
}))
const { page, pageSize, pageItems, resetPage } = useClientPagination(visibleItems)
async function load() {
  loading.value = true
  try {
    items.value = (
      await api.get<Taxon[]>('/taxa', {
        params: { q: query.value, include_inactive: includeInactive.value },
      })
    ).data
  } catch (error) {
    ElMessage.error(errorMessage(error))
  } finally {
    loading.value = false
  }
}
function openEditor(item?: Taxon) {
  editingId.value = item?.id || null
  Object.assign(form, {
    scientific_name: item?.scientific_name || '',
    common_name: item?.common_name || '',
    family: item?.family || '',
    genus: item?.genus || '',
    life_form: item?.life_form || '',
    notes: item?.notes || '',
  })
  editorOpen.value = true
}
async function save() {
  if (!form.scientific_name.trim()) return ElMessage.warning('请填写学名')
  const payload = {
    scientific_name: form.scientific_name.trim(),
    common_name: form.common_name.trim() || null,
    family: form.family.trim() || null,
    genus: form.genus.trim() || null,
    life_form: form.life_form.trim() || null,
    notes: form.notes.trim() || null,
  }
  try {
    if (editingId.value) await api.patch(`/taxa/${editingId.value}`, payload)
    else await api.post('/taxa', payload)
    ElMessage.success(editingId.value ? '物种已更新' : '物种已创建')
    editorOpen.value = false
    await load()
  } catch (error) {
    ElMessage.error(errorMessage(error))
  }
}
async function toggle(item: Taxon) {
  try {
    await ElMessageBox.confirm(
      item.is_active
        ? `确定停用“${item.common_name || item.scientific_name}”吗？停用后不会出现在常用物种列表或实验材料选择中；已有记录仍保留。`
        : `确定启用“${item.common_name || item.scientific_name}”吗？启用后可再次在物种列表和实验材料选择中选择。`,
      item.is_active ? '停用物种' : '启用物种',
      { type: 'warning' },
    )
    await api.patch(`/taxa/${item.id}`, { is_active: !item.is_active })
    ElMessage.success('状态已更新')
    await load()
  } catch (error) {
    if (error !== 'cancel' && error !== 'close') ElMessage.error(errorMessage(error))
  }
}
async function remove(item: Taxon) {
  try {
    await ElMessageBox.confirm(`永久删除“${item.common_name || item.scientific_name}”及其物种档案？此操作不能撤销；已有种子批次或实验记录的物种不能删除。`, '删除物种', { type: 'warning', confirmButtonText: '永久删除', cancelButtonText: '返回' })
    await api.delete(`/taxa/${item.id}`)
    ElMessage.success('物种已删除')
    await load()
  } catch (error) {
    if (error !== 'cancel' && error !== 'close') ElMessage.error(errorMessage(error))
  }
}
onMounted(load)
</script>
<template>
  <div class="page-heading">
    <div>
      <div class="eyebrow">物种信息</div>
      <h1>物种信息库</h1>
      <p>统一维护物种基础信息，关联种子批次与历次试验。</p>
    </div>
    <el-button type="primary" :icon="Plus" @click="openEditor()">新增物种</el-button>
  </div>
  <div class="surface-panel table-panel">
    <div class="table-toolbar">
      <div class="toolbar-title">
        <h3>物种档案</h3>
        <span>{{ items.length }} 条记录</span>
      </div>
      <div class="toolbar-actions">
        <el-input
          v-model="query"
          placeholder="搜索物种编号、中文名或学名"
          clearable
          :prefix-icon="Search"
          @input="() => { resetPage(); load() }"
        /><el-checkbox v-model="includeInactive" @change="() => { resetPage(); load() }">显示停用</el-checkbox>
      </div>
    </div>
    <el-table
      :data="pageItems"
      v-loading="loading"
      class="data-table"
      @row-dblclick="(row: Taxon) => router.push(`/taxa/${row.id}`)"
      @sort-change="onSortChange"
      empty-text="还没有物种信息。请点击右上角新增物种，再添加种子批次。"
      ><el-table-column prop="code" label="物种编号" width="100" sortable="custom" /><el-table-column
        prop="common_name" label="中文名"
        min-width="165"
        sortable="custom"
        ><template #default="{ row }"
          ><div class="taxon-name">
            <router-link class="table-link strong" :to="`/taxa/${row.id}`">{{ row.common_name || row.scientific_name }}</router-link>
          </div></template
        ></el-table-column
      ><el-table-column prop="scientific_name" label="学名" min-width="155" sortable="custom" show-overflow-tooltip />
      <el-table-column prop="family" label="科" min-width="90" sortable="custom"
        ><template #default="{ row }">{{ row.family || '—' }}</template></el-table-column
      ><el-table-column prop="genus" label="属" min-width="80" sortable="custom"><template #default="{ row }">{{ row.genus || '—' }}</template></el-table-column
      ><el-table-column prop="life_form" label="生活型" min-width="80" sortable="custom"><template #default="{ row }">{{ row.life_form || '—' }}</template></el-table-column
      ><el-table-column label="状态" width="100"
        ><template #default="{ row }"
          ><span class="status-pill" :class="row.is_active ? 'active' : 'cancelled'">{{
            row.is_active ? '使用中' : '已停用'
          }}</span></template
        ></el-table-column
      ><el-table-column label="操作" width="250" fixed="right"
        ><template #default="{ row }"
          ><el-button link type="primary" @click="router.push(`/taxa/${row.id}`)">查看详情</el-button
          ><el-button link @click="openEditor(row)">编辑</el-button
          ><el-button link :type="row.is_active ? 'warning' : 'success'" @click="toggle(row)">{{
            row.is_active ? '停用' : '启用'
          }}</el-button><el-button link type="danger" @click="remove(row)">删除</el-button></template
        ></el-table-column
      ></el-table
    >
    <el-pagination v-model:current-page="page" v-model:page-size="pageSize" class="list-pagination" :page-sizes="[25, 50, 100]" layout="total, sizes, prev, pager, next" :total="visibleItems.length" />
  </div>
  <el-dialog v-model="editorOpen" :title="editingId ? '编辑物种' : '新增物种'" width="540px"
    ><el-form label-position="top"
      ><el-form-item label="学名 *"
        ><el-input
          v-model="form.scientific_name"
          placeholder="例如 Arabidopsis thaliana" /></el-form-item
      ><el-form-item label="中文名 / 俗名"
        ><el-input v-model="form.common_name" placeholder="选填" /></el-form-item
      ><el-form-item label="科"><el-input v-model="form.family" placeholder="选填" /></el-form-item
      ><el-form-item label="属"><el-input v-model="form.genus" placeholder="选填" /></el-form-item
      ><el-form-item label="生活型"><el-input v-model="form.life_form" placeholder="选填" /></el-form-item
      ><el-form-item label="备注"
        ><el-input
          v-model="form.notes"
          type="textarea"
          :rows="3"
          placeholder="选填" /></el-form-item></el-form
    ><template #footer
      ><el-button @click="editorOpen = false">取消</el-button
      ><el-button type="primary" @click="save">保存物种</el-button></template
    ></el-dialog
  >
</template>
