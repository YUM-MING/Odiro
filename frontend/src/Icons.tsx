// 이모지 대신 쓰는 단색 아이콘. 어느 OS/브라우저에서도 같은 모양으로 그려진다.
import type { SVGProps } from 'react'

type P = SVGProps<SVGSVGElement> & { size?: number }

function base({ size = 18, ...rest }: P) {
  return {
    width: size,
    height: size,
    viewBox: '0 0 24 24',
    fill: 'none',
    stroke: 'currentColor',
    strokeWidth: 2,
    strokeLinecap: 'round' as const,
    strokeLinejoin: 'round' as const,
    'aria-hidden': true,
    ...rest,
  }
}

export const Heart = (p: P) => (
  <svg {...base(p)}>
    <path d="M12 20s-7-4.4-7-10a4 4 0 0 1 7-2.6A4 4 0 0 1 19 10c0 5.6-7 10-7 10z" />
  </svg>
)

export const Suitcase = (p: P) => (
  <svg {...base(p)}>
    <rect x="4" y="7" width="16" height="13" rx="3" />
    <path d="M9 7V5a2 2 0 0 1 2-2h2a2 2 0 0 1 2 2v2M9 7v13M15 7v13" />
  </svg>
)

export const Pin = (p: P) => (
  <svg {...base(p)}>
    <path d="M12 21s-6-5.3-6-11a6 6 0 0 1 12 0c0 5.7-6 11-6 11z" />
    <circle cx="12" cy="10" r="2.3" />
  </svg>
)

export const Calendar = (p: P) => (
  <svg {...base(p)}>
    <rect x="3.5" y="5" width="17" height="15.5" rx="3" />
    <path d="M3.5 10h17M8 3v4M16 3v4" />
  </svg>
)

export const Car = (p: P) => (
  <svg {...base(p)}>
    <path d="M5 13l1.6-4.5A2 2 0 0 1 8.5 7h7a2 2 0 0 1 1.9 1.5L19 13" />
    <rect x="3.5" y="13" width="17" height="5" rx="2" />
    <circle cx="7.5" cy="18.5" r="1.5" fill="currentColor" stroke="none" />
    <circle cx="16.5" cy="18.5" r="1.5" fill="currentColor" stroke="none" />
  </svg>
)

export const Sparkle = (p: P) => (
  <svg {...base(p)} fill="currentColor" stroke="none">
    <path d="M12 2l1.8 5.2L19 9l-5.2 1.8L12 16l-1.8-5.2L5 9l5.2-1.8zM5 16l.9 2.1L8 19l-2.1.9L5 22l-.9-2.1L2 19l2.1-.9zM19 15l.7 1.6 1.6.7-1.6.7L19 19.6l-.7-1.6-1.6-.7 1.6-.7z" />
  </svg>
)

export const Robot = (p: P) => (
  <svg {...base(p)}>
    <rect x="4" y="8" width="16" height="12" rx="4" />
    <path d="M12 8V4M9 4h6" />
    <circle cx="9" cy="14" r="1.4" fill="currentColor" stroke="none" />
    <circle cx="15" cy="14" r="1.4" fill="currentColor" stroke="none" />
    <path d="M9.5 17.5h5" />
  </svg>
)

export const Map = (p: P) => (
  <svg {...base(p)}>
    <path d="M3 6.5 9 4l6 2.5L21 4v13.5L15 20l-6-2.5L3 20z" />
    <path d="M9 4v13.5M15 6.5V20" />
  </svg>
)

export const Bookmark = (p: P) => (
  <svg {...base(p)}>
    <path d="M6 3h12v18l-6-4-6 4z" />
  </svg>
)

export const Chevron = (p: P) => (
  <svg {...base(p)}>
    <path d="m6 9 6 6 6-6" />
  </svg>
)
