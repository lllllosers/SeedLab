<script setup lang="ts">
import { ref } from 'vue'
import { ElMessage } from 'element-plus'
import { api, errorMessage } from '../api/client'
import { Download, UploadFilled, Document } from '@element-plus/icons-vue'

const file = ref<File | null>(null),
  lotFile = ref<File | null>(null),
  taxonInput = ref<HTMLInputElement | null>(null),
  lotInput = ref<HTMLInputElement | null>(null),
  busy = ref(false),
  lotBusy = ref(false),
  lotError = ref('')
function selected(event: Event) {
  file.value = (event.target as HTMLInputElement).files?.[0] || null
}
function selectedLotFile(event: Event) {
  lotFile.value = (event.target as HTMLInputElement).files?.[0] || null
  lotError.value = ''
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
    if (taxonInput.value) taxonInput.value.value = ''
  } catch (error) {
    ElMessage.error(errorMessage(error))
  } finally {
    busy.value = false
  }
}
async function download() {
  try {
    const { data } = await api.get<Blob>('/export/taxa.csv', { responseType: 'blob' })
    saveFile(data, 'seedlab-taxa.csv')
  } catch (error) {
    ElMessage.error(errorMessage(error))
  }
}
async function downloadTaxaTemplate() {
  try {
    const { data } = await api.get<Blob>('/export/taxa-template.xlsx', { responseType: 'blob' })
    saveFile(data, 'seedlab-taxa-template.xlsx')
  } catch (error) {
    ElMessage.error(errorMessage(error))
  }
}
function saveFile(data: Blob, filename: string) {
  const url = URL.createObjectURL(data)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  link.click()
  URL.revokeObjectURL(url)
}
async function downloadLotTemplate() {
  try {
    const { data } = await api.get<Blob>('/export/seed-lots-template.xlsx', { responseType: 'blob' })
    saveFile(data, 'seedlab-seed-lots-template.xlsx')
  } catch (error) {
    ElMessage.error(errorMessage(error))
  }
}
async function uploadLots() {
  if (!lotFile.value) return ElMessage.warning('请先选择填写好的种子批次文件')
  lotBusy.value = true
  lotError.value = ''
  try {
    const form = new FormData()
    form.append('file', lotFile.value)
    const { data } = await api.post<{ imported: number }>('/import/seed-lots', form)
    ElMessage.success(`已新增 ${data.imported} 个种子批次`)
    lotFile.value = null
    if (lotInput.value) lotInput.value.value = ''
  } catch (error) {
    lotError.value = errorMessage(error)
  } finally {
    lotBusy.value = false
  }
}
</script>
<template>
  <div class="page-heading">
    <div>
      <div class="eyebrow">导入与导出</div>
      <h1>导入与导出</h1>
      <p>下载模板填写材料信息，再批量导入；导入前会检查整张表。</p>
    </div>
  </div>
  <div class="data-cards">
    <section class="surface-panel data-card">
      <div class="data-card-icon">
        <el-icon><UploadFilled /></el-icon>
      </div>
      <h3>导入物种</h3>
      <p>下载模板后填写物种学名；中文名和科可选填。填好后上传 Excel 文件批量建立物种。</p>
      <el-button plain :icon="Download" @click="downloadTaxaTemplate">下载物种模板</el-button>
      <div class="file-picker">
        <label for="taxon-file" class="file-label"
          ><el-icon><Document /></el-icon>{{ file?.name || '选择 Excel 文件' }}</label
        ><input id="taxon-file" ref="taxonInput" type="file" accept=".xlsx" @change="selected" />
      </div>
      <el-button type="primary" :loading="busy" @click="upload">导入物种</el-button
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
  <section class="surface-panel data-card lot-import-card">
    <div class="data-card-icon"><el-icon><UploadFilled /></el-icon></div>
    <h3>种子批次批量导入</h3>
    <p>下载包含当前物种的模板，核对物种编号，填写来源、数量和备注后上传。每一行会建立一个新的种子批次。</p>
    <el-button plain :icon="Download" @click="downloadLotTemplate">下载种子批次模板</el-button>
    <div class="file-picker">
      <label for="lot-file" class="file-label"><el-icon><Document /></el-icon>{{ lotFile?.name || '选择填写好的 Excel 文件' }}</label>
      <input id="lot-file" ref="lotInput" type="file" accept=".xlsx" @change="selectedLotFile" />
    </div>
    <el-button type="primary" :loading="lotBusy" @click="uploadLots">导入种子批次</el-button>
    <p v-if="lotError" class="import-error" role="alert">{{ lotError }}</p>
    <small>一次最多 500 行。若有物种编号或数量填写错误，整张表都不会导入；请按提示修改后重新上传。</small>
  </section>
</template>
