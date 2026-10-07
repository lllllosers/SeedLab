<script setup lang="ts">
import { defineAsyncComponent, onMounted, shallowRef } from 'vue'
import { ElMessage } from 'element-plus'
import { errorMessage } from '../../../shared/api/client'
import { getExperimentTypes } from '../api'
import type { ExperimentTypeOption } from '../api'
import { resolveExperimentUi } from '../uiRegistry'
import UnavailableExperiment from '../components/UnavailableExperiment.vue'

const types = shallowRef<ExperimentTypeOption[]>([])
const page = shallowRef<ReturnType<typeof defineAsyncComponent>>()
const unavailable = shallowRef(false)
function selectType(code: string) {
  const ui = resolveExperimentUi(code)
  // Keep the active wizard instance for the same supported type.
  if (!ui) { page.value = undefined; unavailable.value = true }
}
onMounted(async () => {
  try {
    types.value = (await getExperimentTypes()).data
    const ui = resolveExperimentUi(types.value[0]?.value || '')
    if (ui) page.value = defineAsyncComponent(ui.create)
    else unavailable.value = true
  } catch (error) {
    ElMessage.error(errorMessage(error))
  }
})
</script>
<template>
  <component :is="page" v-if="page" :experiment-types="types" @type-selected="selectType" />
  <UnavailableExperiment v-else-if="unavailable" />
</template>
