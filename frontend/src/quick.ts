import type { CourseResponse } from './api'

export interface QuickAction {
  label: string
  instruction: string
}

// 보내는 문장은 예전 고정 버튼과 같다 (백엔드 수정 흐름이 이미 처리하는 표현: 코스에서 한 곳을 골라 그 성격으로 교체).
// 수정 흐름은 여행이면 모든 날을 함께 보고 한 곳을 고르므로, 버튼 판단도 코스(여행 전체) 기준이다.
const QUIET: QuickAction = { label: '더 조용한 곳으로', instruction: '전체적으로 더 조용하고 한적한 곳 위주로 바꿔줘' }
const INDOOR: QuickAction = { label: '실내 위주로', instruction: '비 와도 괜찮게 실내 장소 위주로 바꿔줘' }
const CHEAPER: QuickAction = { label: '예산 낮춰줘', instruction: '예산을 30% 정도 낮춰서 가성비 좋은 곳으로 바꿔줘' }

export const QUICK_MAX = 3
export const BUDGET_TIGHT_RATIO = 0.7 // 1인 예상 비용이 예산의 이 비율 이상일 때만 '예산 낮춰줘'

/** 이미 조용한 분위기를 요청했는지 (분위기 태그 또는 자유 조건에 '조용'). 판단할 값이 없으면 false */
function askedQuiet(c: CourseResponse): boolean {
  const moods = c.request.moods ?? []
  return moods.some((m) => m.includes('조용')) || (c.request.free_text ?? '').includes('조용')
}

/**
 * 코스 상태에 맞는 빠른 수정 버튼 (최대 3개, 응답에 이미 있는 값만 쓴다. 값이 없으면 추정하지 않는다).
 * - 실내 위주로: 비 규칙이 이미 발동(meta.weather.rain)했으면 제외
 * - 예산 낮춰줘: 예산·예상 비용이 둘 다 있으면 비용 ≥ 예산의 70% 일 때만. 하나라도 없으면 판단 불가 → 후순위로만
 * - 더 조용한 곳으로: 제외하지 않는다. 이미 조용한 분위기를 요청했으면 후순위
 * 제외 조건에 걸린 버튼은 개수를 채우려고 다시 넣지 않는다. 세 후보 중 '조용한' 은 제외되지 않아 0개가 되는 경우는 없다.
 */
export function quickActions(c: CourseResponse): QuickAction[] {
  const first: QuickAction[] = []
  const later: QuickAction[] = []

  const budget = c.request.budget ?? 0
  const cost = c.meta.est_cost_total ?? 0
  if (budget > 0 && cost > 0) {
    if (cost >= budget * BUDGET_TIGHT_RATIO) first.push(CHEAPER) // 예산이 빠듯하면 맨 앞
  } else {
    later.push(CHEAPER) // 판단 불가: 기본 버튼으로 후순위
  }

  if (!c.meta.weather.rain) first.push(INDOOR)

  ;(askedQuiet(c) ? later : first).push(QUIET)

  return [...first, ...later].slice(0, QUICK_MAX)
}
