// /plan: 조건 요약 + 진행 상태 + 채팅(결과·수정) | 지도 스플릿 뷰
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import {
  createCourse,
  editCourse,
  getMoods,
  getPublicConfig,
  isNetworkError,
  MOODS,
  startCourse,
  startEdit,
  subscribeStream,
  type CourseRequest,
  type CourseResponse,
  type EditRequest,
  type TraceStep,
} from './api'
import Builder from './Builder'
import * as I from './Icons'
import MapView from './MapView'
import { DAY_COLORS, KIND_COLOR, KIND_LABEL, kakaoReviewLink, kakaoRouteLink, kakaoToLink, kindColor, placeKind, type Kind } from './mapUtil'
import { renderMarkdown } from './markdown'
import { EDIT_NODES, GENERATE_NODES, MOCK_ENABLED, mockCourse, mockEdit, simulateProgress } from './mock'
import Progress from './Progress'
import { initialSteps, type StepState } from './steps'
import { formatDate, loadCourse, loadRequest, saveCourse, saveRequest, shareConditions, summarize } from './request'
import './Plan.css'

type Phase = 'idle' | 'running' | 'done' | 'error'
interface ChatMsg {
  id: string
  role: 'user' | 'odiro'
  text: string
  course?: CourseResponse
}

const QUICK_GLOBAL = [
  { label: '더 조용한 곳으로', instruction: '전체적으로 더 조용하고 한적한 곳 위주로 바꿔줘' },
  { label: '실내 위주로', instruction: '비 와도 괜찮게 실내 장소 위주로 바꿔줘' },
  { label: '예산 낮춰줘', instruction: '예산을 30% 정도 낮춰서 가성비 좋은 곳으로 바꿔줘' },
]

export default function Plan() {
  const navigate = useNavigate()
  const location = useLocation()
  const navState = (location.state ?? {}) as { request?: CourseRequest; fresh?: boolean }

  const [req, setReq] = useState<CourseRequest | null>(() => navState.request ?? loadRequest())
  const [draft, setDraft] = useState<CourseRequest | null>(null) // 드로어 편집용
  const [course, setCourse] = useState<CourseResponse | null>(() => (navState.fresh ? null : loadCourse()))
  const [chat, setChat] = useState<ChatMsg[]>([])
  const [steps, setSteps] = useState<StepState[]>(initialSteps(GENERATE_NODES))
  const [phase, setPhase] = useState<Phase>('idle')
  const [error, setError] = useState<string | null>(null)
  const [slow, setSlow] = useState(false)
  const [elapsed, setElapsed] = useState(0)
  const [selected, setSelected] = useState<number | null>(null)
  const [moods, setMoods] = useState<string[]>([...MOODS])
  const [kakaoKey, setKakaoKey] = useState<string | undefined>(undefined)
  const [input, setInput] = useState('')
  const [toast, setToast] = useState<string | null>(null)
  const [usingMock, setUsingMock] = useState(MOCK_ENABLED)
  const [shareOpen, setShareOpen] = useState(false)
  const [shareOverride, setShareOverride] = useState<Record<string, boolean>>({}) // 사용자가 바꾼 체크 상태
  const shareRef = useRef<HTMLDivElement>(null)

  const cancelRef = useRef<(() => void) | null>(null)
  const startedFor = useRef<string | null>(null)
  const chatEnd = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!req) navigate('/', { replace: true })
  }, [req, navigate])

  useEffect(() => {
    getMoods().then(setMoods).catch(() => undefined)
    getPublicConfig()
      .then((c) => setKakaoKey(c.kakao_js_api_key || ''))
      .catch(() => setKakaoKey(''))
  }, [])

  // 진행 중 경과 시간 / 45초 안내
  useEffect(() => {
    if (phase !== 'running') return
    const t0 = Date.now()
    setElapsed(0)
    setSlow(false)
    const tick = window.setInterval(() => setElapsed(Date.now() - t0), 500)
    const slowTimer = window.setTimeout(() => setSlow(true), 45_000)
    return () => {
      window.clearInterval(tick)
      window.clearTimeout(slowTimer)
    }
  }, [phase])

  useEffect(() => {
    chatEnd.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [chat, phase])

  const applyStep = useCallback((s: TraceStep) => {
    setSteps((prev) => {
      const i = prev.findIndex((p) => p.node === s.node)
      if (i < 0) return [...prev, { ...s }]
      const next = [...prev]
      next[i] = { ...s }
      return next
    })
  }, [])

  const finish = useCallback((c: CourseResponse, userText?: string) => {
    setCourse(c)
    saveCourse(c)
    setSelected(null)
    setPhase('done')
    setChat((prev) => [
      ...prev,
      ...(userText ? [{ id: `u${Date.now()}`, role: 'user' as const, text: userText }] : []),
      { id: c.course_id, role: 'odiro' as const, text: c.answer_md, course: c },
    ])
    setSteps((prev) => prev.map((s) => (s.status === 'start' || s.status === 'pending' ? { ...s, status: 'done' } : s)))
  }, [])

  const fail = useCallback((msg: string) => {
    setError(msg)
    setPhase('error')
    setSteps((prev) => prev.map((s) => (s.status === 'start' ? { ...s, status: 'error' } : s)))
  }, [])

  /** 생성/수정 공통 실행기. SSE → (첫 이벤트 전 실패 시) 동기 API → (네트워크 불가 시) 목 */
  const run = useCallback(
    async (
      nodes: readonly string[],
      start: () => Promise<{ job_id: string; stream_url: string }>,
      sync: () => Promise<CourseResponse>,
      mock: () => CourseResponse,
      userText?: string,
    ) => {
      cancelRef.current?.()
      setSteps(initialSteps(nodes))
      setError(null)
      setPhase('running')
      if (userText) setChat((prev) => [...prev, { id: `u${Date.now()}`, role: 'user', text: userText }])

      const fallbackToMock = () => {
        setUsingMock(true)
        const result = mock()
        cancelRef.current = simulateProgress(nodes, applyStep, () => finish(result))
      }
      if (MOCK_ENABLED) return fallbackToMock()

      try {
        const job = await start()
        cancelRef.current = subscribeStream(job.stream_url, {
          onProgress: applyStep,
          onResult: (c) => finish(c),
          onError: async (m) => {
            if (m !== '__before_first__') return fail(m)
            try {
              finish(await sync())
            } catch (e) {
              fail(e instanceof Error ? e.message : String(e))
            }
          },
        })
      } catch (e) {
        if (isNetworkError(e)) return fallbackToMock()
        const detail = (e as { response?: { data?: { detail?: string } } }).response?.data?.detail
        fail(detail ?? (e instanceof Error ? e.message : String(e)))
      }
    },
    [applyStep, finish, fail],
  )

  const generate = useCallback(
    (r: CourseRequest) => {
      setChat([])
      void run(GENERATE_NODES, () => startCourse(r), () => createCourse(r), () => mockCourse(r))
    },
    [run],
  )

  const edit = useCallback(
    (instruction: string, targetOrder: number | null = null, targetDay = 1) => {
      if (!course) return
      const body: EditRequest = { course, instruction, target_order: targetOrder, target_day: targetDay }
      void run(
        EDIT_NODES,
        () => startEdit(body),
        () => editCourse(body),
        () => mockEdit(course, instruction, targetOrder),
        instruction,
      )
    },
    [course, run],
  )

  // 첫 진입: 저장된 코스가 없으면 생성 (StrictMode 이중 실행 방지)
  useEffect(() => {
    if (!req) return
    const key = JSON.stringify(req)
    if (course && course.request.region === req.region && !navState.fresh) {
      if (chat.length === 0) setChat([{ id: course.course_id, role: 'odiro', text: course.answer_md, course }])
      setPhase('done')
      return
    }
    if (startedFor.current === key) return
    startedFor.current = key
    generate(req)
    // 새로고침 때 또 생성하지 않도록 fresh 플래그를 history state 에서 지운다
    if (navState.fresh) navigate('/plan', { replace: true, state: { request: req } })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [req])

  useEffect(() => () => cancelRef.current?.(), [])

  const submitDraft = () => {
    if (!draft) return
    saveRequest(draft)
    saveCourse(null)
    setReq(draft)
    setDraft(null)
    startedFor.current = JSON.stringify(draft)
    generate(draft)
  }

  const sendInput = () => {
    const text = input.trim()
    if (!text || phase === 'running') return
    setInput('')
    edit(text)
  }

  const shareItems = useMemo(() => (course ? shareConditions(course.request, course.meta.est_cost_total) : []), [course])
  const isShareOn = (c: { key: string; defaultOn: boolean }) => shareOverride[c.key] ?? c.defaultOn

  useEffect(() => {
    if (!shareOpen) return
    const onDown = (e: MouseEvent) => {
      if (shareRef.current && !shareRef.current.contains(e.target as Node)) setShareOpen(false)
    }
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && setShareOpen(false)
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [shareOpen])

  const showToast = (msg: string) => {
    setToast(msg)
    window.setTimeout(() => setToast(null), 2500)
  }

  /** 체크된 조건만 넣은 공유 텍스트 */
  const buildShareText = (): string => {
    if (!course) return ''
    const r = course.request
    const car = r.transport === 'car'
    const trip = r.mode === 'trip'
    const picked = shareItems.filter(isShareOn)
    const lines = [
      `[Odiro] ${course.title || `${r.region} 코스`} · ${formatDate(r.date)}`,
      ...(picked.length ? ['', '📋 이런 조건으로 짠 코스예요', ...picked.map((c) => `· ${c.text}`)] : []),
    ]
    byDay.forEach(([day, idxs]) => {
      const ps = idxs.map((i) => course.places[i])
      lines.push('', trip ? `■ Day ${day}` : '■ 코스')
      ps.forEach((p) =>
        lines.push(`${p.order}. ${p.name}${p.arrive ? ` (${p.arrive})` : ''} — ${p.address}`, `   ${p.place_url || kakaoToLink(p)}`),
      )
      const route = kakaoRouteLink(ps, car ? 'car' : 'walk')
      if (route) {
        // 카카오맵 경로는 출발·도착·경유지 5곳, 최대 7곳까지만 받는다
        lines.push(`${car ? '🚗 전체 경로 (자차)' : '🚶 전체 경로 (도보)'}${ps.length > 7 ? ' · 앞 7곳' : ''}: ${route}`)
      }
    })
    lines.push('', 'https://odiro-where.web.app')
    return lines.join('\n')
  }

  const copyShare = async () => {
    try {
      await navigator.clipboard.writeText(buildShareText())
      showToast('코스를 복사했어요. 메신저에 붙여넣기!')
      setShareOpen(false)
    } catch {
      showToast('복사에 실패했어요. 브라우저 권한을 확인해 주세요.')
    }
  }


  const byDay = useMemo(() => {
    const m = new Map<number, number[]>()
    course?.places.forEach((p, i) => m.set(p.day, [...(m.get(p.day) ?? []), i]))
    return [...m.entries()].sort((a, b) => a[0] - b[0])
  }, [course])

  if (!req) return null

  return (
    <div className="plan">
      <header className="plan-header">
        <a className="brand" href="/">
          <span className="brand-pin" aria-hidden="true" />
          <span className="brand-name">odiro<span className="brand-dot">.</span></span>
        </a>
        <button className="cond" onClick={() => setDraft({ ...req })} title="조건 바꾸기">
          <I.Sliders size={16} />
          <span className="cond-text">{summarize(req)}</span>
          <I.Chevron className="chevron" />
        </button>
        <div className="plan-actions">
          {usingMock && <span className="mock-badge" title="백엔드에 연결되지 않아 예시 데이터를 보여줍니다">예시 모드</span>}
          <button className="btn btn-ghost" onClick={() => generate(req)} disabled={phase === 'running'}>
            <I.Refresh size={16} /> 다시 만들기
          </button>
          <div className="share-wrap" ref={shareRef}>
            <button
              className="btn btn-primary"
              onClick={() => setShareOpen((o) => !o)}
              disabled={!course}
              aria-expanded={shareOpen}
              aria-haspopup="dialog"
            >
              <I.Share size={16} /> 공유
            </button>
            {shareOpen && course && (
              <div className="share-pop" role="dialog" aria-label="공유 설정">
                <p className="share-title">함께 보낼 조건</p>
                <p className="share-hint">체크한 항목이 공유 글에 들어가요. 장소·경로 링크는 항상 포함돼요.</p>
                <div className="share-checks">
                  {shareItems.map((c) => (
                    <label key={c.key} className="share-check">
                      <input
                        type="checkbox"
                        checked={isShareOn(c)}
                        onChange={(e) => setShareOverride((o) => ({ ...o, [c.key]: e.target.checked }))}
                      />
                      <span>{c.label}</span>
                    </label>
                  ))}
                </div>
                <div className="share-actions">
                  <button className="share-btn primary" onClick={copyShare}>복사하기</button>
                </div>
              </div>
            )}
          </div>
        </div>
      </header>

      <div className="plan-body">
        <aside className="left">
          <Progress steps={steps} running={phase === 'running'} elapsedMs={elapsed} />

          {course && (
            <div className="info-strip">
              {course.meta.sun.sunrise && (
                <span><I.Sun size={14} /> 일출 {course.meta.sun.sunrise} · 일몰 {course.meta.sun.sunset}</span>
              )}
              {course.meta.weather.available && (
                <span className={course.meta.weather.rain ? 'rain' : ''}>
                  {course.meta.weather.rain ? <I.Rain size={14} /> : <I.Sun size={14} />}
                  {course.meta.weather.summary}
                  {course.meta.weather.temp_c !== null && ` ${Math.round(course.meta.weather.temp_c)}°`}
                  {course.meta.weather.pop !== null && ` · 강수 ${Math.round(course.meta.weather.pop * 100)}%`}
                </span>
              )}
              {course.meta.weather.rain && <span className="badge-rain">비 예보 → 실내 위주</span>}
              {!!course.meta.est_cost_total && (
                <span
                  className={course.request.budget > 0 && course.meta.est_cost_total > course.request.budget ? 'over' : ''}
                  title="장소별 1인 예상 비용의 합계 (추정치, 숙박비 제외)"
                >
                  1인 예상 약 {course.meta.est_cost_total.toLocaleString('ko-KR')}원
                  {course.request.budget > 0 &&
                    ` / 예산 ${course.request.budget.toLocaleString('ko-KR')}원${course.request.mode === 'trip' ? ` (${course.request.days}일 합계)` : ''}`}
                </span>
              )}
              <span className="muted">RAG {course.meta.rag_docs} · 웹 {course.meta.web_docs}{course.meta.cached ? ' · 캐시' : ''}</span>
            </div>
          )}
          {course && course.meta.warnings.length > 0 && (
            <ul className="warnings">
              {course.meta.warnings.map((w) => (
                <li key={w}>{w}</li>
              ))}
            </ul>
          )}

          <section className="chat" aria-label="대화">
            {chat.map((m) =>
              m.role === 'user' ? (
                <div key={m.id} className="msg user">{m.text}</div>
              ) : (
                <div key={m.id} className="msg odiro">
                  <span className="avatar" aria-hidden="true" />
                  <div className="bubble">
                    <div className="md" dangerouslySetInnerHTML={{ __html: renderMarkdown(m.text) }} />
                    {m.course && m.course.course_id === course?.course_id && (
                      <div className="places">
                        <div className="legend" aria-label="색 구분">
                          {(Object.keys(KIND_COLOR) as Kind[])
                            .filter((k) => course.places.some((p) => placeKind(p.category) === k))
                            .map((k) => (
                              <span key={k}><i style={{ background: KIND_COLOR[k] }} />{KIND_LABEL[k]}</span>
                            ))}
                        </div>
                        {byDay.map(([day, idxs]) => (
                          <div key={day}>
                            <div className="day-label" style={{ color: DAY_COLORS[(day - 1) % DAY_COLORS.length] }}>
                              {course.request.mode === 'trip' && <span>Day {day}</span>}
                              {idxs.length >= 2 && (
                                <a
                                  className="nav-link"
                                  href={kakaoRouteLink(idxs.map((i) => course.places[i]), course.request.transport === 'car' ? 'car' : 'walk')}
                                  target="_blank"
                                  rel="noopener noreferrer"
                                  title="이 날의 장소를 순서대로 잇는 경로를 카카오맵에서 엽니다 (앱에서 내비 시작 가능)"
                                >
                                  {course.request.transport === 'car' ? '🚗 내비로 전체 경로 열기' : '🚶 도보 경로 열기'}
                                </a>
                              )}
                            </div>
                            {idxs.map((i) => {
                              const p = course.places[i]
                              return (
                                <button
                                  key={`${p.day}-${p.order}`}
                                  className={`place-card${selected === i ? ' selected' : ''}`}
                                  onClick={() => setSelected(i)}
                                >
                                  <span className="pc-order" style={{ background: kindColor(p) }}>
                                    {p.order}
                                  </span>
                                  <span className="pc-body">
                                    <span className="pc-title">
                                      <strong>{p.name}</strong>
                                      <span className="pc-kind" style={{ color: kindColor(p) }}> {p.category}</span>
                                      {p.arrive && <span className="pc-time"><I.Clock size={12} /> {p.arrive} · {p.stay_min}분</span>}
                                    </span>
                                    {p.reason && <span className="pc-reason">{p.reason}</span>}
                                    {(!!p.est_cost || !!p.parking) && (
                                      <span className="pc-extra">
                                        {!!p.est_cost && <span>1인 약 {p.est_cost.toLocaleString('ko-KR')}원</span>}
                                        {!!p.parking && <span>주차 {p.parking}</span>}
                                      </span>
                                    )}
                                    {p.review_summary && <span className="pc-review">💬 {p.review_summary}</span>}
                                    {p.tags.length > 0 && (
                                      <span className="chips">
                                        {p.tags.map((t) => (
                                          <span key={t} className="chip">{t}</span>
                                        ))}
                                      </span>
                                    )}
                                    <span className="pc-links">
                                      {[
                                        { label: '리뷰 보기', href: kakaoReviewLink(p) },
                                        { label: course.request.transport === 'car' ? '내비·길찾기' : '길찾기', href: kakaoToLink(p) },
                                      ].map((l) => (
                                        <span
                                          key={l.label}
                                          className="pc-link"
                                          role="link"
                                          tabIndex={0}
                                          onClick={(e) => {
                                            e.stopPropagation()
                                            window.open(l.href, '_blank', 'noopener,noreferrer')
                                          }}
                                          onKeyDown={(e) => {
                                            if (e.key === 'Enter') {
                                              e.stopPropagation()
                                              window.open(l.href, '_blank', 'noopener,noreferrer')
                                            }
                                          }}
                                        >
                                          {l.label} ↗
                                        </span>
                                      ))}
                                    </span>
                                  </span>
                                  <span
                                    className="pc-edit"
                                    role="button"
                                    tabIndex={0}
                                    title={`${p.order}번 장소 바꿔줘`}
                                    onClick={(e) => {
                                      e.stopPropagation()
                                      edit(`${p.order}번 장소(${p.name})를 다른 곳으로 바꿔줘`, p.order, p.day)
                                    }}
                                    onKeyDown={(e) => {
                                      if (e.key === 'Enter' || e.key === ' ') {
                                        e.preventDefault()
                                        e.stopPropagation()
                                        edit(`${p.order}번 장소(${p.name})를 다른 곳으로 바꿔줘`, p.order, p.day)
                                      }
                                    }}
                                  >
                                    <I.Refresh size={14} /> 바꾸기
                                  </span>
                                </button>
                              )
                            })}
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                </div>
              ),
            )}

            {phase === 'running' && (
              <div className="msg odiro">
                <span className="avatar" aria-hidden="true" />
                <div className="bubble thinking">
                  <span className="dots"><i /><i /><i /></span>
                  {slow ? '조금 오래 걸리고 있어요. 외부 지도·날씨 API 응답을 기다리는 중이에요…' : '코스를 짜고 있어요…'}
                </div>
              </div>
            )}
            {phase === 'error' && (
              <div className="msg odiro">
                <span className="avatar" aria-hidden="true" />
                <div className="bubble error">
                  <strong>코스를 만들지 못했어요.</strong>
                  <div className="small">{error}</div>
                  <button className="btn btn-ghost small-btn" onClick={() => generate(req)}>다시 시도</button>
                </div>
              </div>
            )}
            <div ref={chatEnd} />
          </section>

          {course && phase !== 'running' && (
            <div className="quick" aria-label="빠른 수정">
              {QUICK_GLOBAL.map((q) => (
                <button key={q.label} className="quick-btn" onClick={() => edit(q.instruction)}>
                  {q.label}
                </button>
              ))}
            </div>
          )}

          <form
            className="composer"
            onSubmit={(e) => {
              e.preventDefault()
              sendInput()
            }}
          >
            <input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder={course ? '예) 두 번째 카페를 조용한 곳으로 바꿔줘' : '코스가 완성되면 대화로 수정할 수 있어요'}
              disabled={!course || phase === 'running'}
              aria-label="수정 요청"
            />
            <button type="submit" className="send" disabled={!course || phase === 'running' || !input.trim()} aria-label="보내기">
              <I.Send size={18} />
            </button>
          </form>
        </aside>

        <main className="right">
          <MapView kakaoKey={kakaoKey} places={course?.places ?? []} legs={course?.legs ?? []} selected={selected} onSelect={setSelected} />
          {course && (
            <div className="map-links">
              <strong>{course.title || `${course.request.region} 코스`}</strong>
              <span className="muted"> · 카카오맵으로 보기:</span>
              {course.places.map((p) => (
                <a key={`${p.day}-${p.order}`} href={p.place_url || kakaoToLink(p)} target="_blank" rel="noopener noreferrer">
                  {p.order}. {p.name}
                </a>
              ))}
            </div>
          )}
        </main>
      </div>

      {draft && (
        <div className="drawer-backdrop" onClick={() => setDraft(null)}>
          <div className="drawer" role="dialog" aria-modal="true" aria-label="조건 바꾸기" onClick={(e) => e.stopPropagation()}>
            <div className="drawer-head">
              <strong>조건 바꾸기</strong>
              <button className="icon-btn" aria-label="닫기" onClick={() => setDraft(null)}>
                <I.Close size={18} />
              </button>
            </div>
            <Builder value={draft} onChange={setDraft} moods={moods} onSubmit={submitDraft} submitLabel="이 조건으로 다시 만들기" expanded />
          </div>
        </div>
      )}

      {toast && <div className="toast" role="status">{toast}</div>}
    </div>
  )
}
