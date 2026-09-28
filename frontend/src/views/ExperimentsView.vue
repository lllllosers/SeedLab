<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { api, errorMessage } from '../api/client'
import type { Experiment, ExperimentStatus } from '../types'
import { dateText, statusLabels } from '../utils'
import { Plus, Search } from '@element-plus/icons-vue'

const router = useRouter(),
  items = ref<Experiment[]>([]),
  query = ref(''),
  status = ref(''),
  loading = ref(false),
  editorOpen = ref(false)
const form = reactive({ name: '', description: '' })
async function load() {
  loading.value = true
  try {
    items.value = (
      await api.get<Experiment[]>('/experiments', {
        params: { q: query.value, status: status.value || undefined },
      })
    ).data
  } catch (error) {
    ElMessage.error(errorMessage(error))
  } finally {
    loading.value = false
  }
}
async function create() {
  if (!form.name.trim()) return ElMessage.warning('请填写实验名称')
  try {
    const { data } = await api.post<Experiment>('/experiments', {
      name: form.name.trim(),
      description: form.description.trim() || null,
    })
    editorOpen.value = false
    ElMessage.success('实验已创建')
    router.push(`/experiments/${data.id}`)
  } catch (error) {
    ElMessage.error(errorMessage(error))
  }
}
function openEditor() {
  form.name = ''
  form.description = ''
  editorOpen.value = true
}
onMounted(load)
</script>
<template>
  <div class="page-heading">
    <div>
      <div class="eyebrow">EXPERIMENT MANAGEMENT</div>
      <h1>实验列表</h1>
      <p>从设计和基础信息开始，为每项实验建立可追溯档案。</p>
    </div>
    <el-button
      type="primary"
      :icon="Plus"
      @click="openEditor"
      >创建实验</el-button
    >
  </div>
  <div class="surface-panel table-panel">
    <div class="table-toolbar">
      <div class="toolbar-title">
        <h3>实验档案</h3>
        <span>{{ items.length }} 项实验</span>
      </div>
      <div class="toolbar-actions">
        <el-input
          v-model="query"
          placeholder="搜索实验编号或名称"
          clearable
          :prefix-icon="Search"
          @input="load"
        /><el-select
          v-model="status"
          placeholder="全部状态"
          clearable
          style="width: 145px"
          @change="load"
          ><el-option label="草稿" value="draft" /><el-option
            label="进行中"
            value="active" /><el-option label="已完成" value="completed" /><el-option
            label="已取消"
            value="cancelled"
        /></el-select>
      </div>
    </div>
    <el-table
      :data="items"
      v-loading="loading"
      class="data-table"
      empty-text="暂无实验，点击右上角创建"
      ><el-table-column prop="code" label="实验编号" width="170" /><el-table-column
        label="实验名称"
        min-width="300"
        ><template #default="{ row }"
          ><router-link class="table-link strong" :to="`/experiments/${row.id}`">{{
            row.name
          }}</router-link>
          <div class="table-subtitle">{{ row.description || '暂无说明' }}</div></template
        ></el-table-column
      ><el-table-column label="状态" width="120"
        ><template #default="{ row }"
          ><span class="status-pill" :class="row.status">{{
            statusLabels[row.status as ExperimentStatus]
          }}</span></template
        ></el-table-column
      ><el-table-column label="创建日期" width="140"
        ><template #default="{ row }">{{ dateText(row.created_at) }}</template></el-table-column
      ><el-table-column label="操作" width="100"
        ><template #default="{ row }"
          ><el-button link type="primary" @click="router.push(`/experiments/${row.id}`)"
            >查看详情</el-button
          ></template
        ></el-table-column
      ></el-table
    >
  </div>
  <el-dialog v-model="editorOpen" title="创建实验" width="540px"
    ><p class="dialog-intro">先建立实验档案，后续阶段可继续配置材料、培养皿和测定计划。</p>
    <el-form label-position="top"
      ><el-form-item label="实验名称 *"
        ><el-input v-model="form.name" placeholder="例如 不同温度对种子萌发的影响" /></el-form-item
      ><el-form-item label="实验说明"
        ><el-input
          v-model="form.description"
          type="textarea"
          :rows="4"
          placeholder="简要记录研究目标或设计说明" /></el-form-item></el-form
    ><template #footer
      ><el-button @click="editorOpen = false">取消</el-button
      ><el-button type="primary" @click="create">创建实验</el-button></template
    ></el-dialog
  >
</template>
