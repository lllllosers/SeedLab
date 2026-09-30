<script setup lang="ts">
import { ref } from 'vue'
import type { ExperimentStatus, MeasurementTask } from '../../types'
import MeasurementEditor from './MeasurementEditor.vue'
const props = defineProps<{ task: MeasurementTask | null; status: ExperimentStatus }>()
const emit = defineEmits<{ close: []; changed: [] }>()
const editor = ref<{ confirmDiscard: () => Promise<boolean>; dirty: boolean } | null>(null)
async function close(done?: () => void) {
  if (!editor.value || (await editor.value.confirmDiscard())) {
    done?.()
    emit('close')
  }
}
async function confirmDiscard() {
  return !editor.value || (await editor.value.confirmDiscard())
}
function changed() { emit('changed'); emit('close') }
defineExpose({ confirmDiscard, dirty: () => editor.value?.dirty || false })
</script>
<template>
  <el-dialog
    :model-value="!!props.task"
    title="修改本阶段测定"
    width="760px"
    :before-close="close"
    :close-on-click-modal="false"
  >
    <MeasurementEditor
      v-if="task"
      ref="editor"
      :task="task"
      :status="status"
      @saved="changed"
      @cleared="changed"
    />
    <template #footer><el-button @click="close()">取消</el-button></template>
  </el-dialog>
</template>
