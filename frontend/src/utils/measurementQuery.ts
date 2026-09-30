/** Query controls never contain or validate measurement edit values. */
export interface MeasurementQuery {
  search: string
  dag: number | string | null | undefined
  dates: string[] | null
  materialIds: string[]
  page: number
  pageSize: number
}
export function normalizedDag(value: MeasurementQuery['dag']): number | null {
  return typeof value === 'number' && Number.isInteger(value) && value >= 0 ? value : null
}
export function measurementQueryParams(query: MeasurementQuery): URLSearchParams {
  const params = new URLSearchParams({
    page: String(query.page),
    page_size: String(query.pageSize),
  })
  if (query.search.trim()) params.set('q', query.search.trim())
  const day = normalizedDag(query.dag)
  if (day !== null) params.set('dag', String(day))
  query.materialIds.forEach((id) => params.append('material_ids', id))
  if (query.dates?.length === 2 && query.dates.every(Boolean)) {
    params.set('date_from', query.dates[0]!)
    params.set('date_to', query.dates[1]!)
  }
  return params
}
