import type { PlaceOut } from './api'

/** Day 별 동선(선) 색 (trip 모드) */
export const DAY_COLORS = ['#ff6b4a', '#2f9e55', '#d98c12']

export function dayColor(day: number): string {
  return DAY_COLORS[(day - 1) % DAY_COLORS.length]
}

/** 장소 종류: 카드 번호·지도 핀 색을 이걸로 나눈다 */
export type Kind = 'food' | 'cafe' | 'play' | 'stay'

export const KIND_COLOR: Record<Kind, string> = {
  food: '#e8590c', // 밥집: 주황
  cafe: '#8a5a2b', // 카페: 갈색
  play: '#2f9e55', // 놀거리·볼거리: 초록
  stay: '#3b5bdb', // 숙소: 파랑
}

export const KIND_LABEL: Record<Kind, string> = { food: '밥집', cafe: '카페', play: '놀거리', stay: '숙소' }

export function placeKind(category: string): Kind {
  if (category === '식당') return 'food'
  if (category === '카페') return 'cafe'
  if (category === '숙소') return 'stay'
  return 'play'
}

export function kindColor(p: Pick<PlaceOut, 'category'>): string {
  return KIND_COLOR[placeKind(p.category)]
}

const point = (p: PlaceOut) => `${encodeURIComponent(p.name)},${p.lat},${p.lng}`

/** 카카오맵 길찾기 링크 (도착지 지정, 출발지는 현재 위치) */
export function kakaoToLink(p: PlaceOut): string {
  return `https://map.kakao.com/link/to/${point(p)}`
}

/** 카카오맵 리뷰·상세 페이지. 장소 id 가 없으면 이름 검색으로 연다 */
export function kakaoReviewLink(p: PlaceOut): string {
  return p.place_url || `https://map.kakao.com/link/search/${encodeURIComponent(p.name)}`
}

/** 하루 코스 전체를 순서대로 잇는 카카오맵 경로 (자차 내비 / 도보). 장소가 2곳 미만이면 빈 문자열 */
export function kakaoRouteLink(places: PlaceOut[], mode: 'car' | 'walk'): string {
  if (places.length < 2) return ''
  // 카카오맵은 출발·도착 + 경유지 5곳까지 받는다
  return `https://map.kakao.com/link/by/${mode}/${places.slice(0, 7).map(point).join('/')}`
}
