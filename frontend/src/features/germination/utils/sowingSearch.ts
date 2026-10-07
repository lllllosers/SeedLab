export function sowingSearchMatches(
  material: {
    experiment_number: number | null
    preview_number: number
    taxon_common_name: string | null
    taxon_scientific_name: string
    seed_lot_code: string
    source_code: string | null
  },
  dishes: Array<{ field_number: string | null }>,
  search: string,
) {
  const term = search.trim().toLocaleLowerCase()
  return (
    !term ||
    [
      String(material.experiment_number || material.preview_number).padStart(3, '0'),
      ...dishes.map((dish) => dish.field_number),
      material.taxon_common_name,
      material.taxon_scientific_name,
      material.seed_lot_code,
      material.source_code,
    ].some((value) => value?.toLocaleLowerCase().includes(term))
  )
}
