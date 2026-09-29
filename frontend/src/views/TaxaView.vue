<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api, errorMessage } from '../api/client'
import type { Taxon } from '../types'
import { dateText } from '../utils'
import { Plus, Search, Collection } from '@element-plus/icons-vue'

const router = useRouter()
const items = ref<Taxon[]>([])
const query = ref('')
const includeInactive = ref(false)
const loading = ref(false)
const editorOpen = ref(false)
const editingId = ref<string | null>(null)
const form = reactive({ scientific_name: '', common_name: '', family: '', notes: '' })
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
        ? `确定停用“${item.common_name || item.scientific_name}”吗？停用后不会出现在常用物种列表或种子批次导入模板中；已有记录仍保留。`
        : `确定启用“${item.common_name || item.scientific_name}”吗？启用后可再次在物种列表和种子批次导入模板中选择。`,
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
          placeholder="搜索编号、学名或俗名"
          clearable
          :prefix-icon="Search"
          @input="load"
        /><el-checkbox v-model="includeInactive" @change="load">显示停用</el-checkbox>
      </div>
    </div>
    <el-table
      :data="items"
      v-loading="loading"
      class="data-table"
      empty-text="还没有物种信息。请点击右上角新增物种，再添加种子批次。"
      ><el-table-column prop="code" label="编号" width="130" /><el-table-column
        label="物种"
        min-width="260"
        ><template #default="{ row }"
          ><div class="taxon-name">
            <b>{{ row.common_name || row.scientific_name }}</b
            ><small>{{ row.scientific_name }}</small>
          </div></template
        ></el-table-column
      ><el-table-column prop="family" label="科" min-width="130"
        ><template #default="{ row }">{{ row.family || '—' }}</template></el-table-column
      ><el-table-column label="状态" width="100"
        ><template #default="{ row }"
          ><span class="status-pill" :class="row.is_active ? 'active' : 'cancelled'">{{
            row.is_active ? '使用中' : '已停用'
          }}</span></template
        ></el-table-column
      ><el-table-column label="创建日期" width="120"
        ><template #default="{ row }">{{ dateText(row.created_at) }}</template></el-table-column
      ><el-table-column label="操作" width="220" fixed="right"
        ><template #default="{ row }"
          ><el-button link type="primary" @click="router.push(`/taxa/${row.id}`)">查看</el-button
          ><el-button link @click="openEditor(row)">编辑</el-button
          ><el-button link :type="row.is_active ? 'warning' : 'success'" @click="toggle(row)">{{
            row.is_active ? '停用' : '启用'
          }}</el-button></template
        ></el-table-column
      ></el-table
    >
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
