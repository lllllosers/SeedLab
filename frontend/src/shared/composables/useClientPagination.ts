import { computed, ref, watch, type ComputedRef } from 'vue'

export function useClientPagination<T>(items: ComputedRef<T[]>) {
  const page = ref(1)
  const pageSize = ref(50)
  const totalPages = computed(() => Math.max(1, Math.ceil(items.value.length / pageSize.value)))
  const pageItems = computed(() => items.value.slice((page.value - 1) * pageSize.value, page.value * pageSize.value))
  watch([items, pageSize], () => { page.value = Math.min(page.value, totalPages.value) })
  const resetPage = () => { page.value = 1 }
  return { page, pageSize, pageItems, totalPages, resetPage }
}
