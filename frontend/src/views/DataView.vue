<script setup lang="ts">
import { ref } from 'vue'
import { ElMessage } from 'element-plus'
import { api, errorMessage } from '../api/client'
import { Download, UploadFilled, Document } from '@element-plus/icons-vue'

const file = ref<File | null>(null),
  busy = ref(false)
function selected(event: Event) {
  file.value = (event.target as HTMLInputElement).files?.[0] || null
}
async function upload() {
  if (!file.value) return ElMessage.warning('请选择 .xlsx 文件')
  busy.value = true
  try {
    const form = new FormData()
    form.append('file', file.value)
    const { data } = await api.post<{ imported: number }>('/import/taxa', form)
    ElMessage.success(`已导入 ${data.imported} 个物种`)
    file.value = null
  } catch (error) {
    ElMessage.error(errorMessage(error))
  } finally {
    busy.value = false
  }
}
async function download() {
  try {
    const { data } = await api.get<Blob>('/export/taxa.csv', { responseType: 'blob' })
    const url = URL.createObjectURL(data)
    const link = document.createElement('a')
    link.href = url
    link.download = 'seedlab-taxa.csv'
    link.click()
    URL.revokeObjectURL(url)
  } catch (error) {
    ElMessage.error(errorMessage(error))
  }
}
</script>
<template>
  <div class="page-heading">
    <div>
      <div class="eyebrow">DATA EXCHANGE</div>
      <h1>导入与导出</h1>
      <p>使用 Excel 交换物种基础信息，数据库保留正式记录与操作历史。</p>
    </div>
  </div>
  <div class="data-cards">
    <section class="surface-panel data-card">
      <div class="data-card-icon">
        <el-icon><UploadFilled /></el-icon>
      </div>
      <h3>导入物种</h3>
      <p>
        上传 .xlsx 文件，批量建立物种档案。首行必须包含 <code>scientific_name</code>，可选
        <code>common_name</code> 和 <code>family</code>。
      </p>
      <div class="file-picker">
        <label for="taxon-file" class="file-label"
          ><el-icon><Document /></el-icon>{{ file?.name || '选择 Excel 文件' }}</label
        ><input id="taxon-file" type="file" accept=".xlsx" @change="selected" />
      </div>
      <el-button type="primary" :loading="busy" @click="upload">开始导入</el-button
      ><small>单次最多 500 行、2 MB。学名重复时整批不导入。</small>
    </section>
    <section class="surface-panel data-card">
      <div class="data-card-icon green">
        <el-icon><Download /></el-icon>
      </div>
      <h3>导出物种</h3>
      <p>下载当前物种档案的 CSV 文件，可用 Excel 打开，用于数据交换或归档。</p>
      <el-button plain :icon="Download" @click="download">下载物种 CSV</el-button
      ><small>导出字段包含编号、学名、俗名、科、状态与备注。</small>
    </section>
  </div>
</template>
