import type { AvailableLot } from '../index'

export function orderedMaterials(items: AvailableLot[]): AvailableLot[] {
  return [...new Map(items.map((lot) => [lot.id, lot])).values()].sort(
    (a, b) => a.sort_rank - b.sort_rank,
  )
}
export function selectedMaterialPage(items: AvailableLot[], page: number, size: number) {
  return orderedMaterials(items)
    .slice((page - 1) * size, page * size)
    .map((lot, index) => ({
      lot,
      number: String((page - 1) * size + index + 1).padStart(3, '0'),
    }))
}
