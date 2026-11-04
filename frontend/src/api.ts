import axios from 'axios'

// VITE_API_URL 이 비어 있으면 상대경로(/api) → vite proxy 또는 같은 도메인 rewrite 사용
const baseURL = import.meta.env.VITE_API_URL || ''

export const api = axios.create({ baseURL, timeout: 30_000 })

export interface Health {
  status: string
  version: string
}

export interface ConfigCheck {
  ready: boolean
  missing: string[]
}

export const getHealth = () => api.get<Health>('/api/health').then((r) => r.data)
export const getConfigCheck = () => api.get<ConfigCheck>('/api/config-check').then((r) => r.data)
