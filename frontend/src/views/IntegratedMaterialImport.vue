<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { UploadFilled, Download, Document } from '@element-plus/icons-vue'
import { saveMaterialPrefill, type MaterialImportResult } from '../features/germination'
import { api, errorMessage } from '../shared/api/client'

import {
  displayCollectedDate,
  filterReviewRows,
  isNewMaterial,
  type ReviewFilter,
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
  experiment_selection_summary: {
    new_species_unique_count: number
    new_batch_unique_count: number
    pending_taxon_count: number
    pending_material_count: number
  }
}
const historyLabel = (status: GerStatus) => gerLabels[status]
const router = useRouter()
const file = ref<File | null>(null)
const input = ref<HTMLInputElement | null>(null)
const preview = ref<Preview | null>(null)
const materialDecisions = ref<Record<string, string>>({})
const taxonDecisions = ref<Record<string, string>>({})
const nameDecisions = ref<Record<string, string>>({})
const search = ref('')
const filter = ref<ReviewFilter>('all')
const reviewing = ref<number | null>(null)
const reviewRow = computed(() => preview.value?.rows.find((row) => row.line === reviewing.value))
const shownRows = computed(() =>
  filterReviewRows(preview.value?.rows || [], filter.value, search.value, materialDecisions.value),
)
const pendingRows = computed(
  () =>
    preview.value?.rows.filter(
      (row) => !reviewRowReady(row, materialDecisions.value[String(row.line)]),
    ) || [],
)
const suggestedRows = computed(() =>
  pendingRows.value.filter(
    (row) =>
      row.material_status === 'confirm' &&
      !row.candidate_row &&
      row.candidate_lots.length === 1 &&
      row.source &&
      row.source === row.candidate_lots[0]!.source &&
      row.candidate_lots[0]!.ger_status !== 'none',
  ),
)
const filters: { value: ReviewFilter; label: string }[] = [
  { value: 'all', label: '全部' },
  { value: 'pending', label: '只看待确认' },
  { value: 'new-species', label: '本次新增物种' },
  { value: 'existing-species', label: '历史已有物种' },
  { value: 'new-material', label: '本次新材料' },
  { value: 'history', label: '历史做过' },
]
function showFilter(value: ReviewFilter) {
  filter.value = value
  search.value = ''
}
function groupSize(row: PreviewRow) {
  const key = filter.value === 'species-plan' ? 'selection_species_group' : 'selection_batch_group'
  return preview.value?.rows.filter((item) => item[key] && item[key] === row[key]).length || 1
}
async function chooseMaterial(line: number, choice: string) {
  materialDecisions.value[String(line)] = choice
  await preflight()
}
async function chooseTaxon(line: number, choice: string) {
  taxonDecisions.value[String(line)] = choice
  delete materialDecisions.value[String(line)]
  await preflight()
}
async function acceptSuggestions() {
  try {
    await ElMessageBox.confirm(
      `将沿用 ${suggestedRows.value.length} 份同物种、同来源的历史材料。不会建立新批次；请确认它们确实是同一批种子。最终导入前仍可逐项修改。`,
      '核对历史材料',
      { confirmButtonText: '沿用这些历史材料', cancelButtonText: '取消', type: 'warning' },
    )
  } catch {
    return
  }
  for (const row of suggestedRows.value)
    materialDecisions.value[String(row.line)] = `reuse:${row.candidate_lots[0]!.id}`
  await preflight()
}
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
function changeMode(value: 'complete' | 'new') {
  mode.value = value
  imported.value = null
  preview.value = null
  materialDecisions.value = {}
  taxonDecisions.value = {}
  nameDecisions.value = {}
  filter.value = 'all'
  search.value = ''
}
function selectFile(event: Event) {
  file.value = (event.target as HTMLInputElement).files?.[0] || null
  preview.value = null
  imported.value = null
  materialDecisions.value = {}
  taxonDecisions.value = {}
  nameDecisions.value = {}
  filter.value = 'all'
  search.value = ''
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
    form.append('decisions', JSON.stringify(materialDecisions.value))
    preview.value = (await api.post<Preview>('/import/materials/preview', form)).data
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
    form.append('name_decisions', JSON.stringify(nameDecisions.value))
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
function materialHistory(row: PreviewRow): string {
  const choice = materialDecisions.value[String(row.line)]
  if (choice === 'new') return gerLabels.none
  if (choice?.startsWith('reuse:'))
    return gerLabels[
      row.candidate_lots.find((lot) => choice === `reuse:${lot.id}`)?.ger_status || 'pending'
    ]
  if (choice?.startsWith('reuse-row:')) {
    const other = preview.value?.rows.find((item) => String(item.line) === choice.slice(10))
    return other ? materialHistory(other) : gerLabels.pending
  }
  return gerLabels[row.material_ger_status]
}
function materialIsNew(row: PreviewRow): boolean {
  return isNewMaterial(preview.value?.rows || [], row, materialDecisions.value)
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
      <h3>本次实验筛选</h3>
      <p>
        先选择实验范围，再核对物种与这批种子的身份。历史试验指种子萌发试验；筛选数量会随确认选择更新。
      </p>
      <div class="selection-cards">
        <article>
          <h4>只做历史没做过的物种</h4>
          <strong
            >{{
              preview.experiment_selection_summary.new_species_unique_count
            }}
            个明确需要做的物种</strong
          >
          <p>另有 {{ preview.experiment_selection_summary.pending_taxon_count }} 个物种待确认</p>
          <el-button @click="showFilter('species-plan')">查看这些物种</el-button>
        </article>
        <article>
          <h4>同物种不同来源也单独做</h4>
          <strong
            >当前明确
            {{ preview.experiment_selection_summary.new_batch_unique_count }} 份种子材料</strong
          >
          <p>
            待确认物种 {{ preview.experiment_selection_summary.pending_taxon_count }} 项、材料
            {{ preview.experiment_selection_summary.pending_material_count }}
            项；确认后数量可能变化。
          </p>
          <el-button @click="showFilter('batch-plan')">查看这些材料</el-button>
        </article>
        <article>
          <h4>需要你处理</h4>
          <strong>{{ pendingRows.length }} 项</strong>
          <p>
            物种 {{ preview.experiment_selection_summary.pending_taxon_count }} 项、材料
            {{ preview.experiment_selection_summary.pending_material_count }} 项
          </p>
          <el-button @click="showFilter('pending')">立即处理</el-button>
        </article>
      </div>
      <details class="recognition-details">
        <summary>查看识别明细</summary>
        <p>以下是导入记录识别统计，不是最终实验数量。</p>
        <p>
          清单 {{ preview.stats.total }} 条；物种：历史已有
          {{ preview.stats.taxon_existing }}、本次新增 {{ preview.stats.taxon_new }}、待确认
          {{ preview.stats.taxon_confirm }}。
        </p>
        <p>
          材料：已有
          {{ preview.stats.material_existing + preview.stats.material_updatable }}、本次新增
          {{ preview.stats.material_new }}、待确认 {{ preview.stats.material_confirm }}、待物种确认
          {{ preview.stats.material_pending }}；可补全资料 {{ preview.stats.material_updatable }}。
        </p>
        <p>
          物种历史试验：有记录 {{ preview.stats.taxon_with_ger }}、没做过
          {{ preview.stats.taxon_without_ger }}、待确认 {{ preview.stats.taxon_confirm }}。
        </p>
      </details>
      <div v-if="suggestedRows.length" class="review-suggestions">
        <p>
          {{ suggestedRows.length }}
          项找到同物种、同来源的历史材料。核对后可一次沿用，其他项目仍需分别处理。
        </p>
        <el-button :disabled="busy" @click="acceptSuggestions">核对并沿用这些历史材料</el-button>
      </div>
      <el-input
        v-model="search"
        placeholder="搜索中文名、学名、来源或原始材料编号"
        clearable
        aria-label="搜索材料"
      />
      <div class="review-filters">
        <el-button
          v-for="item in filters"
          :key="item.value"
          :type="filter === item.value ? 'primary' : 'default'"
          @click="showFilter(item.value)"
          >{{ item.label }}</el-button
        >
      </div>
      <p v-if="filter === 'species-plan' || filter === 'batch-plan'">
        相同{{
          filter === 'species-plan' ? '物种' : '材料'
        }}只显示一份代表记录，标明清单中的记录数；最终导入仍核对整份清单。
      </p>
      <el-table
        :data="shownRows"
        max-height="560"
        row-key="line"
        empty-text="没有符合筛选的材料，请更换筛选条件或清空搜索。"
      >
        <el-table-column label="物种 / 来源" min-width="250"
          ><template #default="{ row }"
            ><b>{{ row.name || row.scientific_name }}</b
            ><small class="table-subtitle">{{ row.scientific_name }}</small>
            <div>来源：{{ row.source || '未填写' }}</div>
            <small
              >原始材料编号：{{ row.source_code || '未填写' }} · 清单第 {{ row.line }} 行</small
            >
            <p v-if="groupSize(row) > 1 && (filter === 'species-plan' || filter === 'batch-plan')">
              同一{{ filter === 'species-plan' ? '物种' : '材料' }}在清单中有
              {{ groupSize(row) }} 条记录
            </p></template
          ></el-table-column
        >
        <el-table-column label="物种状态" width="140"
          ><template #default="{ row }"
            ><el-tag
              :type="
                row.taxon_status === 'new'
                  ? 'success'
                  : row.taxon_status === 'existing'
                    ? 'info'
                    : 'warning'
              "
              :effect="row.taxon_status === 'new' ? 'dark' : 'plain'"
              >{{
                row.taxon_status === 'new'
                  ? '＋ 本次新增'
                  : row.taxon_status === 'existing'
                    ? '✓ 历史已有'
                    : '! 待确认'
              }}</el-tag
            ></template
          ></el-table-column
        >
        <el-table-column label="种子材料状态" width="160"
          ><template #default="{ row }"
            ><el-tag
              :type="
                materialIsNew(row)
                  ? 'success'
                  : reviewRowReady(row, materialDecisions[String(row.line)])
                    ? 'info'
                    : 'warning'
              "
              >{{
                materialIsNew(row)
                  ? '＋ 本次新材料'
                  : reviewRowReady(row, materialDecisions[String(row.line)])
                    ? '✓ 已有材料'
                    : '! 待确认'
              }}</el-tag
            ></template
          ></el-table-column
        >
        <el-table-column label="历史试验" width="170"
          ><template #default="{ row }"
            ><div>物种：{{ gerLabels[row.taxon_ger_status as GerStatus] }}</div>
            <div>本材料：{{ materialHistory(row) }}</div></template
          ></el-table-column
        >
        <el-table-column label="资料" min-width="180"
          ><template #default="{ row }"
            ><div v-if="row.fills.length">可补全：{{ row.fills.join('、') }}</div>
            <div v-if="row.conflicts.length">资料存在差异：{{ row.conflicts.join('、') }}</div>
            <div v-if="row.name_difference">名称不同：系统为“{{ row.system_common_name }}”</div>
            <div v-for="message in row.errors" :key="message">{{ message }}</div></template
          ></el-table-column
        >
        <el-table-column label="操作" width="145"
          ><template #default="{ row }"
            ><el-button :disabled="busy" @click="reviewing = row.line">{{
              row.taxon_status === 'confirm'
                ? '核对物种'
                : row.material_status === 'confirm'
                  ? '核对种子材料'
                  : '查看资料'
            }}</el-button></template
          ></el-table-column
        >
      </el-table>
      <p v-if="!pendingRows.length">✓ 所有需要确认的项目都已处理</p>
      <el-dialog
        :model-value="reviewing !== null"
        title="核对物种与种子材料"
        width="min(720px, 95vw)"
        @close="reviewing = null"
      >
        <template v-if="reviewRow">
          <h3>{{ reviewRow.name }}</h3>
          <p>{{ reviewRow.scientific_name }}</p>
          <p>
            来源：{{ reviewRow.source || '未填写' }} · 原始材料编号：{{
              reviewRow.source_code || '未填写'
            }}
          </p>
          <template
            v-if="reviewRow.taxon_status === 'confirm' || taxonDecisions[String(reviewRow.line)]"
          >
            <h4>先核对物种</h4>
            <p>新表：{{ reviewRow.name }} · {{ reviewRow.scientific_name }}</p>
            <p>系统不会自动判断植物分类学同义名，请根据材料资料明确选择。</p>
            <article
              v-for="taxon in reviewRow.taxon_candidates"
              :key="taxon.id"
              class="candidate-card"
            >
              <b>系统已有：{{ taxon.common_name }}</b>
              <p>{{ taxon.scientific_name }} · 历史试验：{{ historyLabel(taxon.ger_status) }}</p>
              <small>系统物种编号：{{ taxon.code }}</small>
              <p>
                <el-button
                  :disabled="busy"
                  @click="chooseTaxon(reviewRow.line, `reuse:${taxon.id}`)"
                  >使用系统已有物种</el-button
                >
              </p>
            </article>
            <el-button :disabled="busy" @click="chooseTaxon(reviewRow.line, 'new')"
              >确认为新的物种</el-button
            >
          </template>
          <template v-if="reviewRow.name_difference"
            ><h4>名称不同</h4>
            <p>系统当前名称：{{ reviewRow.system_common_name }}；新表名称：{{ reviewRow.name }}</p>
            <el-radio-group
              :model-value="nameDecisions[String(reviewRow.line)] || 'keep'"
              @update:model-value="
                (value: string | number | boolean | undefined) =>
                  (nameDecisions[String(reviewRow!.line)] = String(value))
              "
              ><el-radio value="keep">沿用系统名称“{{ reviewRow.system_common_name }}”</el-radio
              ><el-radio value="update" :disabled="!reviewRow.can_update_common_name"
                >更新系统名称为“{{ reviewRow.name }}”</el-radio
              ></el-radio-group
            >
            <p>仅在最终确认导入时更新中文名；物种编号、学名及历史实验保持不变。</p></template
          >
          <template v-if="reviewRow.material_status === 'confirm'">
            <h4>再核对这批种子</h4>
            <article v-if="reviewRow.candidate_row" class="candidate-card">
              <b>清单中另一条可能是同一材料</b
              ><template
                v-for="other in preview.rows.filter(
                  (item) => item.line === reviewRow!.candidate_row,
                )"
                :key="other.line"
                ><p>{{ other.name }} · {{ other.scientific_name }}</p>
                <p>来源：{{ other.source || '未填写' }}</p>
                <p>原始材料编号：{{ other.source_code || '未填写' }}</p>
                <small>清单第 {{ other.line }} 行</small></template
              >
              <p>
                <el-button
                  :disabled="busy"
                  @click="chooseMaterial(reviewRow.line, `reuse-row:${reviewRow.candidate_row}`)"
                  >合并为同一份材料</el-button
                >
              </p>
            </article>
            <article v-for="lot in reviewRow.candidate_lots" :key="lot.id" class="candidate-card">
              <b>可能相同的历史材料：{{ reviewRow.system_common_name || reviewRow.name }}</b>
              <p>来源：{{ lot.source || '未填写' }}</p>
              <p>原始材料编号：{{ lot.source_code || '未填写' }}</p>
              <p>采集 / 获得日期：{{ displayCollectedDate(lot.collected_at) }}</p>
              <p>
                历史试验：{{ historyLabel(lot.ger_status)
                }}{{ lot.is_active ? '' : '（材料已停用）' }}
              </p>
              <small>系统编号：{{ lot.code }}</small>
              <p>
                <el-button
                  :disabled="busy"
                  @click="chooseMaterial(reviewRow.line, `reuse:${lot.id}`)"
                  >使用这份已有材料</el-button
                >
              </p>
            </article>
            <el-button :disabled="busy" @click="chooseMaterial(reviewRow.line, 'new')">{{
              reviewRow.candidate_row ? '保留为两份不同材料' : '这是另一份新材料'
            }}</el-button>
            <p v-if="materialDecisions[String(reviewRow.line)]">本项已选择，可在最终导入前更改。</p>
          </template>
          <p v-if="reviewRow.fills.length">可补全：{{ reviewRow.fills.join('、') }}</p>
          <p v-if="reviewRow.conflicts.length">
            资料存在差异：{{
              reviewRow.conflicts.join('、')
            }}；除明确选择更新中文名外，不覆盖已有资料。
          </p>
        </template>
        <template #footer><el-button @click="reviewing = null">返回清单</el-button></template>
      </el-dialog>
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

<style scoped>
.selection-cards {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
  gap: 16px;
  margin: 18px 0;
}
.selection-cards article,
.candidate-card {
  border: 1px solid #dce7df;
  border-radius: 12px;
  padding: 16px;
  background: #f7faf7;
}
.selection-cards h4 {
  margin: 0 0 14px;
}
.selection-cards strong {
  font-size: 1.1rem;
  color: #275b43;
}
.selection-cards p,
.recognition-details p {
  color: #53665b;
  line-height: 1.6;
}
.recognition-details {
  margin: 18px 0;
}
.recognition-details summary {
  cursor: pointer;
}
.review-filters {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin: 14px 0;
}
.review-filters :deep(.el-button) {
  margin-left: 0;
}
.candidate-card {
  margin: 14px 0;
}
.candidate-card p {
  margin: 8px 0;
}
small {
  display: block;
  color: #6d7d74;
  line-height: 1.6;
}
</style>
