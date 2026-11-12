// 조건 빌더. 랜딩의 검색 카드와 /plan 의 조건 변경 드로어에서 같이 쓴다.
import { useState, type ComponentType } from 'react'
import type { CourseRequest, Mode } from './api'
import * as I from './Icons'
import { formatBudget } from './request'

type Icon = ComponentType<{ size?: number }>
type UiMode = 'date' | 'trip' | 'day'

const UI_MODES: { key: UiMode; label: string; Icon: Icon; mode: Mode }[] = [
  { key: 'date', label: '데이트 코스', Icon: I.Heart, mode: 'outing' },
  { key: 'trip', label: '여행 코스', Icon: I.Suitcase, mode: 'trip' },
  { key: 'day', label: '당일치기', Icon: I.Pin, mode: 'outing' },
]

interface Props {
  value: CourseRequest
  onChange: (next: CourseRequest) => void
  moods: string[]
  onSubmit: () => void
  submitLabel?: string
  /** 드로어에서는 상세 조건을 처음부터 펼친다 */
  expanded?: boolean
}

export default function Builder({ value, onChange, moods, onSubmit, submitLabel = 'AI로 나만의 코스 만들기', expanded = false }: Props) {
  const [uiMode, setUiMode] = useState<UiMode>(value.mode === 'trip' ? 'trip' : value.party.includes('연인') ? 'date' : 'day')
  const [more, setMore] = useState(expanded)
  const [error, setError] = useState<string | null>(null)

  const set = <K extends keyof CourseRequest>(k: K, v: CourseRequest[K]) => onChange({ ...value, [k]: v })

  const pickMode = (m: (typeof UI_MODES)[number]) => {
    setUiMode(m.key)
    onChange({
      ...value,
      mode: m.mode,
      days: m.mode === 'trip' ? Math.max(2, value.days) : 1,
      party: m.key === 'date' && !value.party ? '연인' : value.party,
    })
  }

  const toggleMood = (m: string) =>
    set('moods', value.moods.includes(m) ? value.moods.filter((x) => x !== m) : [...value.moods, m])

  const submit = (e?: React.FormEvent) => {
    e?.preventDefault()
    if (!value.region.trim()) {
      setError('어디로 갈지 지역을 입력해 주세요. 예) 성수동, 가평, 인천 송도')
      return
    }
    if (value.date.length !== 10) {
      setError('날짜를 선택해 주세요.')
      return
    }
    setError(null)
    onSubmit()
  }

  return (
    <form className="builder" onSubmit={submit} noValidate>
      <div className="mode-tabs" role="tablist" aria-label="코스 종류">
        {UI_MODES.map((m) => (
          <button
            key={m.key}
            type="button"
            role="tab"
            aria-selected={uiMode === m.key}
            className={`mode-tab${uiMode === m.key ? ' active' : ''}`}
            onClick={() => pickMode(m)}
          >
            <span className="mode-icon"><m.Icon size={19} /></span>
            {m.label}
          </button>
        ))}
      </div>

      <div className="fields">
        <label className="field">
          <span className="field-icon"><I.Pin /></span>
          <input
            className="field-input"
            placeholder="어디로 갈까요? (성수동, 가평…)"
            value={value.region}
            onChange={(e) => set('region', e.target.value)}
            aria-label="지역"
            autoComplete="off"
          />
        </label>
        <label className="field">
          <span className="field-icon"><I.Calendar /></span>
          <input
            className="field-input"
            type="date"
            value={value.date}
            onChange={(e) => set('date', e.target.value)}
            aria-label="날짜"
          />
          {value.mode === 'trip' && (
            <select
              className="field-select"
              value={value.days}
              onChange={(e) => set('days', Number(e.target.value))}
              aria-label="여행 일수"
            >
              <option value={2}>1박 2일</option>
              <option value={3}>2박 3일</option>
            </select>
          )}
        </label>
        {value.mode === 'trip' && (
          <label className="field">
            <span className="field-icon"><I.Pin /></span>
            <input
              className="field-input"
              placeholder="숙소를 정했다면 이름 (선택, 비우면 추천)"
              value={value.lodging ?? ''}
              maxLength={80}
              onChange={(e) => set('lodging', e.target.value)}
              aria-label="숙소"
              autoComplete="off"
            />
          </label>
        )}
        <div className="field field-seg" role="radiogroup" aria-label="교통수단">
          <span className="field-icon">{value.transport === 'car' ? <I.Car /> : <I.Walk />}</span>
          <button
            type="button"
            role="radio"
            aria-checked={value.transport === 'walk'}
            className={`seg${value.transport === 'walk' ? ' on' : ''}`}
            onClick={() => set('transport', 'walk')}
          >
            뚜벅이
          </button>
          <button
            type="button"
            role="radio"
            aria-checked={value.transport === 'car'}
            className={`seg${value.transport === 'car' ? ' on' : ''}`}
            onClick={() => set('transport', 'car')}
          >
            자차
          </button>
        </div>
      </div>

      <button type="button" className="more-toggle" onClick={() => setMore((v) => !v)} aria-expanded={more}>
        <I.Sliders size={16} />
        상세 조건 {more ? '접기' : '펼치기'}
        {!more && value.moods.length > 0 && <span className="more-count">{value.moods.length}</span>}
        <I.Chevron className={`chevron${more ? ' up' : ''}`} />
      </button>

      {more && (
        <div className="more">
          <div className="more-row">
            <label className="more-field">
              <span>시작</span>
              <input type="time" value={value.start_time} onChange={(e) => set('start_time', e.target.value)} step={1800} />
            </label>
            <label className="more-field">
              <span>종료</span>
              <input type="time" value={value.end_time} onChange={(e) => set('end_time', e.target.value)} step={1800} />
            </label>
            <label className="more-field grow">
              <span>동행</span>
              <input
                placeholder="연인 / 가족(아이 2) / 친구"
                value={value.party}
                onChange={(e) => set('party', e.target.value)}
              />
            </label>
          </div>

          <label className="more-field">
            <span>
              1인 예산 <strong>{formatBudget(value.budget)}</strong>
              <small className="muted"> {value.mode === 'trip' ? `· ${value.days}일 전체 합계 (숙박비 제외)` : '· 하루 합계'}</small>
            </span>
            <input
              type="range"
              min={0}
              max={300_000}
              step={10_000}
              value={value.budget}
              onChange={(e) => set('budget', Number(e.target.value))}
              aria-valuetext={formatBudget(value.budget)}
            />
          </label>

          <div className="more-field">
            <span>분위기 (여러 개 선택)</span>
            <div className="moods" role="group" aria-label="분위기 태그">
              {moods.map((m) => (
                <button
                  key={m}
                  type="button"
                  className={`mood${value.moods.includes(m) ? ' on' : ''}`}
                  aria-pressed={value.moods.includes(m)}
                  onClick={() => toggleMood(m)}
                >
                  {m}
                </button>
              ))}
            </div>
          </div>

          <label className="more-field">
            <span>자유 조건</span>
            <input
              placeholder="예) 비건 메뉴 있는 식당 하나는 꼭, 주차 편한 곳"
              value={value.free_text}
              maxLength={300}
              onChange={(e) => set('free_text', e.target.value)}
            />
          </label>
        </div>
      )}

      {error && (
        <p className="form-error" role="alert">
          {error}
        </p>
      )}

      <button className="cta" type="submit">
        <I.Sparkle size={20} />
        <span>{submitLabel}</span>
        <span className="cta-arrow">→</span>
      </button>
    </form>
  )
}
