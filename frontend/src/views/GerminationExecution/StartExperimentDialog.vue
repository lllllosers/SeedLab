<script setup lang="ts">
import { ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { api, errorMessage } from '../../api/client'
import type { GerminationExecution, Workload } from '../../types'

const props = defineProps<{ experimentId: string; workload: Workload | null }>()
const emit = defineEmits<{ started: [execution: GerminationExecution] }>()
const open = defineModel<boolean>({ required: true })
const actualTime = ref('')
const saving = ref(false)
const pad = (value: number) => String(value).padStart(2, '0')
function localNow() {
  const date = new Date()
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}:00`
}
watch(open, (value) => {
  if (value) actualTime.value = localNow()
})
async function start() {
  const date = new Date(actualTime.value.replace(' ', 'T'))
  if (!actualTime.value || Number.isNaN(date.getTime()))
    return ElMessage.warning('请填写实际置床时间')
  saving.value = true
  try {
    const { data } = await api.post<GerminationExecution>(
      `/experiments/${props.experimentId}/start`,
      { sown_at: date.toISOString() },
    )
    open.value = false
    ElMessage.success('实验已开始，培养皿已生成')
    emit('started', data)
  } catch (error) {
    ElMessage.error(errorMessage(error))
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <el-dialog v-model="open" title="正式开始实验" width="520px">
    <p class="execution-dialog-copy">
      确认实际置床时间后，系统会一次生成全部培养皿并将实验设为进行中。培养皿数量随后固定。
    </p>
    <div v-if="workload" class="start-preview">
      <div>
        <small>实验材料</small><strong>{{ workload.material_count }}</strong>
      </div>
      <div>
        <small>预计培养皿</small><strong>{{ workload.estimated_dish_count }}</strong>
      </div>
      <div>
        <small>置床种子</small><strong>{{ workload.estimated_seed_count }}</strong>
      </div>
    </div>
    <el-form label-position="top"
      ><el-form-item label="实际置床时间"
        ><el-date-picker
          v-model="actualTime"
          type="datetime"
          value-format="YYYY-MM-DD HH:mm:ss"
          format="YYYY-MM-DD HH:mm"
          placeholder="选择实际置床日期和时间"
          style="width: 100%" /></el-form-item
    ></el-form>
    <p class="wizard-help">
      请填写实际完成置床的时间。种子批次登记的数量不会因开始实验而减少。
    </p>
    <template #footer
      ><el-button @click="open = false">取消</el-button
      ><el-button type="primary" :loading="saving" @click="start"
        >确认开始并生成培养皿</el-button
      ></template
    >
  </el-dialog>
</template>
