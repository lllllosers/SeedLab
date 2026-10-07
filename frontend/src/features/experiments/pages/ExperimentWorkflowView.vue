<script setup lang="ts">
import { computed, defineAsyncComponent, shallowRef, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { errorMessage } from '../../../shared/api/client'
import { getExperiment } from '../api'
import { resolveExperimentUi } from '../uiRegistry'
import UnavailableExperiment from '../components/UnavailableExperiment.vue'

const props = defineProps<{ mode: 'configuration' | 'execution' }>()
const route = useRoute()
const page = shallowRef<ReturnType<typeof defineAsyncComponent>>()
const unavailable = shallowRef(false)
const pageKey = computed(() => `${route.params.id}:${props.mode}`)
let sequence = 0
watch(() => [String(route.params.id), props.mode] as const, async ([id, mode]) => {
  const request = ++sequence
  page.value = undefined
  unavailable.value = false
  try {
    const { data } = await getExperiment(id)
    if (request !== sequence) return
    const ui = resolveExperimentUi(data.experiment_type)
    if (ui) page.value = defineAsyncComponent(ui[mode])
    else unavailable.value = true
  } catch (error) {
    if (request === sequence) ElMessage.error(errorMessage(error))
  }
}, { immediate: true })
</script>
<template>
  <component :is="page" v-if="page" :key="pageKey" />
  <UnavailableExperiment v-else-if="unavailable" />
</template>
