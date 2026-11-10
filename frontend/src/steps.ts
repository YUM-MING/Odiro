import type { TraceStatus } from './api'

export interface StepState {
  node: string
  status: TraceStatus | 'pending'
  ms: number
  detail: string
}

export function initialSteps(nodes: readonly string[]): StepState[] {
  return nodes.map((node) => ({ node, status: 'pending', ms: 0, detail: '' }))
}
