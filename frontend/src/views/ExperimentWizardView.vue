<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { onBeforeRouteLeave, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api, errorMessage } from '../api/client'
import { useAuth } from '../stores/auth'
import type {
  AvailableLot,
  ExperimentConfiguration,
  ExperimentMaterialInput,
  ExperimentProtocol,
  Workload,
} from '../types'
import MaterialsStep from './ExperimentWizard/MaterialsStep.vue'
import ProtocolStep from './ExperimentWizard/ProtocolStep.vue'
import SamplingStep from './ExperimentWizard/SamplingStep.vue'
import TimepointsStep from './ExperimentWizard/TimepointsStep.vue'
import OverridesStep from './ExperimentWizard/OverridesStep.vue'
import PageBackButton from '../components/PageBackButton.vue'
import {
  readMaterialPrefill,
  resolveMaterialPrefill,
  clearMaterialPrefill,
} from '../utils/materialPrefill'
import { effectiveMaterial } from '../utils/effectiveMaterial'

const router = useRouter()
const auth = useAuth()
const step = ref(0)
const saving = ref(false)
const estimate = ref<Workload | null>(null)
const steps = [
  '基本信息',
  '实验材料',
  '培养皿与重复',
  '幼苗取样',
  '发芽后测定时间',
  '特殊材料',
  '检查与创建',
]
const experimentTypes = ref<{ value: string; label: string }[]>([])
const form = reactive({ experiment_type: '', name: '', description: '', planned_start_date: '' })
const lots = ref<AvailableLot[]>([])
const materials = ref<ExperimentMaterialInput[]>([])
const reviewMaterials = computed(() =>
  materials.value.map((entry, index) => ({
    entry,
    lot: lots.value[index],
    values: effectiveMaterial(entry, protocol.value),
  })),
)
const dagDays = ref<number[]>([3, 7, 14])
const protocol = ref<ExperimentProtocol>({
  seeds_per_dish: 20,
  replicate_count: 3,
  observation_period_days: 14,
  sampling_rule: 'first_germinated',
  sample_count: 5,
  sample_scope: 'per_dish',
  germination_criterion: '',
  summary: null,
})
watch(lots, (current) => {
  const old = new Map(materials.value.map((item) => [item.seed_lot_id, item]))
  materials.value = current.map(
    (lot) =>
      old.get(lot.id) || {
        seed_lot_id: lot.id,
        label: null,
        seeds_per_dish_override: null,
        replicate_count_override: null,
        sample_count_override: null,
      },
  )
})
const prefillSource = ref('')
const created = ref(false)
onMounted(async () => {
  try {
    experimentTypes.value = (await api.get('/experiments/types')).data
    form.experiment_type = experimentTypes.value[0]?.value || ''
  } catch (error) {
    ElMessage.error(errorMessage(error))
  }
  const prefill = readMaterialPrefill(sessionStorage)
  if (!prefill) return
  try {
    const available = (await api.get<AvailableLot[]>('/experiments/available-seed-lots')).data
    const resolved = resolveMaterialPrefill(prefill, available)
    lots.value = resolved.lots
    prefillSource.value = prefill.source
    if (resolved.excluded)
      ElMessage.warning(`有 ${resolved.excluded} 份材料当前不可用于实验，已从预选中移除。`)
  } catch (error) {
    ElMessage.error(errorMessage(error))
  }
})
onBeforeRouteLeave(async () => {
  if (created.value || !readMaterialPrefill(sessionStorage)) return true
  try {
    await ElMessageBox.confirm(
      '离开后将清除本次导入带入的预选材料。是否退出创建实验？',
      '退出并清除预选材料',
      { confirmButtonText: '退出并清除', cancelButtonText: '继续创建', type: 'warning' },
    )
    clearMaterialPrefill(sessionStorage)
    return true
  } catch {
    return false
  }
})
function payload() {
  return {
    experiment_type: form.experiment_type,
    name: form.name.trim(),
    description: form.description.trim() || null,
    planned_start_date: form.planned_start_date || null,
    protocol: {
      ...protocol.value,
      germination_criterion: protocol.value.germination_criterion.trim(),
    },
    materials: materials.value,
    dag_days: dagDays.value,
  }
}
function validCurrent(): boolean {
  if (step.value === 0 && !form.experiment_type) return warn('请先选择实验类型；列表未加载时请刷新后重试')
  if (step.value === 0 && form.name.trim().length < 2) return warn('请填写至少 2 个字的实验名称')
  if (step.value === 1 && !lots.value.length) return warn('请至少选择一个种子批次')
  if (
    step.value === 2 &&
    (!protocol.value.seeds_per_dish ||
      !protocol.value.replicate_count ||
      !protocol.value.observation_period_days ||
      !protocol.value.germination_criterion.trim())
  )
    return warn('请填写完整且大于 0 的默认方案与发芽判定标准')
  if (step.value === 3 && (!protocol.value.sample_count || protocol.value.sample_count < 1))
    return warn('取样数 N 必须大于 0')
  if (step.value === 4 && !dagDays.value.length) return warn('请至少添加一个 DAG 时间点')
  return true
}
function warn(message: string): false {
  ElMessage.warning(message)
  return false
}
async function next() {
  if (!validCurrent()) return
  if (step.value === 5) {
    try {
      estimate.value = (await api.post<Workload>('/experiments/estimate', payload())).data
    } catch (error) {
      ElMessage.error(errorMessage(error))
      return
    }
  }
  step.value++
}
async function create() {
  saving.value = true
  try {
    const { data } = await api.post<ExperimentConfiguration>('/experiments/configured', payload())
    created.value = true
    clearMaterialPrefill(sessionStorage)
    ElMessage.success('完整实验方案已保存')
    router.push(`/experiments/${data.experiment.id}`)
  } catch (error) {
    ElMessage.error(errorMessage(error))
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <PageBackButton to="/experiments" label="返回实验列表" />
  <div class="wizard-header">
    <div>
      <div class="eyebrow">创建实验 · 第 {{ step + 1 }} 步，共 7 步</div>
      <h1>{{ form.name || '创建实验' }}</h1>
      <p>
        第 {{ step + 1 }} 步：{{ steps[step] }} · 负责人 {{ auth.user?.display_name || '当前用户' }}
      </p>
    </div>
    <div class="wizard-progress">
      <strong>{{ Math.round(((step + 1) / steps.length) * 100) }}%</strong><span>配置进度</span>
    </div>
  </div>
  <el-progress
    :percentage="Math.round(((step + 1) / steps.length) * 100)"
    :show-text="false"
    :stroke-width="5"
    class="wizard-bar"
  />
  <p v-if="prefillSource" class="wizard-help">
    已预选{{ prefillSource }}的 {{ lots.length }} 份材料。请按 7
    步逐项确认，可在实验材料步骤移除或补加。
  </p>
  <div class="wizard-layout">
    <aside class="wizard-nav surface-panel">
      <button
        v-for="(title, index) in steps"
        :key="title"
        :class="{ active: step === index, done: step > index }"
        @click="index < step && (step = index)"
      >
        <span>{{ index + 1 }}</span
        >{{ title }}
      </button>
    </aside>
    <main class="surface-panel wizard-main">
      <template v-if="step === 0"
        ><div class="wizard-step-copy">
          <h2>实验基本信息</h2>
          <p>为这次具体实验命名。负责人默认是当前登录用户。</p>
          <p>
            建议按实验类型、日期、顺序号命名，也可按研究内容自定义。例如：种子萌发试验-202609-01，或盐胁迫下披碱草种子萌发试验。
          </p>
        </div>
        <el-form label-position="top"
          ><el-form-item label="实验类型">
            <el-select v-model="form.experiment_type" placeholder="请选择实验类型">
              <el-option
                v-for="item in experimentTypes"
                :key="item.value"
                :label="item.label"
                :value="item.value"
              />
            </el-select> </el-form-item
          ><el-form-item label="实验名称"
            ><el-input
              v-model="form.name"
              maxlength="255"
              show-word-limit
              placeholder="例如：温度梯度对种子萌发的影响" /></el-form-item
          ><el-form-item label="实验说明"
            ><el-input
              v-model="form.description"
              type="textarea"
              :rows="4"
              placeholder="研究目的、材料背景或设计依据" /></el-form-item
          ><el-form-item label="计划开始日期"
            ><el-date-picker
              v-model="form.planned_start_date"
              type="date"
              value-format="YYYY-MM-DD"
              placeholder="可选，填写计划开始日期" /></el-form-item></el-form
      ></template>
      <MaterialsStep v-else-if="step === 1" v-model="lots" />
      <ProtocolStep v-else-if="step === 2" v-model="protocol" />
      <SamplingStep v-else-if="step === 3" v-model="protocol" />
      <TimepointsStep v-else-if="step === 4" v-model="dagDays" />
      <OverridesStep v-else-if="step === 5" v-model="materials" :lots="lots" :protocol="protocol" />
      <template v-else
        ><div class="wizard-step-copy">
          <h2>检查并创建实验</h2>
          <p>确认下面的材料、实际使用参数与预计工作量。创建后仍可在实验开始前调整配置。</p>
        </div>
        <div class="review-grid">
          <div>
            <small>实验材料</small><strong>{{ estimate?.material_count }}</strong>
          </div>
          <div>
            <small>预计培养皿</small><strong>{{ estimate?.estimated_dish_count }}</strong>
          </div>
          <div>
            <small>预计置床种子</small><strong>{{ estimate?.estimated_seed_count }}</strong>
          </div>
          <div>
            <small>预计幼苗样本</small><strong>{{ estimate?.estimated_sample_count }}</strong>
          </div>
          <div>
            <small>预计测定记录</small><strong>{{ estimate?.estimated_measurement_count }}</strong>
          </div>
        </div>
        <div class="review-section">
          <h3>{{ form.name }}</h3>
          <p>
            实验类型：{{
              experimentTypes.find((item) => item.value === form.experiment_type)?.label
            }}
          </p>
          <p>{{ form.description || '暂无实验说明' }}</p>
          <p>
            计划开始：{{ form.planned_start_date || '未设置' }} · 负责人：{{
              auth.user?.display_name
            }}
          </p>
        </div>
        <div class="review-section">
          <h3>默认方案</h3>
          <p>
            每皿 {{ protocol.seeds_per_dish }} 粒 · 每材料 {{ protocol.replicate_count }} 次重复 ·
            观察 {{ protocol.observation_period_days }} 天
          </p>
          <p>
            按发芽顺序取前 {{ protocol.sample_count }} 株，{{
              protocol.sample_scope === 'per_dish' ? '每个培养皿' : '每个实验材料合计'
            }}
            · 判定：{{ protocol.germination_criterion }}
          </p>
        </div>
        <div class="review-section">
          <h3>材料与发芽后测定时间（DAG）</h3>
          <div
            v-for="item in reviewMaterials"
            :key="item.entry.seed_lot_id"
            class="review-material"
          >
            <div>
              <b>{{ item.lot?.taxon_common_name || item.lot?.taxon_scientific_name }}</b>
              <small v-if="item.lot?.taxon_common_name">{{
                item.lot?.taxon_scientific_name
              }}</small>
              <small>{{ item.lot?.code }}</small>
            </div>
            <span
              >每皿 {{ item.values.seedsPerDish }} 粒 · 重复 {{ item.values.replicateCount }} 次 ·
              取样 {{ item.values.sampleCount }} 株</span
            >
          </div>
          <div class="dag-chips">
            <el-tag v-for="day in dagDays" :key="day">DAG {{ day }}</el-tag>
          </div>
        </div>
      </template>
      <div class="wizard-footer">
        <el-button :disabled="step === 0" @click="step--">上一步</el-button
        ><el-button v-if="step < 6" type="primary" @click="next">下一步</el-button
        ><el-button v-else type="primary" :loading="saving" @click="create">创建实验</el-button>
      </div>
    </main>
  </div>
</template>
