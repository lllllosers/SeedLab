import assert from 'node:assert/strict'
import test from 'node:test'
import { computed, nextTick, ref } from 'vue'
import { useClientPagination } from '../src/composables/useClientPagination.ts'

test('filter and sort complete results before pagination', async () => {
  const source = ref(Array.from({ length: 120 }, (_, index) => ({ name: `材料${String(index + 1).padStart(3, '0')}` })))
  const search = ref('')
  const descending = ref(false)
  const visible = computed(() => source.value
    .filter((item) => item.name.includes(search.value))
    .sort((left, right) => descending.value ? right.name.localeCompare(left.name) : left.name.localeCompare(right.name)))
  const { page, pageSize, pageItems, totalPages, resetPage } = useClientPagination(visible)

  assert.equal(pageSize.value, 50)
  assert.equal(totalPages.value, 3)
  page.value = 3
  assert.deepEqual(pageItems.value.map((item) => item.name), source.value.slice(100).map((item) => item.name))

  search.value = '材料01'
  resetPage()
  await nextTick()
  assert.equal(visible.value.length, 10)
  assert.equal(totalPages.value, 1)
  assert.equal(pageItems.value[0].name, '材料010')

  descending.value = true
  assert.equal(pageItems.value[0].name, '材料019')
  pageSize.value = 25
  search.value = ''
  await nextTick()
  assert.equal(totalPages.value, 5)
  assert.equal(pageItems.value.length, 25)
  assert.equal(pageItems.value[0].name, '材料120')
})
