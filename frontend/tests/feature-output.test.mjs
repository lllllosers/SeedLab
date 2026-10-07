import assert from 'node:assert/strict'
import test from 'node:test'
import { readFileSync } from 'node:fs'
import { createHash } from 'node:crypto'

// Accepted AF-4 source blocks, captured before moves. Only the experiments
// action handler's internal type-aware navigation expression was normalized.
const expected = {
  "features/germination/pages/ExperimentWizardView.vue": "b4d1f18f64c77ec3e1970532c13e052aacf4bd0ad6b76280747a2dc3ff49e49f",
  "features/germination/pages/ExperimentDesignDetailView.vue": "b50691957f1c023b9041e83b6b5b1aa9c7fc3c325fc7b2c1b756f85ef85e8169",
  "features/germination/pages/GerminationExecutionView.vue": "603869b8c949ff6b769c20256089741f4969e6072fca0c8d5dc494fcfc95af02",
  "features/experiments/pages/ExperimentsView.vue": "d38e73524ad4f2a035c10cd7d6e06d15fb47f42680ffaaad1f9e8cfb852c2a62",
  "features/germination/components/creation/MaterialsStep.vue": "d099d04eb687f18bf9a64a01cf37183303c52b2477854fb1a391ccd27b7a434c",
  "features/germination/components/creation/OverridesStep.vue": "899a0cf408a9065b5251cf595e5814c886faeb4b0c96ac50a830dc4e4912e449",
  "features/germination/components/creation/ProtocolStep.vue": "f896212b5c9753070d13242af3efbe3420fbf0a26f6735b44d44a33f087dbd6c",
  "features/germination/components/creation/SamplingStep.vue": "c3db46069570bd6dc24a5e9092f8193236f9df0e5dcab921328fb52607b53613",
  "features/germination/components/creation/TimepointsStep.vue": "e1e6fb4a3cde2c526eff9f9da36ac7ac5712754f8c69ca72084c6eebd5021f07",
  "features/germination/components/DishStatusTable.vue": "04ec6481889e20f50fd4227827f6d0c86a04d13be456e9ddacf6ff6585283bf7",
  "features/germination/components/GerminationQuickEntry.vue": "658294f0466e1e4fb8ca82ac198d46fafb831b1bc7e5293856e81c616e357b61",
  "features/measurement/components/MeasurementEditDialog.vue": "dcf4513c03386c3d97e48cb0b3fdf19b5af68466293abff661e4f993b8d9cca0",
  "features/measurement/components/MeasurementEditor.vue": "cd8f6fe54d46d76bb80dfb0866ac2391a9fd9d28cec02ec60fb88dc561488a61",
  "features/measurement/components/MeasurementRecords.vue": "4fd8d35cd0f15d7ef49692f2f6736605f091091eef2470b0a8690e5638a9ac66",
  "features/measurement/components/MeasurementRecordsTable.vue": "e835a532a17e21da26e2525a5176423c759abbd1cc0c3058fa7429f6f26b933b",
  "features/germination/components/ObservationHistory.vue": "08d87120339c8a6735c269c6ed947d99ec0723b9f3279dee0ab8954b3c220495",
  "features/measurement/components/SeedlingMeasurementWorkbench.vue": "109526ce92b0c0e8803cc6bdfce5fcb45424bee34311352c10c40fa20fc8a6b0",
  "features/germination/components/SowingManagement.vue": "b0424a965cbfd97ba048b1058a4af1a2dec7cdc13a3be5b1c36088d277e0ca54",
  "shared/components/PageBackButton.vue": "afda8a17e6a99b9e7d1ee06238588b8d591a2fbf111053a1695e4104e507e9f2"
}

test('all moved page/component templates and styles preserve accepted output', () => {
  for (const [file, digest] of Object.entries(expected)) {
    const source = readFileSync(new URL('../src/' + file, import.meta.url), 'utf8')
    const rendered = source.includes('</script>') ? source.slice(source.indexOf('</script>') + 9) : source
    assert.equal(createHash('sha256').update(rendered).digest('hex'), digest, file)
  }
})
