import { germinationUi } from '../germination/index.ts'

// Static public feature composition, without registration or a default type.
export const experimentUiRegistry = Object.freeze({ GER: germinationUi })

export function resolveExperimentUi(code: string) {
  return Object.hasOwn(experimentUiRegistry, code)
    ? experimentUiRegistry[code as keyof typeof experimentUiRegistry]
    : undefined
}
