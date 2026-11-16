// 여행(N박 M일) 코스의 날짜 탭. 채팅의 장소 목록과 지도가 같은 선택 상태를 공유한다.
import { dayColor } from './mapUtil'

interface Props {
  days: number[]
  active: number
  onChange: (day: number) => void
  className?: string
}

export default function DayTabs({ days, active, onChange, className = '' }: Props) {
  if (days.length < 2) return null
  return (
    <div className={`day-tabs ${className}`} role="tablist" aria-label="날짜 선택">
      {days.map((d) => (
        <button
          key={d}
          type="button"
          role="tab"
          aria-selected={d === active}
          className={`day-tab${d === active ? ' active' : ''}`}
          style={{ ['--day' as string]: dayColor(d) }}
          onClick={() => onChange(d)}
        >
          Day {d}
        </button>
      ))}
    </div>
  )
}
