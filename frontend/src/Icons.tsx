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

export const Map = (p: P) => (
  <svg {...base(p)}>
    <path d="M3 6.5 9 4l6 2.5L21 4v13.5L15 20l-6-2.5L3 20z" />
    <path d="M9 4v13.5M15 6.5V20" />
  </svg>
)

export const Chevron = (p: P) => (
  <svg {...base(p)}>
    <path d="m6 9 6 6 6-6" />
  </svg>
)

export const Share = (p: P) => (
  <svg {...base(p)}>
    <circle cx="18" cy="5" r="2.5" />
    <circle cx="6" cy="12" r="2.5" />
    <circle cx="18" cy="19" r="2.5" />
    <path d="m8.2 10.8 7.6-4.6M8.2 13.2l7.6 4.6" />
  </svg>
)

export const Refresh = (p: P) => (
  <svg {...base(p)}>
    <path d="M20 12a8 8 0 1 1-2.3-5.7" />
    <path d="M20 4v5h-5" />
  </svg>
)

export const Sliders = (p: P) => (
  <svg {...base(p)}>
    <path d="M4 7h10M18 7h2M4 17h4M12 17h8" />
    <circle cx="16" cy="7" r="2" />
    <circle cx="10" cy="17" r="2" />
  </svg>
)

export const Sun = (p: P) => (
  <svg {...base(p)}>
    <circle cx="12" cy="12" r="4" />
    <path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
  </svg>
)

export const Rain = (p: P) => (
  <svg {...base(p)}>
    <path d="M7 15a4.5 4.5 0 0 1-.6-9A6 6 0 0 1 18 7.5 3.5 3.5 0 0 1 17.5 15z" />
    <path d="M9 18l-1 3M13 18l-1 3M17 18l-1 3" />
  </svg>
)

export const Walk = (p: P) => (
  <svg {...base(p)}>
    <circle cx="13" cy="4" r="1.8" fill="currentColor" stroke="none" />
    <path d="M10 21l2-6 3 2v4M8 12l3-3 3 1 2 3h2M12 9l-2 3-3 1" />
  </svg>
)

export const Check = (p: P) => (
  <svg {...base(p)}>
    <path d="m5 12 4.5 4.5L19 7" />
  </svg>
)

export const Clock = (p: P) => (
  <svg {...base(p)}>
    <circle cx="12" cy="12" r="8.5" />
    <path d="M12 7.5V12l3 2" />
  </svg>
)

export const Send = (p: P) => (
  <svg {...base(p)}>
    <path d="M21 3 10 14M21 3l-7 18-4-7-7-4z" />
  </svg>
)

export const Close = (p: P) => (
  <svg {...base(p)}>
    <path d="M6 6l12 12M18 6 6 18" />
  </svg>
)

export const Bulb = (p: P) => (
  <svg {...base(p)}>
    <path d="M9 18h6M10 21.5h4" />
    <path d="M12 2.5a6.5 6.5 0 0 0-3.8 11.8c.5.4.8 1 .8 1.6V16h6v-.1c0-.6.3-1.2.8-1.6A6.5 6.5 0 0 0 12 2.5z" />
  </svg>
)

export const Chat = (p: P) => (
  <svg {...base(p)}>
    <path d="M20.5 11.5a8 8 0 0 1-11.7 7.1L4 20l1.3-4.4A8 8 0 1 1 20.5 11.5z" />
    <path d="M8.5 11.5h.01M12.5 11.5h.01M16.5 11.5h.01" />
  </svg>
)

export const Swap = (p: P) => (
  <svg {...base(p)}>
    <path d="M7 4 3 8l4 4M3 8h14" />
    <path d="m17 12 4 4-4 4M21 16H7" />
  </svg>
)

export const CloudSun = (p: P) => (
  <svg {...base(p)}>
    <path d="M9 2.5v1.5M3.6 4.6l1.1 1.1M2 10h1.5M14.4 4.6l-1.1 1.1" />
    <path d="M5.6 12.6A4 4 0 0 1 12.4 8" />
    <path d="M17 20.5H8.5a3.5 3.5 0 1 1 .7-6.9 5 5 0 0 1 9.6 1.5 2.75 2.75 0 0 1-1.8 5.4z" />
  </svg>
)

export const Click = (p: P) => (
  <svg {...base(p)}>
    <path d="M9 9l10.5 4.2-4.3 1.5-1.5 4.3z" />
    <path d="M7.5 3.5v2M3.5 7.5h2M4.6 4.6 6 6M11.4 4.6 10 6M4.6 11.4 6 10" />
  </svg>
)

export const Wallet = (p: P) => (
  <svg {...base(p)}>
    <path d="M19 7V5.5A1.5 1.5 0 0 0 17.5 4H5a2 2 0 0 0 0 4h14a1 1 0 0 1 1 1v3" />
    <path d="M3 6v12a2 2 0 0 0 2 2h14a1 1 0 0 0 1-1v-3" />
    <path d="M21 12h-4a2 2 0 0 0 0 4h4z" />
  </svg>
)

export const Compass = (p: P) => (
  <svg {...base(p)}>
    <circle cx="12" cy="12" r="9" />
    <path d="m15.5 8.5-2 5-5 2 2-5z" />
  </svg>
)

