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
import { DAY_COLORS, kakaoToLink } from './mapUtil'
import { renderMarkdown } from './markdown'
import { EDIT_NODES, GENERATE_NODES, MOCK_ENABLED, mockCourse, mockEdit, simulateProgress } from './mock'
import Progress from './Progress'
import { initialSteps, type StepState } from './steps'
import { formatDate, loadCourse, loadRequest, saveCourse, saveRequest, summarize } from './request'
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

  const share = async () => {
    if (!course) return
    const lines = [
      `[Odiro] ${course.title || `${course.request.region} 코스`} · ${formatDate(course.request.date)}`,
      ...course.places.map(
        (p) =>
          `${course.request.mode === 'trip' ? `Day${p.day} ` : ''}${p.order}. ${p.name}${p.arrive ? ` (${p.arrive})` : ''} — ${p.address}\n   ${p.place_url || kakaoToLink(p)}`,
      ),
      '',
      'https://odiro-where.web.app',
    ]
    try {
      await navigator.clipboard.writeText(lines.join('\n'))
      setToast('코스를 복사했어요. 메신저에 붙여넣기!')
    } catch {
      setToast('복사에 실패했어요. 브라우저 권한을 확인해 주세요.')
    }
    window.setTimeout(() => setToast(null), 2500)
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
          <button className="btn btn-primary" onClick={share} disabled={!course}>
            <I.Share size={16} /> 공유
          </button>
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
                        {byDay.map(([day, idxs]) => (
                          <div key={day}>
                            {course.request.mode === 'trip' && (
                              <div className="day-label" style={{ color: DAY_COLORS[(day - 1) % DAY_COLORS.length] }}>
                                Day {day}
                              </div>
                            )}
                            {idxs.map((i) => {
                              const p = course.places[i]
                              return (
                                <button
                                  key={`${p.day}-${p.order}`}
                                  className={`place-card${selected === i ? ' selected' : ''}`}
                                  onClick={() => setSelected(i)}
                                >
                                  <span className="pc-order" style={{ background: DAY_COLORS[(p.day - 1) % DAY_COLORS.length] }}>
                                    {p.order}
                                  </span>
                                  <span className="pc-body">
                                    <span className="pc-title">
                                      <strong>{p.name}</strong>
                                      <span className="muted"> {p.category}</span>
                                      {p.arrive && <span className="pc-time"><I.Clock size={12} /> {p.arrive} · {p.stay_min}분</span>}
                                    </span>
                                    {p.reason && <span className="pc-reason">{p.reason}</span>}
                                    {(!!p.est_cost || !!p.parking) && (
                                      <span className="pc-extra">
                                        {!!p.est_cost && <span>1인 약 {p.est_cost.toLocaleString('ko-KR')}원</span>}
                                        {!!p.parking && <span>주차 {p.parking}</span>}
                                      </span>
                                    )}
                                    {p.tags.length > 0 && (
                                      <span className="chips">
                                        {p.tags.map((t) => (
                                          <span key={t} className="chip">{t}</span>
                                        ))}
                                      </span>
                                    )}
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
