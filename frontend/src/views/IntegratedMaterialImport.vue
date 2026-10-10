<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { UploadFilled, Download, Document } from '@element-plus/icons-vue'
import { saveMaterialPrefill, type MaterialImportResult } from '../features/germination'
import { api, errorMessage } from '../shared/api/client'

import {
  identityLabels,
  gerLabels,
  reviewRowReady,
  type PreviewRow,
  type GerStatus,
} from '../shared/materialImportReview'

interface Preview {
  file_hash: string
  already_imported: boolean
  rows: PreviewRow[]
  stats: Record<string, number>
}
const historyLabel = (status: GerStatus) => gerLabels[status]
const router = useRouter()
const file = ref<File | null>(null)
const input = ref<HTMLInputElement | null>(null)
const preview = ref<Preview | null>(null)
const materialDecisions = ref<Record<string, string>>({})
const taxonDecisions = ref<Record<string, string>>({})
const mode = ref<'complete' | 'new'>('complete')
const busy = ref(false)
const imported = ref<MaterialImportResult | null>(null)
const canConfirm = computed(
  () =>
    !!preview.value &&
    !busy.value &&
    !preview.value.already_imported &&
    preview.value.stats.errors === 0 &&
    preview.value.rows.every((row) =>
      reviewRowReady(row, materialDecisions.value[String(row.line)]),
    ),
)
const confirmationRows = computed(
  () => preview.value?.rows.filter((row) => row.material_status === 'confirm') || [],
)
const confirmationSelection = ref<number[]>([])
function applyToSelected(choice: 'reuse' | 'new' | 'suggested') {
  let applied = 0
  for (const row of confirmationRows.value.filter((item) =>
    confirmationSelection.value.includes(item.line),
  )) {
    const reuse = row.candidate_row
      ? `reuse-row:${row.candidate_row}`
      : row.candidate_lots.length === 1
        ? `reuse:${row.candidate_lots[0]!.id}`
        : null
    const value = choice === 'new' ? 'new' : choice === 'suggested' ? row.suggested_decision : reuse
    if (value) {
      materialDecisions.value[String(row.line)] = value
      applied++
    }
  }
  if (applied < confirmationSelection.value.length)
    ElMessage.warning(
      `${confirmationSelection.value.length - applied} 行有多个候选材料或没有明确建议，请逐行选择。`,
    )
}
function selectAllConfirmations() {
  confirmationSelection.value = confirmationRows.value.map((row) => row.line)
}
function changeMode(value: 'complete' | 'new') {
  mode.value = value
  imported.value = null
  preview.value = null
  materialDecisions.value = {}
  taxonDecisions.value = {}
  confirmationSelection.value = []
}
function selectFile(event: Event) {
  file.value = (event.target as HTMLInputElement).files?.[0] || null
  preview.value = null
  imported.value = null
  materialDecisions.value = {}
  taxonDecisions.value = {}
  confirmationSelection.value = []
}
async function downloadTemplate() {
  try {
    const { data } = await api.get<Blob>('/export/materials-template.xlsx', {
      responseType: 'blob',
    })
    const url = URL.createObjectURL(data)
    const link = document.createElement('a')
    link.href = url
    link.download = 'seedlab-materials-template.xlsx'
    link.click()
    URL.revokeObjectURL(url)
  } catch (error) {
    ElMessage.error(errorMessage(error))
  }
}
async function preflight() {
  if (!file.value) return ElMessage.warning('请先选择种子材料 Excel 文件')
  imported.value = null
  busy.value = true
  try {
    const form = new FormData()
    form.append('file', file.value)
    form.append('mode', mode.value)
    form.append('taxon_decisions', JSON.stringify(taxonDecisions.value))
    preview.value = (await api.post<Preview>('/import/materials/preview', form)).data
    materialDecisions.value = {}
    confirmationSelection.value = []
    if (preview.value.already_imported) ElMessage.warning('这份文件已经成功导入过')
  } catch (error) {
    ElMessage.error(errorMessage(error))
  } finally {
    busy.value = false
  }
}
async function confirm() {
  if (!file.value || !canConfirm.value) return
  busy.value = true
  try {
    const form = new FormData()
    form.append('file', file.value)
    form.append('mode', mode.value)
    form.append('taxon_decisions', JSON.stringify(taxonDecisions.value))
    form.append('decisions', JSON.stringify(materialDecisions.value))
    imported.value = (await api.post('/import/materials/confirm', form)).data
    ElMessage.success(`清单已导入，本次新建材料 ${imported.value?.created_material_count} 份`)
    preview.value = null
    file.value = null
    if (input.value) input.value.value = ''
  } catch (error) {
    ElMessage.error(errorMessage(error))
  } finally {
    busy.value = false
  }
}
function createExperiment(scope: 'all' | 'created') {
  if (imported.value && saveMaterialPrefill(sessionStorage, imported.value, scope))
    router.push('/experiments/new')
}
</script>

<template>
  <section class="surface-panel integrated-import">
    <div class="panel-heading">
      <div class="data-card-icon">
        <el-icon><UploadFilled /></el-icon>
      </div>
      <div>
        <h2>导入种子材料清单</h2>
        <p>
          先核对物种，再核对这份种子材料；萌发试验历史分别按物种和材料显示。已有记录的不同信息会提示核对，不会自动覆盖。
        </p>
      </div>
    </div>
    <div class="integrated-import-actions">
      <el-button :icon="Download" @click="downloadTemplate">下载导入模板</el-button>
      <el-button :icon="Document" @click="input?.click()">选择材料清单</el-button>
      <input
        ref="input"
        type="file"
        accept=".xlsx"
        aria-label="选择材料清单"
        hidden
        @change="selectFile"
      />
      <el-button type="primary" :loading="busy" @click="preflight">预检材料</el-button>
    </div>
    <div class="import-mode">
      <strong>这张表是什么类型？</strong>
      <el-radio-group :model-value="mode" @update:model-value="changeMode">
        <el-radio value="complete">完整 / 更新后的材料清单</el-radio>
        <el-radio value="new">仅包含新增材料的清单</el-radio>
      </el-radio-group>
      <p>
        {{
          mode === 'complete'
            ? '表中可能包含以前登记过的材料，只新增或补全真正发生变化的部分。'
            : '表中主要是这次新获得的种子材料；无原始材料编号时倾向建立新批次。'
        }}
      </p>
    </div>
    <p v-if="file">当前文件：{{ file.name }}</p>
    <template v-if="preview">
      <el-alert
        v-if="preview.already_imported"
        title="这份文件已经成功导入过。若有新增材料，请上传更新后的完整清单。"
        type="warning"
        show-icon
        :closable="false"
      />
      <div class="import-stats">
        <span>清单 {{ preview.stats.total }} 行</span>
        <span
          >物种识别：已有 {{ preview.stats.taxon_existing }} 行 · 新增
          {{ preview.stats.taxon_new }} 行 · 需确认 {{ preview.stats.taxon_confirm }} 行</span
        >
        <span
          >材料识别：已有 {{ preview.stats.material_existing }} · 新增
          {{ preview.stats.material_new }} · 需确认 {{ preview.stats.material_confirm }} · 可补全
          {{ preview.stats.material_updatable }}</span
        >
        <span
          >物种萌发试验：有记录 {{ preview.stats.taxon_with_ger }} 行 · 无记录
          {{ preview.stats.taxon_without_ger }} 行</span
        >
        <span v-if="preview.stats.errors">需修正 {{ preview.stats.errors }} 行</span>
      </div>
      <p>
        物种与种子材料分别识别。同一物种可以有多份不同来源的材料；先确认物种，再核对材料。以上识别统计按清单行计算。
      </p>
      <div v-if="confirmationRows.length" class="wizard-bulk-actions">
        <el-button @click="selectAllConfirmations"
          >全选需要确认（{{ confirmationRows.length }}）</el-button
        >
        <el-button @click="confirmationSelection = []">取消全选</el-button>
        <span>已勾选 {{ confirmationSelection.length }} 行</span>
        <el-button @click="applyToSelected('reuse')">批量复用已有材料</el-button>
        <el-button @click="applyToSelected('new')">批量作为新材料</el-button>
        <el-button @click="applyToSelected('suggested')">按系统建议批量处理</el-button>
      </div>
      <el-table :data="preview.rows" max-height="520" row-key="line" empty-text="文件中没有材料">
        <el-table-column label="勾选" width="70"
          ><template #default="{ row }"
            ><el-checkbox
              v-if="row.material_status === 'confirm'"
              v-model="confirmationSelection"
              :value="row.line" /></template
        ></el-table-column>
        <el-table-column prop="line" label="Excel 行" width="95" />
        <el-table-column label="物种 / 材料" min-width="230">
          <template #default="{ row }"
            ><b>{{ row.name || row.scientific_name }}</b>
            <small class="table-subtitle"
              >{{ row.scientific_name }} · {{ row.source_code || '原始材料编号未填写' }} ·
              {{ row.source || '来源未填写' }}</small
            ></template
          >
        </el-table-column>
        <el-table-column label="物种识别" width="115"
          ><template #default="{ row }">
            <el-tag
              :type="
                row.taxon_status === 'confirm'
                  ? 'warning'
                  : row.taxon_status === 'error'
                    ? 'danger'
                    : 'info'
              "
              >{{ identityLabels[row.taxon_status as keyof typeof identityLabels] }}物种</el-tag
            >
          </template></el-table-column
        >
        <el-table-column label="材料识别" width="135"
          ><template #default="{ row }">
            {{ identityLabels[row.material_status as keyof typeof identityLabels]
            }}{{ ['existing', 'new'].includes(row.material_status) ? '材料' : '' }}
          </template></el-table-column
        >
        <el-table-column label="萌发试验历史（GER）" min-width="190"
          ><template #default="{ row }">
            <div>物种：{{ gerLabels[row.taxon_ger_status as keyof typeof gerLabels] }}</div>
            <div>本材料：{{ gerLabels[row.material_ger_status as keyof typeof gerLabels] }}</div>
          </template></el-table-column
        >
        <el-table-column label="说明" min-width="280">
          <template #default="{ row }">
            <div v-for="message in [...row.errors, ...row.warnings]" :key="message">
              {{ message }}
            </div>
            <div v-if="row.taxon_status === 'confirm'">
              新表学名：{{ row.scientific_name || '未填写' }}
            </div>
            <div v-if="row.candidate_row">
              第 {{ row.candidate_row }} 行可能是同一材料，请确认。
            </div>
            <div v-if="row.fills.length">将补全：{{ row.fills.join('、') }}</div>
            <div v-if="row.conflicts.length">
              信息不一致，本次不会自动覆盖：{{ row.conflicts.join('、') }}
            </div>
            <div v-if="row.material_status === 'confirm' && row.candidate_lots.length">
              找到 {{ row.candidate_lots.length }} 份疑似已有材料，请明确选择。
            </div>
          </template>
        </el-table-column>
        <el-table-column label="处理选择" min-width="300">
          <template #default="{ row }">
            <el-select
              v-if="row.taxon_status === 'confirm' || taxonDecisions[String(row.line)]"
              v-model="taxonDecisions[String(row.line)]"
              placeholder="请确认物种"
              :disabled="busy"
              @change="preflight"
            >
              <el-option
                v-for="taxon in row.taxon_candidates"
                :key="taxon.id"
                :label="`复用已有物种 ${taxon.code} · ${taxon.common_name || ''} · ${taxon.scientific_name}`"
                :value="`reuse:${taxon.id}`"
              />
              <el-option label="确认为新物种" value="new" />
            </el-select>
            <el-select
              :disabled="busy"
              v-if="row.material_status === 'confirm'"
              v-model="materialDecisions[String(row.line)]"
              placeholder="请选择"
            >
              <el-option
                v-if="row.candidate_row"
                :label="`复用第 ${row.candidate_row} 行`"
                :value="`reuse-row:${row.candidate_row}`"
              />
              <el-option
                v-for="lot in row.candidate_lots"
                :key="lot.id"
                :label="`复用 ${lot.code} · ${lot.source_code || lot.source || '来源未填写'}${lot.collected_at ? ' · ' + lot.collected_at.slice(0, 10) : ''} · ${historyLabel(lot.ger_status)}${lot.is_active ? '' : '（已停用）'}`"
                :value="`reuse:${lot.id}`"
              />
              <el-option label="作为另一份新材料" value="new" />
            </el-select>
          </template>
        </el-table-column>
      </el-table>
      <div class="integrated-import-actions">
        <el-button type="primary" :disabled="!canConfirm" :loading="busy" @click="confirm"
          >确认导入</el-button
        >
        <span v-if="preview.stats.errors">请先修正文件中的错误，再重新预检。</span>
        <span v-else-if="preview.stats.confirm && !canConfirm"
          >请先确认物种，再处理所有需要确认的材料。</span
        >
      </div>
    </template>
    <div v-if="imported" class="import-success">
      <h3>导入完成</h3>
      <p>
        本次清单共 {{ imported.total_material_count }} 份材料：{{
          imported.existing_material_count
        }}
        份沿用系统已有材料；本次新建材料 {{ imported.created_material_count }} 份；补全资料
        {{ imported.updated_material_count }} 份。
      </p>
      <p>下一步：进入创建实验向导，逐步确认实验方案。</p>
      <el-button
        type="primary"
        :disabled="!imported.all_seed_lot_ids.length"
        @click="createExperiment('all')"
        >使用本次全部材料创建实验</el-button
      >
      <el-button
        :disabled="!imported.created_seed_lot_ids.length"
        @click="createExperiment('created')"
        >仅使用本次新增材料创建实验</el-button
      >
      <p v-if="!imported.created_material_count">本次清单没有新增材料。</p>
    </div>
  </section>
</template>
