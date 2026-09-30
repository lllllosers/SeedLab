<script setup lang="ts">
import { reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api, errorMessage } from '../../api/client'
import type { GerminationExecution, GerminationObservation } from '../../types'
import { dateTimeText } from '../../utils'

const props = defineProps<{ execution: GerminationExecution }>()
const emit = defineEmits<{ changed: [] }>()
const editing = ref(false)
const saving = ref(false)
const form = reactive({ id: '', dishCode: '', count: 0, notes: '' })
function edit(observation: GerminationObservation) {
  Object.assign(form, {
    id: observation.id,
    dishCode: observation.field_number || observation.dish_code,
    count: observation.new_germinated_count,
    notes: observation.notes || '',
  })
  editing.value = true
}
async function save() {
  saving.value = true
  try {
    await api.patch(`/experiments/${props.execution.experiment.id}/observations/${form.id}`, {
      new_germinated_count: form.count,
      notes: form.notes.trim() || null,
    })
    editing.value = false
    ElMessage.success('巡检记录已修正')
    emit('changed')
  } catch (error) {
    ElMessage.error(errorMessage(error))
  } finally {
    saving.value = false
  }
}
async function remove(observation: GerminationObservation) {
  try {
    await ElMessageBox.confirm(
      `确定删除培养皿 ${observation.field_number || observation.dish_code} 在 ${dateTimeText(observation.observed_at)} 的巡检吗？删除后发芽累计数会重新计算。`,
      '删除巡检记录',
    )
  } catch {
    return
  }
  try {
    await api.delete(`/experiments/${props.execution.experiment.id}/observations/${observation.id}`)
    ElMessage.success('巡检记录已删除')
    emit('changed')
  } catch (error) {
    ElMessage.error(errorMessage(error))
  }
}
</script>
<template>
  <div class="execution-section-head">
    <div>
      <h3>最近巡检记录</h3>
      <p>显示最近 100 次巡检；已选出幼苗的巡检不能删除。</p>
    </div>
    <span class="history-count">{{ execution.recent_observations.length }} 条</span>
  </div>
  <div v-if="execution.recent_observations.length" class="execution-table-wrap">
    <table class="execution-table">
      <thead>
        <tr>
          <th>巡检时间</th>
          <th>培养皿</th>
          <th>本次新增</th>
          <th>产生样本</th>
          <th>备注</th>
          <th>操作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="observation in execution.recent_observations" :key="observation.id">
          <td>{{ dateTimeText(observation.observed_at) }}</td>
          <td>
            <b>{{ observation.field_number || observation.dish_code }}</b>
          </td>
          <td>
            <strong>{{ observation.new_germinated_count }}</strong>
          </td>
          <td>{{ observation.generated_sample_count }}</td>
          <td>{{ observation.notes || '—' }}</td>
          <td>
            <el-button
              v-if="execution.experiment.status !== 'cancelled'"
              link
              type="primary"
              @click="edit(observation)"
              >修正</el-button
            ><el-button
              v-if="execution.experiment.status !== 'cancelled'"
              link
              type="danger"
              :disabled="observation.generated_sample_count > 0"
              @click="remove(observation)"
              >删除</el-button
            >
          </td>
        </tr>
      </tbody>
    </table>
  </div>
  <div v-else class="wizard-empty">
    当前实验还没有发芽巡检记录。检查培养皿后，填写本次新增发芽数并保存。
  </div>
  <el-dialog v-model="editing" title="修正巡检记录" width="480px"
    ><p class="execution-dialog-copy">
      {{ form.dishCode }} · 修改新增数后会重新校验累计与已选幼苗。已有样本不会被自动删除。
    </p>
    <el-form label-position="top"
      ><el-form-item label="本次新增发芽数"
        ><el-input-number
          v-model="form.count"
          :min="0"
          :precision="0"
          style="width: 100%" /></el-form-item
      ><el-form-item label="备注"
        ><el-input v-model="form.notes" type="textarea" :rows="3" /></el-form-item></el-form
    ><template #footer
      ><el-button @click="editing = false">取消</el-button
      ><el-button type="primary" :loading="saving" @click="save">保存修正</el-button></template
    ></el-dialog
  >
</template>
