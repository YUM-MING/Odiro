// 조건 빌더의 날짜 칸 + 달력 팝업.
// - 데이트·당일치기: 날짜 하나. 값은 YYYY-MM-DD(CourseRequest.date), days = 1. 표시 "11월 28일 (토)" + "N일 후" 알약
// - 여행(range): 시작일~종료일 기간. 첫 클릭 = 시작일, 두 번째 클릭 = 종료일(시작일+1~+2, 최대 2박 3일).
//   서버로는 지금처럼 date = 시작일, days = 종료일 − 시작일 + 1 (2 또는 3)로 보낸다 (schemas.py days ≤ 3)
// 날씨 예보가 반영되는 날(브라우저 기준 오늘~+5일, get_weather 의 예보 범위)에 점을 찍는다.
import { useEffect, useRef, useState, type KeyboardEvent } from 'react'
import * as I from './Icons'
import { localYmd } from './request'

const WEEKDAYS = ['일', '월', '화', '수', '목', '금', '토']
const FORECAST_DAYS = 5
const TRIP_MIN_DAYS = 2 // 1박 2일
const TRIP_MAX_DAYS = 3 // 2박 3일 (서버 CourseRequest.days 최대)

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

/** 두 날짜 사이 일수 (b − a) */
function dayDiff(a: string, b: string): number {
  const x = parseYmd(a)
  const y = parseYmd(b)
  return x && y ? Math.round((y.getTime() - x.getTime()) / 86_400_000) : 0
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

/** "12/1 (화)" — weekday=false 면 "12/1" */
function formatShort(ymd: string, weekday = true): string {
  const d = parseYmd(ymd)
  return d ? `${d.getMonth() + 1}/${d.getDate()}${weekday ? ` (${WEEKDAYS[d.getDay()]})` : ''}` : ''
}

interface Props {
  value: string // 시작일 (여행) 또는 날짜 (그 외)
  days?: number // 여행 일수 (range 일 때만 씀)
  /** 여행 모드: 시작일~종료일 기간 선택 */
  range?: boolean
  onChange: (date: string, days: number) => void
}

export default function DatePicker({ value, days = 1, range = false, onChange }: Props) {
  const [open, setOpen] = useState(false)
  const [view, setView] = useState('') // 보고 있는 달 YYYY-MM
  const [focus, setFocus] = useState('') // 키보드 포커스 날짜 YYYY-MM-DD
  const [pending, setPending] = useState<string | null>(null) // 여행: 시작일만 고른 상태
  const wrapRef = useRef<HTMLDivElement>(null)
  const triggerRef = useRef<HTMLButtonElement>(null)
  const gridRef = useRef<HTMLDivElement>(null)
  // 바깥 클릭(문서 이벤트)에서도 최신 값으로 마무리하려고 ref 로 들고 있는다
  const pendingRef = useRef<string | null>(null)
  const onChangeRef = useRef(onChange)
  useEffect(() => {
    onChangeRef.current = onChange
  }, [onChange])

  // 오늘(브라우저 기준)은 팝업을 열 때마다 다시 잰다 (페이지를 열어 둔 채 날이 바뀌어도 맞게)
  const [today, setToday] = useState(todayYmd)
  const lastForecast = addDays(today, FORECAST_DAYS)

  const setPendingBoth = (p: string | null) => {
    pendingRef.current = p
    setPending(p)
  }

  // 열 때 선택된 날짜가 속한 달을 보여 준다 (값이 없거나 지난 날짜면 오늘 달)
  const openAt = (ymd: string) => {
    const now = todayYmd()
    const start = parseYmd(ymd) && ymd >= now ? ymd : now
    setToday(now)
    setFocus(start)
    setView(monthOf(start))
    setPendingBoth(null)
    setOpen(true)
  }
  /** 닫기. 여행에서 시작일만 고른 채 닫으면 최소 기간(1박 2일)으로 정한다 */
  const close = (returnFocus = false) => {
    const p = pendingRef.current
    if (p) onChangeRef.current(p, TRIP_MIN_DAYS)
    setPendingBoth(null)
    setOpen(false)
    if (returnFocus) triggerRef.current?.focus()
  }

  const pick = (d: string) => {
    if (!range) {
      onChange(d, 1)
      close(true)
      return
    }
    if (!pending) {
      setPendingBoth(d) // 첫 클릭 = 시작일 (팝업은 열어 둔다)
      return
    }
    // 두 번째 클릭 = 종료일. 같은 날을 다시 누르면 최소 기간(1박 2일)
    const n = d === pending ? TRIP_MIN_DAYS : dayDiff(pending, d) + 1
    const start = pending
    setPendingBoth(null)
    onChange(start, Math.min(TRIP_MAX_DAYS, Math.max(TRIP_MIN_DAYS, n)))
    setOpen(false)
    triggerRef.current?.focus()
  }

  // 바깥 클릭으로 닫기 (시작일만 골랐으면 1박 2일로)
  useEffect(() => {
    if (!open) return
    const onDown = (e: MouseEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) {
        const p = pendingRef.current
        if (p) onChangeRef.current(p, TRIP_MIN_DAYS)
        pendingRef.current = null
        setPending(null)
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', onDown)
    return () => document.removeEventListener('mousedown', onDown)
  }, [open])

  // 키보드 포커스 날짜로 실제 포커스 이동 (DOM 만 건드린다)
  useEffect(() => {
    if (open) gridRef.current?.querySelector<HTMLButtonElement>(`[data-date="${focus}"]`)?.focus()
  }, [open, focus])

  /** 고를 수 없는 날: 지난 날, 여행에서 시작일을 고른 뒤 시작일 이전·시작일+2 초과 */
  const blocked = (d: string) =>
    d < today || (pending !== null && (d < pending || d > addDays(pending, TRIP_MAX_DAYS - 1)))

  const moveFocus = (n: number) => {
    const next = addDays(focus, n)
    if (blocked(next)) return
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

  // 표시할 기간: 시작일만 고른 중이면 그 하루, 아니면 현재 값
  const tripDays = Math.min(TRIP_MAX_DAYS, Math.max(TRIP_MIN_DAYS, days))
  const rangeStart = range ? (pending ?? value) : value
  const rangeEnd = range ? (pending ?? addDays(value, tripDays - 1)) : value
  const hasSpan = range && rangeEnd > rangeStart

  const label = formatKoDate(value)
  const endYmd = addDays(value, tripDays - 1)
  // 데이트·당일치기 알약: 오늘과의 차이 (오늘 / N일 후). 지난 날짜·잘못된 값이면 없음
  const diff = parseYmd(value) && parseYmd(today) ? dayDiff(today, value) : -1
  const relLabel = diff === 0 ? '오늘' : diff > 0 ? `${diff}일 후` : ''
  const relForecast = diff >= 0 && diff <= FORECAST_DAYS
  const nightsLabel = `${tripDays - 1}박 ${tripDays}일`

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

  const triggerLabel = range
    ? label
      ? `여행 기간 ${label}부터 ${formatKoDate(endYmd)}까지, ${nightsLabel}, 바꾸려면 누르세요`
      : '여행 기간 선택'
    : label
      ? `날짜 ${label}, 바꾸려면 누르세요`
      : '날짜 선택'

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
          aria-label={triggerLabel}
          onClick={() => (open ? close() : openAt(value))}
        >
          {range && label ? (
            <>
              {/* 칸 폭에 따라 하나만 보인다 (App.css 컨테이너 쿼리): 긴 표기 → "12/1 (화) – 12/3 (목)" → "12/1 – 12/3" */}
              <span className="date-label date-range-long">{label} – {formatKoDate(endYmd)}</span>
              <span className="date-label date-range-short">{formatShort(value)} – {formatShort(endYmd)}</span>
              <span className="date-label date-range-tiny">{formatShort(value, false)} – {formatShort(endYmd, false)}</span>
              <span className="date-pill date-pill-trip" aria-hidden="true">{nightsLabel}</span>
            </>
          ) : (
            <>
              <span className="date-label">{label || <span className="date-placeholder">{range ? '여행 기간 선택' : '날짜 선택'}</span>}</span>
              {!range && relLabel && (
                <span className="date-pill" aria-hidden="true">
                  {relForecast && <span className="dp-dot" />}
                  {relLabel}
                </span>
              )}
            </>
          )}
          <I.Chevron size={16} className="date-chev" />
        </button>
      </div>

      {open && (
        <div className="datepop" role="dialog" aria-label={range ? '여행 기간 선택' : '날짜 선택'} onKeyDown={onPopKey}>
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
                  const off = blocked(d)
                  const forecast = !past && d <= lastForecast
                  const isStart = d === rangeStart
                  const isEnd = d === rangeEnd
                  const selected = range ? d >= rangeStart && d <= rangeEnd : d === value
                  const cls = [
                    'dp-cell', 'dp-day', di === 0 ? 'sun' : di === 6 ? 'sat' : '',
                    (range ? isStart || isEnd : d === value) ? 'sel' : '',
                    hasSpan && d > rangeStart && d < rangeEnd ? 'in-range' : '',
                    hasSpan && isStart ? 'range-start' : '',
                    hasSpan && isEnd ? 'range-end' : '',
                    d === today ? 'today' : '', off ? 'past' : '',
                  ]
                    .filter(Boolean)
                    .join(' ')
                  const role = range && pending ? (d === pending ? ', 시작일' : '') : range && isStart ? ', 시작일' : range && isEnd ? ', 종료일' : ''
                  return (
                    <button
                      key={d}
                      type="button"
                      role="gridcell"
                      className={cls}
                      data-date={d}
                      tabIndex={d === focus ? 0 : -1}
                      disabled={off}
                      aria-disabled={off || undefined}
                      aria-selected={selected}
                      aria-current={d === today ? 'date' : undefined}
                      aria-label={`${formatKoDate(d)}${role}${d === today ? ', 오늘' : ''}${forecast ? ', 날씨 예보 반영' : ''}`}
                      onClick={() => pick(d)}
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
          {range && (
            <p className="dp-range-note" aria-live="polite">
              {pending ? '끝나는 날을 골라 주세요. ' : '시작일을 고른 뒤 끝나는 날을 골라 주세요. '}
              최대 2박 3일까지 고를 수 있어요
            </p>
          )}
        </div>
      )}
    </div>
  )
}
