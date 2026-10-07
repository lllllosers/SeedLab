import { api } from '../../shared/api/client'
import type { Experiment } from './types'

export interface ExperimentTypeOption { value: string; label: string }

export const getExperiment = (id: string) => api.get<Experiment>(`/experiments/${id}`)
export const getExperimentTypes = () => api.get<ExperimentTypeOption[]>('/experiments/types')
