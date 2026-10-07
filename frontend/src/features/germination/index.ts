export type * from './types'
export { saveMaterialPrefill } from './utils/materialPrefill.ts'
export type { MaterialImportResult } from './utils/materialPrefill.ts'

// Bundle rendering capabilities only; business types and lifecycle stay backend-owned.
export const germinationUi = Object.freeze({
  code: 'GER',
  label: '种子萌发试验',
  create: () => import('./pages/ExperimentWizardView.vue'),
  configuration: () => import('./pages/ExperimentDesignDetailView.vue'),
  execution: () => import('./pages/GerminationExecutionView.vue'),
  executionPath: (id: string) => `/experiments/${id}/germination`,
})
