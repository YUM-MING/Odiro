// 백엔드 계약: odiro/api/schemas.py 와 1:1. 바꾸면 docs/API_SCHEMA.md 도 같이.
import axios from 'axios'

// VITE_API_URL 이 비어 있으면 상대경로(/api) → vite proxy 또는 같은 도메인 rewrite 사용
const baseURL = import.meta.env.VITE_API_URL || ''

export const api = axios.create({ baseURL, timeout: 60_000 })

export type Mode = 'outing' | 'trip'
export type Transport = 'walk' | 'car'
export type LegTransport = 'walk' | 'transit' | 'car'

export const MOODS = [
  '감성/조용한',
  '힙한/트렌디',
  '뷰맛집/일몰',
  '레트로',
  '자연/산책',
  '실내(비오는날)',
  '액티비티',
  '사진맛집',
  '웨이팅적은',
  '아이동반',
  '반려동물',
] as const

export interface Health {
  status: string
  version: string
}

export interface ConfigCheck {
  ready: boolean
  missing: string[]
}

export interface PublicConfig {
  kakao_js_api_key: string
}

export interface CourseRequest {
  mode: Mode
  transport: Transport
  region: string
  date: string // YYYY-MM-DD
  start_time: string // HH:MM
  end_time: string
  days: number
  budget: number
  moods: string[]
  free_text: string
  party: string
  lodging?: string // 여행 모드: 이미 정한 숙소 이름 (선택)
}

export interface PlaceOut {
  order: number
  day: number
  name: string
  category: string
  lat: number
  lng: number
  address: string
  kakao_place_id: string
  place_url: string
  phone: string
  reason: string
  tags: string[]
  review_summary: string
  arrive: string
  stay_min: number
  image: string
  verified: boolean
  source: string
  est_cost?: number // 1인 예상 비용(원), 추정
  parking?: string // 자차: 가장 가까운 주차장
}

export interface LegOut {
  from_idx: number
  to_idx: number
  transport: LegTransport
  duration_min: number
  distance_m: number
  polyline: number[][] // [[lat, lng], ...]
  estimated: boolean
}

export interface WeatherOut {
  available: boolean
  summary: string
  temp_c: number | null
  pop: number | null
  rain: boolean
  note: string
}

export interface SunOut {
  sunrise: string
  sunset: string
}

export type TraceStatus = 'start' | 'done' | 'skip' | 'error'

export interface TraceStep {
  node: string
  status: TraceStatus
  ms: number
  detail: string
}

export interface CourseMeta {
  sun: SunOut
  weather: WeatherOut
  rag_docs: number
  web_docs: number
  warnings: string[]
  est_cost_total?: number // 1인 예상 비용 합계 (숙박비 제외, 추정)
  trace: TraceStep[]
  cached: boolean
  elapsed_ms: number
}

export interface CourseResponse {
  course_id: string
  request: CourseRequest
  title: string
  places: PlaceOut[]
  legs: LegOut[]
  answer_md: string
  meta: CourseMeta
}

export interface EditRequest {
  course: CourseResponse
  instruction: string
  target_order: number | null
  target_day: number
}

export interface JobStarted {
  job_id: string
  stream_url: string
}

export const getHealth = () => api.get<Health>('/api/health').then((r) => r.data)
export const getConfigCheck = () => api.get<ConfigCheck>('/api/config-check').then((r) => r.data)
export const getPublicConfig = () => api.get<PublicConfig>('/api/public-config').then((r) => r.data)
export const getMoods = () =>
  api
    .get<{ moods: string[] }>('/api/moods')
    .then((r) => r.data.moods)
    .catch(() => [...MOODS])

export const createCourse = (req: CourseRequest) =>
  api.post<CourseResponse>('/api/course', req).then((r) => r.data)
export const startCourse = (req: CourseRequest) =>
  api.post<JobStarted>('/api/course/start', req).then((r) => r.data)
export const editCourse = (req: EditRequest) =>
  api.post<CourseResponse>('/api/course/edit', req).then((r) => r.data)
export const startEdit = (req: EditRequest) =>
  api.post<JobStarted>('/api/course/edit/start', req).then((r) => r.data)

/** 네트워크 자체가 안 되는 오류(백엔드 미기동 등)인지. 이 경우에만 목 데이터로 폴백한다. */
export function isNetworkError(e: unknown): boolean {
  return axios.isAxiosError(e) && !e.response
}

export interface StreamHandlers {
  onProgress: (step: TraceStep) => void
  onResult: (course: CourseResponse) => void
  onError: (message: string) => void
}

/** SSE 구독. 반환된 함수로 닫는다. 첫 이벤트 전에 끊기면 onError('__before_first__') 를 준다. */
export function subscribeStream(streamUrl: string, h: StreamHandlers): () => void {
  const url = streamUrl.startsWith('http') ? streamUrl : `${baseURL}${streamUrl}`
  const es = new EventSource(url)
  let gotAny = false
  es.addEventListener('progress', (ev) => {
    gotAny = true
    h.onProgress(JSON.parse((ev as MessageEvent).data) as TraceStep)
  })
  es.addEventListener('result', (ev) => {
    gotAny = true
    h.onResult(JSON.parse((ev as MessageEvent).data) as CourseResponse)
    es.close()
  })
  es.addEventListener('error', (ev) => {
    // 서버가 보낸 error 이벤트(data 있음) vs 연결 오류(data 없음)
    const data = (ev as MessageEvent).data
    if (data) {
      try {
        h.onError((JSON.parse(data) as { message: string }).message)
      } catch {
        h.onError(String(data))
      }
      es.close()
      return
    }
    if (es.readyState === EventSource.CLOSED) {
      h.onError(gotAny ? '연결이 끊어졌어요.' : '__before_first__')
    }
  })
  return () => es.close()
}
