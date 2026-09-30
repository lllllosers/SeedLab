import type { AvailableLot } from '../types'
import { orderedMaterials } from './materialSelection.ts'

export const MATERIAL_PREFILL_KEY = 'experiment-material-prefill'
export interface MaterialImportResult {
  all_seed_lot_ids: string[]
  created_seed_lot_ids: string[]
  total_material_count: number
  existing_material_count: number
  created_material_count: number
  updated_material_count: number
}
export interface MaterialPrefill {
  seed_lot_ids: string[]
  source: string
  created_at: string
}
export function saveMaterialPrefill(
  storage: Pick<Storage, 'setItem'>,
  result: MaterialImportResult,
  scope: 'all' | 'created',
) {
  const seed_lot_ids = [
    ...new Set(scope === 'all' ? result.all_seed_lot_ids : result.created_seed_lot_ids),
  ]
  if (!seed_lot_ids.length) return false
  storage.setItem(
    MATERIAL_PREFILL_KEY,
    JSON.stringify({
      seed_lot_ids,
      source: scope === 'all' ? '本次清单全部材料' : '本次清单新建材料',
      created_at: new Date().toISOString(),
    }),
  )
  return true
}
export function readMaterialPrefill(
  storage: Pick<Storage, 'getItem' | 'removeItem'>,
): MaterialPrefill | null {
  const raw = storage.getItem(MATERIAL_PREFILL_KEY)
  if (!raw) return null
  try {
    const value = JSON.parse(raw)
    if (
      !Array.isArray(value.seed_lot_ids) ||
      !value.seed_lot_ids.every((id: unknown) => typeof id === 'string') ||
      typeof value.source !== 'string' ||
      typeof value.created_at !== 'string' ||
      !Number.isFinite(Date.parse(value.created_at))
    )
      throw Error()
    return { ...value, seed_lot_ids: [...new Set<string>(value.seed_lot_ids)] }
  } catch {
    storage.removeItem(MATERIAL_PREFILL_KEY)
    return null
  }
}
export function resolveMaterialPrefill(prefill: MaterialPrefill, available: AvailableLot[]) {
  const wanted = new Set(prefill.seed_lot_ids)
  const lots = orderedMaterials(available.filter((lot) => wanted.has(lot.id)))
  return { lots, excluded: wanted.size - lots.length }
}
export function clearMaterialPrefill(storage: Pick<Storage, 'removeItem'>) {
  storage.removeItem(MATERIAL_PREFILL_KEY)
}
