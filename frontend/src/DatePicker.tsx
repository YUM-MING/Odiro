// 조건 빌더의 날짜 칸 + 달력 팝업. 값은 지금처럼 YYYY-MM-DD 문자열(CourseRequest.date), 표시는 "11월 28일 (토)".
// 날씨 예보가 반영되는 날(브라우저 기준 오늘~+5일, get_weather 의 예보 범위)에 점을 찍는다.
import { useEffect, useRef, useState, type KeyboardEvent, type ReactNode } from 'react'
import * as I from './Icons'
import { localYmd } from './request'

const WEEKDAYS = ['일', '월', '화', '수', '목', '금', '토']
const FORECAST_DAYS = 5

function parseYmd(ymd: string): Date | null {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(ymd)
  if (!m) return null
  const d = new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]))
  return Number.isNaN(d.getTime()) ? null : d
}

function addDays(ymd: string, n: number): string {
  const d = parseYmd(ymd) ?? new Date()
  d.setDate(d.getDate() + n)
  return localYmd(d)
}

const monthOf = (ymd: string) => ymd.slice(0, 7) // YYYY-MM

/** 브라우저 기준 오늘 YYYY-MM-DD */
const todayYmd = () => localYmd(new Date())

function addMonths(ym: string, n: number): string {
  const [y, m] = ym.split('-').map(Number)
  const d = new Date(y, m - 1 + n, 1)
  return localYmd(d).slice(0, 7)
}

/** "11월 28일 (토)" — 잘못된 값이면 빈 문자열 */
function formatKoDate(ymd: string): string {
  const d = parseYmd(ymd)
  return d ? `${d.getMonth() + 1}월 ${d.getDate()}일 (${WEEKDAYS[d.getDay()]})` : ''
}

interface Props {
  value: string
  onChange: (ymd: string) => void
  /** 같은 칸 안에 붙는 것 (여행 모드의 일수 select) */
  children?: ReactNode
}

export default function DatePicker({ value, onChange, children }: Props) {
  const [open, setOpen] = useState(false)
  const [view, setView] = useState('') // 보고 있는 달 YYYY-MM
  const [focus, setFocus] = useState('') // 키보드 포커스 날짜 YYYY-MM-DD
  const wrapRef = useRef<HTMLDivElement>(null)
  const triggerRef = useRef<HTMLButtonElement>(null)
  const gridRef = useRef<HTMLDivElement>(null)

  // 오늘(브라우저 기준)은 팝업을 열 때마다 다시 잰다 (페이지를 열어 둔 채 날이 바뀌어도 맞게)
  const [today, setToday] = useState(todayYmd)
  const lastForecast = addDays(today, FORECAST_DAYS)

  // 열 때 선택된 날짜가 속한 달을 보여 준다 (값이 없거나 지난 날짜면 오늘 달)
  const openAt = (ymd: string) => {
    const now = todayYmd()
    const start = parseYmd(ymd) && ymd >= now ? ymd : now
    setToday(now)
    setFocus(start)
    setView(monthOf(start))
    setOpen(true)
  }
  const close = (returnFocus = false) => {
    setOpen(false)
    if (returnFocus) triggerRef.current?.focus()
  }
  const select = (ymd: string) => {
    onChange(ymd)
    close(true)
  }

  // 바깥 클릭으로 닫기
  useEffect(() => {
    if (!open) return
    const onDown = (e: MouseEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', onDown)
    return () => document.removeEventListener('mousedown', onDown)
  }, [open])

  // 키보드 포커스 날짜로 실제 포커스 이동 (DOM 만 건드린다)
  useEffect(() => {
    if (open) gridRef.current?.querySelector<HTMLButtonElement>(`[data-date="${focus}"]`)?.focus()
  }, [open, focus])

  const moveFocus = (n: number) => {
    const next = addDays(focus, n)
    if (next < today) return
    setFocus(next)
    setView(monthOf(next))
  }

  const onGridKey = (e: KeyboardEvent<HTMLDivElement>) => {
    const step = { ArrowLeft: -1, ArrowRight: 1, ArrowUp: -7, ArrowDown: 7 }[e.key]
    if (step !== undefined) {
      e.preventDefault()
      moveFocus(step)
    }
  }

  const onPopKey = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.key === 'Escape') {
      e.preventDefault()
      e.stopPropagation() // 드로어(조건 바꾸기) 안에서도 달력만 닫는다
      close(true)
    }
  }

  const label = formatKoDate(value)
  // 입력칸 알약: 오늘과의 차이 (오늘 / N일 후). 지난 날짜·잘못된 값이면 없음
  const picked = parseYmd(value)
  const base = parseYmd(today)
  const diff = picked && base ? Math.round((picked.getTime() - base.getTime()) / 86_400_000) : -1
  const relLabel = diff === 0 ? '오늘' : diff > 0 ? `${diff}일 후` : ''
  const relForecast = diff >= 0 && diff <= FORECAST_DAYS
  const hasExtra = Boolean(children) // 여행 모드: 같은 칸에 일수 select 가 있어 알약은 숨기고 화살표만
  const [vy, vm] = (view || monthOf(today)).split('-').map(Number)
  const first = new Date(vy, vm - 1, 1)
  const daysInMonth = new Date(vy, vm, 0).getDate()
  const cells: (string | null)[] = [
    ...Array<null>(first.getDay()).fill(null),
    ...Array.from({ length: daysInMonth }, (_, i) => localYmd(new Date(vy, vm - 1, i + 1))),
  ]
  while (cells.length % 7) cells.push(null)
  const weeks = Array.from({ length: cells.length / 7 }, (_, w) => cells.slice(w * 7, w * 7 + 7))
  const canPrev = view > monthOf(today)

  return (
    <div className="date-wrap" ref={wrapRef}>
      <div className={`field date-field${open ? ' open' : ''}`}>
        <span className="field-icon"><I.Calendar /></span>
        <button
          ref={triggerRef}
          type="button"
          className="field-input date-trigger"
          aria-haspopup="dialog"
          aria-expanded={open}
          aria-label={label ? `날짜 ${label}, 바꾸려면 누르세요` : '날짜 선택'}
          onClick={() => (open ? close() : openAt(value))}
        >
          <span className="date-label">{label || <span className="date-placeholder">날짜 선택</span>}</span>
          {!hasExtra && relLabel && (
            <span className="date-pill" aria-hidden="true">
              {relForecast && <span className="dp-dot" />}
              {relLabel}
            </span>
          )}
          <I.Chevron size={16} className="date-chev" />
        </button>
        {children}
      </div>

      {open && (
        <div className="datepop" role="dialog" aria-label="날짜 선택" onKeyDown={onPopKey}>
          <div className="dp-head">
            <button type="button" className="dp-nav prev" onClick={() => setView(addMonths(view, -1))} disabled={!canPrev} aria-label="이전 달">
              <I.Chevron size={18} />
            </button>
            <strong className="dp-title" aria-live="polite">{vy}년 {vm}월</strong>
            <button type="button" className="dp-nav next" onClick={() => setView(addMonths(view, 1))} aria-label="다음 달">
              <I.Chevron size={18} />
            </button>
          </div>

          <div className="dp-grid" role="grid" aria-label={`${vy}년 ${vm}월`} ref={gridRef} onKeyDown={onGridKey}>
            <div className="dp-row dp-weekdays" role="row">
              {WEEKDAYS.map((w, i) => (
                <span key={w} role="columnheader" className={`dp-wd${i === 0 ? ' sun' : i === 6 ? ' sat' : ''}`}>{w}</span>
              ))}
            </div>
            {weeks.map((week, wi) => (
              <div className="dp-row" role="row" key={wi}>
                {week.map((d, di) => {
                  if (!d) return <span key={di} className="dp-cell empty" role="gridcell" />
                  const past = d < today
                  const forecast = !past && d <= lastForecast
                  const cls = ['dp-cell', 'dp-day', di === 0 ? 'sun' : di === 6 ? 'sat' : '', d === value ? 'sel' : '', d === today ? 'today' : '', past ? 'past' : '']
                    .filter(Boolean)
                    .join(' ')
                  return (
                    <button
                      key={d}
                      type="button"
                      role="gridcell"
                      className={cls}
                      data-date={d}
                      tabIndex={d === focus ? 0 : -1}
                      disabled={past}
                      aria-disabled={past || undefined}
                      aria-selected={d === value}
                      aria-current={d === today ? 'date' : undefined}
                      aria-label={`${formatKoDate(d)}${d === today ? ', 오늘' : ''}${forecast ? ', 날씨 예보 반영' : ''}`}
                      onClick={() => select(d)}
                    >
                      <span className="dp-num">{Number(d.slice(8))}</span>
                      {forecast && <span className="dp-dot" aria-hidden="true" />}
                    </button>
                  )
                })}
              </div>
            ))}
          </div>

          <p className="dp-legend"><span className="dp-dot" aria-hidden="true" /> 날씨 예보가 반영되는 날</p>
        </div>
      )}
    </div>
  )
}
