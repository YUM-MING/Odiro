import type { PlaceOut } from './api'

/** Day 별 핀·동선 색 (trip 모드) */
export const DAY_COLORS = ['#ff6b4a', '#2f9e55', '#d98c12']

export function dayColor(day: number): string {
  return DAY_COLORS[(day - 1) % DAY_COLORS.length]
}

/** 카카오맵 길찾기 링크 (도착지 지정) */
export function kakaoToLink(p: PlaceOut): string {
  return `https://map.kakao.com/link/to/${encodeURIComponent(p.name)},${p.lat},${p.lng}`
}
