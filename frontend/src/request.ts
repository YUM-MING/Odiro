// 요청 기본값·프리셋·세션 저장. 새로고침해도 /plan 이 살아 있도록 sessionStorage 를 쓴다.
import type { CourseRequest, CourseResponse } from './api'

const REQ_KEY = 'odiro.request'
const COURSE_KEY = 'odiro.course'

// toISOString 은 UTC 라 한국 저녁엔 하루가 밀린다 → 브라우저 로컬 날짜로 YYYY-MM-DD 조립
function localYmd(d: Date): string {
  const mm = String(d.getMonth() + 1).padStart(2, '0')
  const dd = String(d.getDate()).padStart(2, '0')
  return `${d.getFullYear()}-${mm}-${dd}`
}

/** 다음 토요일 (오늘이 토요일이면 오늘). */
export function nextSaturday(from = new Date()): string {
  const d = new Date(from)
  const diff = (6 - d.getDay() + 7) % 7
  d.setDate(d.getDate() + diff)
  return localYmd(d)
}

/** 저장된 날짜가 오늘(브라우저 기준)보다 이전이면 날짜만 기본값(다음 토요일)으로 바꾼다. 다른 값은 그대로 */
export function withValidDate(r: CourseRequest, now = new Date()): CourseRequest {
  return r.date < localYmd(now) ? { ...r, date: defaultRequest().date } : r
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
    headcount: 1,
    lodging: '',
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

/**
 * 지금 입력값(base) 위에 프리셋을 덮는다. 날짜·시작/종료 시각·예산·인원은 사용자가 고른 값을 그대로 두고,
 * 지역·모드·이동수단·분위기·동행은 프리셋 값으로 바꾼다. 이전 지역에 묶인 자유 조건·숙소는 비운다.
 */
export function applyPreset(base: CourseRequest, p: Preset): CourseRequest {
  const next: CourseRequest = { ...base, free_text: '', lodging: '', party: '', ...p.patch }
  if (next.mode === 'outing') {
    next.days = 1
    next.lodging = ''
  }
  return next
}

export function saveRequest(r: CourseRequest) {
  sessionStorage.setItem(REQ_KEY, JSON.stringify(r))
}
/**
 * 저장된 조건. 지난 날짜는 기본 날짜로 바꿔 돌려준다.
 * keepDate: 이미 만든 코스를 다시 보여 줄 때(새로고침 복원)는 그 코스의 날짜를 그대로 둔다
 */
export function loadRequest({ keepDate = false }: { keepDate?: boolean } = {}): CourseRequest | null {
  const s = sessionStorage.getItem(REQ_KEY)
  if (!s) return null
  try {
    const r = { ...defaultRequest(), ...(JSON.parse(s) as Partial<CourseRequest>) }
    return keepDate ? r : withValidDate(r)
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

/** 공유 텍스트에 넣을 수 있는 조건 항목. 사용자가 체크박스로 고른다 */
export interface ShareCondition {
  key: string
  label: string // 체크박스에 보이는 이름
  text: string // 공유 텍스트에 들어가는 한 줄
  defaultOn: boolean
}

/**
 * 공유용 조건 항목 목록. 값이 없는 항목은 만들지 않는다.
 * 숙소·요청 사항은 직접 적은 개인 입력이라 기본은 꺼 둔다.
 */
export function shareConditions(r: CourseRequest, estCostTotal = 0): ShareCondition[] {
  const when =
    r.mode === 'trip'
      ? `${formatDate(r.date)} 출발 · ${r.days - 1}박 ${r.days}일`
      : `${formatDate(r.date)} ${r.start_time}~${r.end_time}`
  const items: ShareCondition[] = [
    { key: 'basic', label: '지역·모드·이동수단', text: `${r.region || '지역 미정'} · ${MODE_LABEL[r.mode]} · ${TRANSPORT_LABEL[r.transport]}`, defaultOn: true },
    { key: 'when', label: '날짜·시간', text: when, defaultOn: true },
    {
      key: 'budget',
      label: '예산',
      text: `1인 예산 ${formatBudget(r.budget)}${r.budget > 0 && r.mode === 'trip' ? ' (전체 일정 합계, 숙박비 제외)' : ''}${
        r.budget > 0 && r.headcount > 1 ? ` · ${r.headcount}명 합계 ${formatBudget(r.budget * r.headcount)}` : ''
      }`,
      defaultOn: true,
    },
  ]
  if (r.party || r.headcount > 1)
    items.push({ key: 'party', label: '동행·인원', text: `동행 ${[r.party, r.headcount > 1 ? `총 ${r.headcount}명` : ''].filter(Boolean).join(' · ')}`, defaultOn: true })
  if (r.moods.length) items.push({ key: 'moods', label: '분위기', text: `분위기 ${r.moods.join(', ')}`, defaultOn: true })
  if (estCostTotal > 0)
    items.push({ key: 'cost', label: '1인 예상 비용', text: `1인 예상 약 ${estCostTotal.toLocaleString('ko-KR')}원 (추정)`, defaultOn: true })
  if (r.lodging) items.push({ key: 'lodging', label: '숙소', text: `숙소 ${r.lodging}`, defaultOn: false })
  if (r.free_text) items.push({ key: 'free', label: '요청 사항', text: `요청 사항 "${r.free_text}"`, defaultOn: false })
  return items
}

export function summarize(r: CourseRequest): string {
  const parts = [r.region || '지역 미정', formatDate(r.date)]
  if (r.mode === 'trip') parts.push(`${r.days - 1}박 ${r.days}일`)
  else parts.push(`${r.start_time}~${r.end_time}`)
  parts.push(TRANSPORT_LABEL[r.transport], formatBudget(r.budget))
  if (r.moods.length) parts.push(r.moods.join('·'))
  return parts.join(' · ')
}
