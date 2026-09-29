<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { api, errorMessage } from '../api/client'

type RowStatus = 'registered' | 'new' | 'updatable' | 'confirm' | 'error'
interface PreviewRow {
  line: number
  status: RowStatus
  name: string | null
  scientific_name: string | null
  source_code: string | null
  candidate_lot_id: string | null
  candidate_lots: { id: string; code: string; is_active: boolean; source_code: string | null; source: string | null; collected_at: string | null }[]
  candidate_row: number | null
  suggested_decision: string | null
  fills: string[]
  conflicts: string[]
  errors: string[]
}
interface Preview {
  file_hash: string
  already_imported: boolean
  rows: PreviewRow[]
  stats: Record<string, number>
}
const router = useRouter()
const file = ref<File | null>(null)
const input = ref<HTMLInputElement | null>(null)
const preview = ref<Preview | null>(null)
const decisions = ref<Record<string, string>>({})
const mode = ref<'complete' | 'new'>('complete')
const busy = ref(false)
const imported = ref<{ new_taxa: number; new_lots: number; selected_lot_ids: string[] } | null>(null)
const labels: Record<RowStatus, string> = {
  registered: '已登记', new: '新增', updatable: '可补全/更新',
  confirm: '需要确认', error: '错误',
}
const canConfirm = computed(() => !!preview.value && !preview.value.already_imported &&
  preview.value.stats.errors === 0 &&
  preview.value.rows.every((row) => row.status !== 'confirm' || !!decisions.value[String(row.line)]))
const confirmationRows = computed(() => preview.value?.rows.filter((row) => row.status === 'confirm') || [])
const confirmationSelection = ref<number[]>([])
function applyToSelected(choice: 'reuse' | 'new' | 'suggested') {
  let applied = 0
  for (const row of confirmationRows.value.filter((item) => confirmationSelection.value.includes(item.line))) {
    const reuse = row.candidate_row ? `reuse-row:${row.candidate_row}` : row.candidate_lots.length === 1 ? `reuse:${row.candidate_lots[0]!.id}` : null
    const value = choice === 'new' ? 'new' : choice === 'suggested' ? row.suggested_decision : reuse
    if (value) { decisions.value[String(row.line)] = value; applied++ }
  }
  if (applied < confirmationSelection.value.length) ElMessage.warning(`${confirmationSelection.value.length - applied} 行有多个候选材料或没有明确建议，请逐行选择。`)
}
function selectAllConfirmations() { confirmationSelection.value = confirmationRows.value.map((row) => row.line) }
function changeMode(value: 'complete' | 'new') {
  mode.value = value
  preview.value = null
  decisions.value = {}
  confirmationSelection.value = []
}
function selectFile(event: Event) {
  file.value = (event.target as HTMLInputElement).files?.[0] || null
  preview.value = null
  imported.value = null
  decisions.value = {}
  confirmationSelection.value = []
}
async function downloadTemplate() {
  try {
    const { data } = await api.get<Blob>('/export/materials-template.xlsx', { responseType: 'blob' })
    const url = URL.createObjectURL(data)
    const link = document.createElement('a')
    link.href = url
    link.download = 'seedlab-materials-template.xlsx'
    link.click()
    URL.revokeObjectURL(url)
  } catch (error) { ElMessage.error(errorMessage(error)) }
}
async function preflight() {
  if (!file.value) return ElMessage.warning('请先选择种子材料 Excel 文件')
  busy.value = true
  try {
    const form = new FormData()
    form.append('file', file.value)
    form.append('mode', mode.value)
    preview.value = (await api.post<Preview>('/import/materials/preview', form)).data
    decisions.value = {}
    confirmationSelection.value = []
    if (preview.value.already_imported) ElMessage.warning('这份文件已经成功导入过')
  } catch (error) { ElMessage.error(errorMessage(error)) }
  finally { busy.value = false }
}
async function confirm() {
  if (!file.value || !canConfirm.value) return
  busy.value = true
  try {
    const form = new FormData()
    form.append('file', file.value)
    form.append('mode', mode.value)
    form.append('decisions', JSON.stringify(decisions.value))
    imported.value = (await api.post('/import/materials/confirm', form)).data
    ElMessage.success(`已新增 ${imported.value?.new_lots} 份种子材料`)
    preview.value = null
    file.value = null
    if (input.value) input.value.value = ''
  } catch (error) { ElMessage.error(errorMessage(error)) }
  finally { busy.value = false }
}
function createExperiment() {
  if (!imported.value) return
  sessionStorage.setItem('seedlab-import-lots', JSON.stringify(imported.value.selected_lot_ids))
  router.push('/experiments/new?from_import=1')
}
</script>

<template>
  <section class="surface-panel integrated-import">
    <div class="panel-heading">
      <div><h2>种子材料一体导入</h2>
        <p>一张表同时整理物种信息和种子材料。先预检，再确认导入；已有材料不会重复建立。</p>
      </div>
    </div>
    <div class="integrated-import-actions">
      <el-button @click="downloadTemplate">下载一体导入模板</el-button>
      <input ref="input" type="file" accept=".xlsx" aria-label="选择种子材料文件" @change="selectFile" />
      <el-button type="primary" :loading="busy" @click="preflight">预检材料</el-button>
    </div>
    <div class="import-mode"><strong>这张表是什么类型？</strong>
      <el-radio-group :model-value="mode" @update:model-value="changeMode">
        <el-radio value="complete">完整 / 更新后的材料清单</el-radio>
        <el-radio value="new">本次新增材料</el-radio>
      </el-radio-group>
      <p>{{ mode === 'complete' ? '表中可能包含以前登记过的材料，只新增或补全真正发生变化的部分。' : '表中主要是这次新获得的种子材料；无原始材料编号时倾向建立新批次。' }}</p>
    </div>
    <p v-if="file">当前文件：{{ file.name }}</p>
    <template v-if="preview">
      <el-alert v-if="preview.already_imported" title="这份文件已经成功导入过。若有新增材料，请上传更新后的完整清单。" type="warning" show-icon :closable="false" />
      <div class="import-stats">
        <span>总材料数 <b>{{ preview.stats.total }}</b></span>
        <span>已登记 <b>{{ preview.stats.registered }}</b></span>
        <span>新增材料 <b>{{ preview.stats.new }}</b></span>
        <span>新增物种 <b>{{ preview.stats.new_taxa }}</b></span>
        <span>复用已有物种 <b>{{ preview.stats.reused_taxa }}</b></span>
        <span>可补全资料 <b>{{ preview.stats.updatable }}</b></span>
        <span>需要确认 <b>{{ preview.stats.confirm }}</b></span>
        <span>错误 <b>{{ preview.stats.errors }}</b></span>
      </div>
      <div v-if="confirmationRows.length" class="wizard-bulk-actions">
        <el-button @click="selectAllConfirmations">全选需要确认（{{ confirmationRows.length }}）</el-button>
        <el-button @click="confirmationSelection = []">取消全选</el-button>
        <span>已勾选 {{ confirmationSelection.length }} 行</span>
        <el-button @click="applyToSelected('reuse')">批量复用已有材料</el-button>
        <el-button @click="applyToSelected('new')">批量作为新材料</el-button>
        <el-button @click="applyToSelected('suggested')">按系统建议批量处理</el-button>
      </div>
      <el-table :data="preview.rows" max-height="520" row-key="line" empty-text="文件中没有材料">
        <el-table-column label="勾选" width="70"><template #default="{ row }"><el-checkbox v-if="row.status === 'confirm'" v-model="confirmationSelection" :value="row.line" /></template></el-table-column>
        <el-table-column prop="line" label="Excel 行" width="95" />
        <el-table-column label="物种 / 材料" min-width="230">
          <template #default="{ row }"><b>{{ row.name || row.scientific_name }}</b>
            <small class="table-subtitle">{{ row.scientific_name }} · {{ row.source_code || '原始材料编号未填写' }}</small></template>
        </el-table-column>
        <el-table-column label="预检结果" width="145">
          <template #default="{ row }"><el-tag :type="row.status === 'error' ? 'danger' : row.status === 'confirm' ? 'warning' : row.status === 'new' ? 'success' : 'info'">{{ labels[row.status as RowStatus] }}</el-tag></template>
        </el-table-column>
        <el-table-column label="说明" min-width="280">
          <template #default="{ row }">
            <div v-for="message in row.errors" :key="message">{{ message }}</div>
            <div v-if="row.candidate_row">第 {{ row.candidate_row }} 行可能是同一材料，请确认。</div>
            <div v-if="row.fills.length">将补全：{{ row.fills.join('、') }}</div>
            <div v-if="row.conflicts.length">信息不一致，本次不会自动覆盖：{{ row.conflicts.join('、') }}</div>
            <div v-if="row.status === 'confirm' && row.candidate_lots.length">找到 {{ row.candidate_lots.length }} 份疑似已有材料，请明确选择。</div>
          </template>
        </el-table-column>
        <el-table-column label="处理选择" width="230">
          <template #default="{ row }">
            <el-select v-if="row.status === 'confirm'" v-model="decisions[String(row.line)]" placeholder="请选择">
              <el-option v-if="row.candidate_row" :label="`复用第 ${row.candidate_row} 行`" :value="`reuse-row:${row.candidate_row}`" />
              <el-option v-for="lot in row.candidate_lots" :key="lot.id" :label="`复用 ${lot.code} · ${lot.source_code || lot.source || '来源未填写'}${lot.is_active ? '' : '（已停用）'}`" :value="`reuse:${lot.id}`" />
              <el-option label="作为另一份新材料" value="new" />
            </el-select>
          </template>
        </el-table-column>
      </el-table>
      <div class="integrated-import-actions">
        <el-button type="primary" :disabled="!canConfirm" :loading="busy" @click="confirm">确认导入</el-button>
        <span v-if="preview.stats.errors">请先修正文件中的错误，再重新预检。</span>
        <span v-else-if="preview.stats.confirm && !canConfirm">请处理所有“需要确认”的材料。</span>
      </div>
    </template>
    <div v-if="imported" class="import-success">
      <strong>导入完成：新增 {{ imported.new_taxa }} 个物种、{{ imported.new_lots }} 份材料。</strong>
      <el-button type="primary" :disabled="!imported.selected_lot_ids.length" @click="createExperiment">使用本次导入的材料创建实验</el-button>
    </div>
  </section>
</template>
