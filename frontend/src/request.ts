// 요청 기본값·프리셋·세션 저장. 새로고침해도 /plan 이 살아 있도록 sessionStorage 를 쓴다.
import type { CourseRequest, CourseResponse } from './api'

const REQ_KEY = 'odiro.request'
const COURSE_KEY = 'odiro.course'

/** 다음 토요일 (오늘이 토요일이면 오늘). */
export function nextSaturday(from = new Date()): string {
  const d = new Date(from)
  const diff = (6 - d.getDay() + 7) % 7
  d.setDate(d.getDate() + diff)
  // toISOString 은 UTC 라 한국 저녁엔 하루가 밀린다 → 로컬 날짜로 조립
  const mm = String(d.getMonth() + 1).padStart(2, '0')
  const dd = String(d.getDate()).padStart(2, '0')
  return `${d.getFullYear()}-${mm}-${dd}`
}

export function defaultRequest(): CourseRequest {
  return {
    mode: 'outing',
    transport: 'walk',
    region: '',
    date: nextSaturday(),
    start_time: '11:00',
    end_time: '20:00',
    days: 1,
    budget: 100_000,
    moods: [],
    free_text: '',
    party: '',
  }
}

export interface Preset {
  label: string
  patch: Partial<CourseRequest>
}

// 데이터가 수도권(서울·인천·경기)뿐이라 프리셋도 수도권만.
export const PRESETS: Preset[] = [
  { label: '성수동 데이트', patch: { region: '성수동', mode: 'outing', transport: 'walk', moods: ['감성/조용한', '사진맛집'], party: '연인' } },
  { label: '가평 1박 2일', patch: { region: '가평', mode: 'trip', transport: 'car', days: 2, moods: ['자연/산책', '뷰맛집/일몰'], party: '연인' } },
  { label: '인천 송도 아이와', patch: { region: '인천 송도', mode: 'outing', transport: 'car', moods: ['아이동반', '실내(비오는날)'], party: '가족(아이 1)' } },
  { label: '북촌 한옥 산책', patch: { region: '북촌', mode: 'outing', transport: 'walk', moods: ['레트로', '자연/산책', '사진맛집'] } },
  { label: '수원 화성 레트로', patch: { region: '수원 화성', mode: 'outing', transport: 'walk', moods: ['레트로', '사진맛집'] } },
]

export function applyPreset(base: CourseRequest, p: Preset): CourseRequest {
  const next = { ...base, ...p.patch }
  if (next.mode === 'outing') next.days = 1
  return next
}

export function saveRequest(r: CourseRequest) {
  sessionStorage.setItem(REQ_KEY, JSON.stringify(r))
}
export function loadRequest(): CourseRequest | null {
  const s = sessionStorage.getItem(REQ_KEY)
  if (!s) return null
  try {
    return { ...defaultRequest(), ...(JSON.parse(s) as Partial<CourseRequest>) }
  } catch {
    return null
  }
}
export function saveCourse(c: CourseResponse | null) {
  if (c) sessionStorage.setItem(COURSE_KEY, JSON.stringify(c))
  else sessionStorage.removeItem(COURSE_KEY)
}
export function loadCourse(): CourseResponse | null {
  const s = sessionStorage.getItem(COURSE_KEY)
  if (!s) return null
  try {
    return JSON.parse(s) as CourseResponse
  } catch {
    return null
  }
}

export const TRANSPORT_LABEL: Record<CourseRequest['transport'], string> = { walk: '뚜벅이', car: '자차' }
export const MODE_LABEL: Record<CourseRequest['mode'], string> = { outing: '나들이', trip: '여행' }

export function formatBudget(won: number): string {
  if (won <= 0) return '예산 무관'
  return won >= 10_000 ? `${(won / 10_000).toLocaleString('ko-KR')}만원` : `${won.toLocaleString('ko-KR')}원`
}

export function formatDate(iso: string): string {
  const d = new Date(`${iso}T00:00:00`)
  if (Number.isNaN(d.getTime())) return iso
  const w = ['일', '월', '화', '수', '목', '금', '토'][d.getDay()]
  return `${d.getMonth() + 1}/${d.getDate()}(${w})`
}

export function summarize(r: CourseRequest): string {
  const parts = [r.region || '지역 미정', formatDate(r.date)]
  if (r.mode === 'trip') parts.push(`${r.days - 1}박 ${r.days}일`)
  else parts.push(`${r.start_time}~${r.end_time}`)
  parts.push(TRANSPORT_LABEL[r.transport], formatBudget(r.budget))
  if (r.moods.length) parts.push(r.moods.join('·'))
  return parts.join(' · ')
}
