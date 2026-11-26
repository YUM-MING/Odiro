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
  day_starts?: Record<number, string> // 날짜별 시작 시각 {day: HH:MM}. 채팅으로 시작 시간을 바꾸면 서버가 채운다
  days: number
  budget: number
  moods: string[]
  free_text: string
  party: string
  headcount: number // 총 인원(본인 포함). 예산은 1인 기준, 전체 = budget × headcount
  lodging?: string // 여행 모드: 이미 정한 숙소 이름 (선택)
}

export interface IntroOut {
  rest_date: string // 쉬는 날
  use_time: string // 이용시간
  use_fee: string // 이용요금
  parking: string // 주차 가능 여부
  parking_fee: string // 주차요금
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
  intro?: IntroOut | null // TourAPI 이용 정보 (있는 장소만)
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

/** GET /api/daily-pick — 오늘의 숨은 여행지 (TourAPI 관광지 한 곳, 날짜마다 고정) */
export interface DailyPick {
  date: string // YYYY-MM-DD (KST)
  content_id: string
  name: string
  sido: string // 예) 경북
  sigungu: string // 예) 경주시 (세종처럼 없으면 빈 문자열)
  region: string // 조건 빌더에 넣을 지역 문자열. 예) "경북 경주시"
  description: string
  image: string // https
  lat: number
  lng: number
  kakao_map_url: string
  source: string
}

/** date: 한국 날짜 YYYY-MM-DD. 후보가 없으면 404 → 호출한 쪽에서 배너를 숨긴다 */
export const getDailyPick = (date: string) =>
  api.get<DailyPick>('/api/daily-pick', { params: { date } }).then((r) => r.data)

/** timeout: Cloud Run 콜드스타트(최소 인스턴스 0)로 첫 응답이 늦을 수 있어 랜딩 확인은 넉넉히 준다 */
export const getHealth = (timeout = 60_000) => api.get<Health>('/api/health', { timeout }).then((r) => r.data)
export const getConfigCheck = () => api.get<ConfigCheck>('/api/config-check').then((r) => r.data)
export const getPublicConfig = () => api.get<PublicConfig>('/api/public-config').then((r) => r.data)
export const getMoods = () =>
  api
    .get<{ moods: string[] }>('/api/moods')
    .then((r) => r.data.moods)
    .catch(() => [...MOODS])

/**
 * 동기 생성·수정(SSE 가 첫 이벤트 전에 끊겼을 때의 대체 요청) 타임아웃.
 * 서버가 90초(odiro/api/main.py SYNC_TIMEOUT_SEC)에 "너무 오래 걸립니다"(503)로 끊으므로 그보다 약간 길게 둬서
 * 서버의 안내를 받게 한다. SSE 전체 상한(STREAM_TOTAL_TIMEOUT_MS)은 스트림이 끝난 뒤 이 요청이 시작되므로 겹치지 않는다.
 */
export const SYNC_REQUEST_TIMEOUT_MS = 100_000

/** refresh=true: 서버의 7일 결과 캐시를 건너뛰고 새로 만든다 ('다시 만들기') */
export const createCourse = (req: CourseRequest, refresh = false) =>
  api
    .post<CourseResponse>('/api/course', req, { params: refresh ? { refresh: true } : undefined, timeout: SYNC_REQUEST_TIMEOUT_MS })
    .then((r) => r.data)
export const startCourse = (req: CourseRequest, refresh = false) =>
  api.post<JobStarted>('/api/course/start', req, { params: refresh ? { refresh: true } : undefined }).then((r) => r.data)
export const editCourse = (req: EditRequest) =>
  api.post<CourseResponse>('/api/course/edit', req, { timeout: SYNC_REQUEST_TIMEOUT_MS }).then((r) => r.data)
export const startEdit = (req: EditRequest) =>
  api.post<JobStarted>('/api/course/edit/start', req).then((r) => r.data)

/** 네트워크 자체가 안 되는 오류(백엔드 미기동·연결 거부 등)인지 */
export function isNetworkError(e: unknown): boolean {
  return axios.isAxiosError(e) && !e.response
}

// ---------- 사용자에게 보여 줄 오류 문구 ----------

export const MSG_CONNECT = '서버에 연결할 수 없어요. 잠시 후 다시 시도해 주세요.'
export const MSG_TIMEOUT = '코스를 만드는 데 너무 오래 걸리고 있어요. 다시 시도해 주세요.'
export const MSG_DISCONNECTED = '서버와 연결이 끊어졌어요. 다시 시도해 주세요.'
export const MSG_GENERIC = '잠시 후 다시 시도해 주세요.'

/** 한글 문장이고 영어 단어·코드(예외 이름, URL, 키 이름)가 섞이지 않은 문구만 사용자용으로 본다 */
function isUserFacing(msg: string): boolean {
  return /[가-힣]/.test(msg) && !/[A-Za-z_]{3,}/.test(msg)
}

/** 요청·스트림 오류 → 사용자 문구. 원래 기술 메시지는 콘솔에만 남긴다 */
export function toUserMessage(e: unknown): string {
  console.error('[odiro] 요청 실패:', e)
  if (axios.isAxiosError(e)) {
    if (e.code === 'ECONNABORTED' || e.code === 'ETIMEDOUT') return MSG_TIMEOUT
    if (!e.response) return MSG_CONNECT
    const detail = (e.response.data as { detail?: unknown } | undefined)?.detail
    const text = typeof detail === 'string' ? detail : ''
    if (text.includes('오래 걸')) return MSG_TIMEOUT // 서버의 동기 API 시간 초과(503) 안내
    if ([502, 503, 504].includes(e.response.status)) return MSG_CONNECT
    return text && isUserFacing(text) ? text : MSG_GENERIC
  }
  return MSG_GENERIC
}

/** 서버가 보낸 SSE error 이벤트의 메시지: 사용자용이면 그대로, 아니면 일반 문구 */
export function serverErrorMessage(msg: string): string {
  if (isUserFacing(msg)) return msg
  console.error('[odiro] 서버 오류:', msg)
  return MSG_GENERIC
}

// ---------- SSE ----------

/** 연결이 끊긴 뒤 브라우저의 자동 재연결(CONNECTING)을 기다려 주는 시간. 넘으면 끊김으로 처리 */
export const STREAM_RECONNECT_GRACE_MS = 10_000
/**
 * 생성·수정 스트림 전체 대기 상한. Cloud Run 요청 타임아웃이 120초(deploy.yml --timeout 120)라
 * 그 안에 결과가 오지 않으면 정상 완료 가능성이 낮다. 콜드스타트·재연결 여유 30초를 더해 150초.
 * (평가 기준 2일 여행 35~47초, 로컬 첫 요청 57초)
 */
export const STREAM_TOTAL_TIMEOUT_MS = 150_000
/**
 * 스트림이 이만큼 조용하면 서버가 살아 있는지 health 로 확인한다. 서버가 죽어도 중간 프록시가 브라우저 쪽 연결을
 * 열어 둔 채 멈추면 EventSource 는 오류를 내지 않는다(로컬 Vite 프록시에서 재현). 서버의 keep-alive 는 SSE 주석이라
 * 브라우저 코드에서 보이지 않으므로, 조용한 동안 health 를 STREAM_PROBE_EVERY_MS 마다 묻고 연속 2번 실패하면 끊김으로 본다.
 * 노드 하나가 오래 걸려도(LLM 25초+) 서버가 살아 있으면 health 가 성공하므로 계속 기다린다.
 */
export const STREAM_QUIET_MS = 10_000
export const STREAM_PROBE_EVERY_MS = 5_000
const STREAM_PROBE_FAILS = 2

/** onError 로 오는 값: 서버 메시지 그대로, 또는 아래 연결 상태 코드 */
export const STREAM_BEFORE_FIRST = '__before_first__' // 이벤트를 하나도 못 받고 끊김 → 동기 API 로 재시도
export const STREAM_DISCONNECTED = '__disconnected__' // 진행 중 끊김
export const STREAM_TIMEOUT = '__timeout__' // 전체 상한 초과

export interface StreamHandlers {
  onProgress: (step: TraceStep) => void
  onResult: (course: CourseResponse) => void
  onError: (message: string) => void
}

/**
 * SSE 구독. 반환된 함수로 닫는다 (타이머도 함께 정리). onResult·onError 는 합쳐서 한 번만 불린다.
 * - 서버가 보낸 error 이벤트 → 그 메시지
 * - 연결이 끊겨 브라우저가 재연결을 STREAM_RECONNECT_GRACE_MS 넘게 못 하면(또는 아예 CLOSED) → STREAM_BEFORE_FIRST / STREAM_DISCONNECTED
 * - 전체 STREAM_TOTAL_TIMEOUT_MS 초과 → STREAM_TIMEOUT
 */
export function subscribeStream(streamUrl: string, h: StreamHandlers): () => void {
  const url = streamUrl.startsWith('http') ? streamUrl : `${baseURL}${streamUrl}`
  const es = new EventSource(url)
  let gotAny = false
  let ended = false
  let graceTimer: number | undefined
  let lastActivity = Date.now()
  let probing = false
  let probeFails = 0

  const clearGrace = () => {
    if (graceTimer !== undefined) window.clearTimeout(graceTimer)
    graceTimer = undefined
  }
  const alive = () => {
    lastActivity = Date.now()
    probeFails = 0
    clearGrace()
  }
  const end = () => {
    ended = true
    clearGrace()
    window.clearTimeout(totalTimer)
    window.clearInterval(watchdog)
    es.close()
  }
  const failWith = (message: string) => {
    if (ended) return
    end()
    h.onError(message)
  }
  const totalTimer = window.setTimeout(() => failWith(STREAM_TIMEOUT), STREAM_TOTAL_TIMEOUT_MS)
  // 조용한 스트림 감시: 서버가 죽었는데 연결만 걸려 있는 경우를 health 로 알아낸다
  const watchdog = window.setInterval(() => {
    if (ended || probing || Date.now() - lastActivity < STREAM_QUIET_MS) return
    probing = true
    getHealth(5_000)
      .then(() => {
        probeFails = 0
      })
      .catch(() => {
        probeFails += 1
        if (probeFails >= STREAM_PROBE_FAILS) failWith(gotAny ? STREAM_DISCONNECTED : STREAM_BEFORE_FIRST)
      })
      .finally(() => {
        probing = false
      })
  }, STREAM_PROBE_EVERY_MS)

  es.addEventListener('open', alive) // (재)연결 성공
  es.addEventListener('progress', (ev) => {
    if (ended) return
    gotAny = true
    alive()
    h.onProgress(JSON.parse((ev as MessageEvent).data) as TraceStep)
  })
  es.addEventListener('result', (ev) => {
    if (ended) return
    gotAny = true
    end()
    h.onResult(JSON.parse((ev as MessageEvent).data) as CourseResponse)
  })
  es.addEventListener('error', (ev) => {
    // 서버가 보낸 error 이벤트(data 있음) vs 연결 오류(data 없음)
    const data = (ev as MessageEvent).data
    if (data) {
      let message = String(data)
      try {
        message = (JSON.parse(data) as { message: string }).message
      } catch {
        /* 그대로 */
      }
      failWith(message)
      return
    }
    const lost = gotAny ? STREAM_DISCONNECTED : STREAM_BEFORE_FIRST
    if (es.readyState === EventSource.CLOSED) return failWith(lost)
    // CONNECTING: 브라우저가 자동 재연결 중. 일정 시간 안에 다시 이어지지 않으면 끊김으로 처리
    if (graceTimer === undefined) graceTimer = window.setTimeout(() => failWith(lost), STREAM_RECONNECT_GRACE_MS)
  })
  return end
}
