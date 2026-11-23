// /plan: 조건 요약 + 진행 상태 + 채팅(결과·수정) | 지도 스플릿 뷰
import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import {
  createCourse,
  editCourse,
  getMoods,
  getPublicConfig,
  MOODS,
  MSG_DISCONNECTED,
  MSG_TIMEOUT,
  serverErrorMessage,
  startCourse,
  startEdit,
  STREAM_BEFORE_FIRST,
  STREAM_DISCONNECTED,
  STREAM_TIMEOUT,
  subscribeStream,
  toUserMessage,
  type CourseRequest,
  type CourseResponse,
  type EditRequest,
  type TraceStep,
} from './api'
import Builder from './Builder'
import DayTabs from './DayTabs'
import * as I from './Icons'
import MapView from './MapView'
import { DAY_COLORS, KIND_COLOR, KIND_LABEL, kakaoRouteLink, kakaoToLink, kindColor, legLabel, placeKind, type Kind } from './mapUtil'
import { renderMarkdown, splitAnswer } from './markdown'
import { EDIT_NODES, GENERATE_NODES, MOCK_ENABLED, mockCourse, mockEdit, simulateProgress } from './mock'
import Progress from './Progress'
import { initialSteps, type StepState } from './steps'
import { formatDate, loadCourse, loadRequest, saveCourse, saveRequest, shareConditions, summarize, withValidDate } from './request'
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

  // 랜딩에서 막 넘어온 조건은 그대로. 저장된 코스를 다시 보여 주는 경우(새로고침 복원)는 날짜를 바꾸지 않고,
  // 복원할 코스가 없어 새로 만들게 되는 경우만 지난 날짜를 기본 날짜로 바꾼다
  const [req, setReq] = useState<CourseRequest | null>(() => {
    if (navState.fresh) return navState.request ?? loadRequest()
    const r = navState.request ?? loadRequest({ keepDate: true })
    return r && !loadCourse() ? withValidDate(r) : r
  })
  const [draft, setDraft] = useState<CourseRequest | null>(null) // 드로어 편집용
  const [course, setCourse] = useState<CourseResponse | null>(() => (navState.fresh ? null : loadCourse()))
  const [chat, setChat] = useState<ChatMsg[]>([])
  const [steps, setSteps] = useState<StepState[]>(initialSteps(GENERATE_NODES))
  const [phase, setPhase] = useState<Phase>('idle')
  const [error, setError] = useState<string | null>(null)
  const [slow, setSlow] = useState(false)
  const [elapsed, setElapsed] = useState(0)
  const [selected, setSelected] = useState<number | null>(null)
  // 사용자가 카드·핀을 눌러 고른 장소 → 지도가 그 장소로 이동. 자동 선택(첫 장소·Day 탭)은 이동하지 않고 전체 보기를 유지
  const [focus, setFocus] = useState<{ idx: number; seq: number } | null>(null)
  const [activeDay, setActiveDay] = useState(1)
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

  // 지도 키: '' 는 서버가 "키 없음"이라고 답한 것(개발자 설정 문제), mapConfigFailed 는 설정 요청 자체가 실패한 것(서버 연결 문제)
  const [mapConfigFailed, setMapConfigFailed] = useState(false)
  const loadMapConfig = useCallback(() => {
    getPublicConfig()
      .then((c) => {
        setKakaoKey(c.kakao_js_api_key || '')
        setMapConfigFailed(false)
      })
      .catch((e) => {
        if (MOCK_ENABLED) return setKakaoKey('') // 목업 모드는 백엔드 없이 도는 게 정상 → 지금처럼 키 미설정 안내
        console.error('[odiro] 지도 설정을 받지 못함:', e)
        setMapConfigFailed(true)
      })
  }, [])

  useEffect(() => {
    getMoods().then(setMoods).catch(() => undefined)
    loadMapConfig()
  }, [loadMapConfig])

  // 설정을 못 받았으면 서버가 돌아올 때까지 15초마다 다시 요청 (화면을 떠나면 정리)
  useEffect(() => {
    if (!mapConfigFailed) return
    const t = window.setInterval(loadMapConfig, 15_000)
    return () => window.clearInterval(t)
  }, [mapConfigFailed, loadMapConfig])

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

  // 지도 핀을 눌러 장소를 고르면 채팅창의 장소 카드도 화면 안으로 가져온다.
  // 채팅 영역(.chat)만 스크롤한다 (scrollIntoView 는 모바일에서 페이지 전체를 움직여 지도가 밀려난다).
  useEffect(() => {
    if (selected === null) return
    const card = document.querySelector<HTMLElement>(`.place-card[data-place-idx="${selected}"]`)
    const scroller = card?.closest<HTMLElement>('.chat')
    if (!card || !scroller) return
    const c = card.getBoundingClientRect()
    const s = scroller.getBoundingClientRect()
    if (c.top >= s.top && c.bottom <= s.bottom) return // 이미 보이면 그대로
    const centered = scroller.scrollTop + (c.top - s.top) - (s.height - c.height) / 2
    scroller.scrollTo({ top: Math.max(0, centered), behavior: 'smooth' })
  }, [selected])

  // 수정(바꾸기·자유 문장) 뒤에 유지할 날. 카드의 바꾸기는 그 장소의 날, 자유 문장은 보던 날. 생성·복원이면 null
  const keepDayRef = useRef<number | null>(null)

  // 새 코스가 들어오면(생성·저장본 복원) 첫날로 돌아가 1번 장소의 정보 창을 띄운다.
  // 핀을 눌러야 정보가 나온다는 걸 처음 보는 사용자가 알 수 있게 하기 위해서다.
  // 수정 결과면 수정한 날(그 날이 새 코스에 없으면 첫날)을 유지한다 — 장소 목록 탭·지도 탭 모두 activeDay 를 따른다.
  useEffect(() => {
    if (!course || !course.places.length) return
    const keep = keepDayRef.current
    keepDayRef.current = null
    const kept = keep === null ? -1 : course.places.findIndex((p) => p.day === keep)
    const first = kept >= 0 ? kept : course.places.reduce((a, p, i) => (p.day < course.places[a].day ? i : a), 0)
    setActiveDay(course.places[first].day)
    setSelected(first)
  }, [course])

  const selectPlace = useCallback(
    (idx: number | null) => {
      setSelected(idx)
      const day = idx === null ? undefined : course?.places[idx]?.day
      if (day !== undefined) setActiveDay(day)
      if (idx !== null) setFocus((f) => ({ idx, seq: (f?.seq ?? 0) + 1 }))
    },
    [course],
  )

  const changeDay = useCallback(
    (day: number) => {
      setActiveDay(day)
      const first = course?.places.findIndex((p) => p.day === day) ?? -1
      setSelected(first >= 0 ? first : null)
    },
    [course],
  )

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
    // 채팅으로 '첫째날 9시 시작' 처럼 바꾼 시작 시각(day_starts)은 이 코스(course.request)에만 남는다.
    // 화면의 조건(req)에는 합치지 않으므로 '다시 만들기'·새 코스는 기본 시작 시각으로 만든다.
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

  // 실행 번호: 새 요청을 시작하거나 화면을 떠나면 올린다 → 늦게 도착한 이전 요청의 결과·오류는 버린다
  const runSeq = useRef(0)
  const mounted = useRef(true)
  // 실패했을 때 '다시 시도'가 같은 작업(생성 또는 그 수정)을 다시 하게 한다
  const retryRef = useRef<(() => void) | null>(null)
  const [failedAction, setFailedAction] = useState<'generate' | 'edit'>('generate')

  /**
   * 생성/수정 공통 실행기. SSE → (첫 이벤트 전 실패 시) 동기 API.
   * 목 결과는 VITE_MOCK=1 일 때만 쓴다 (배포 환경에서 연결이 안 될 때 예시 코스를 실제 결과처럼 보이지 않게).
   * 실패하면 이전 코스는 그대로 두고 오류 문구와 '다시 시도'를 보여 준다.
   */
  const run = useCallback(
    async (
      action: 'generate' | 'edit',
      nodes: readonly string[],
      start: () => Promise<{ job_id: string; stream_url: string }>,
      sync: () => Promise<CourseResponse>,
      mock: () => CourseResponse,
      userText?: string,
    ) => {
      cancelRef.current?.()
      cancelRef.current = null
      const my = ++runSeq.current
      const current = () => runSeq.current === my && mounted.current
      // 다시 시도: 같은 요청을 다시 보낸다 (채팅의 사용자 말풍선은 이미 있으므로 다시 넣지 않는다)
      retryRef.current = () => void run(action, nodes, start, sync, mock)
      setFailedAction(action)
      setSteps(initialSteps(nodes))
      setError(null)
      setPhase('running')
      if (userText) setChat((prev) => [...prev, { id: `u${Date.now()}`, role: 'user', text: userText }])

      if (MOCK_ENABLED) {
        setUsingMock(true)
        const result = mock()
        cancelRef.current = simulateProgress(nodes, applyStep, () => finish(result))
        return
      }

      const failNow = (msg: string) => current() && fail(msg)
      try {
        const job = await start()
        if (!current()) return // 그 사이 새 요청을 시작했거나 화면을 떠났다
        cancelRef.current = subscribeStream(job.stream_url, {
          onProgress: (s) => current() && applyStep(s),
          onResult: (c) => current() && finish(c),
          onError: async (m) => {
            if (m === STREAM_DISCONNECTED) return failNow(MSG_DISCONNECTED)
            if (m === STREAM_TIMEOUT) return failNow(MSG_TIMEOUT)
            if (m !== STREAM_BEFORE_FIRST) return failNow(serverErrorMessage(m))
            // 진행 이벤트를 하나도 못 받고 끊겼다 → 동기 API 로 한 번 더. 그것도 실패하면 같은 오류 화면
            try {
              const c = await sync()
              if (current()) finish(c)
            } catch (e) {
              failNow(toUserMessage(e))
            }
          },
        })
      } catch (e) {
        failNow(toUserMessage(e))
      }
    },
    [applyStep, finish, fail],
  )

  /** refresh: '다시 만들기'처럼 같은 조건이어도 서버 캐시를 건너뛰고 새로 만들 때 */
  const generate = useCallback(
    (req0: CourseRequest, refresh = false) => {
      // 채팅으로 바꾼 시작 시각은 새 코스에 이어가지 않는다 (이전에 저장된 조건에 남은 값도 제거)
      const { day_starts: _drop, ...r } = req0
      void _drop
      keepDayRef.current = null // 새 코스는 첫날부터
      setChat([])
      void run('generate', GENERATE_NODES, () => startCourse(r, refresh), () => createCourse(r, refresh), () => mockCourse(r))
    },
    [run],
  )

  const edit = useCallback(
    (instruction: string, targetOrder: number | null = null, targetDay = 1) => {
      if (!course) return
      // 결과가 오면 이 날을 다시 보여 준다: 카드의 바꾸기는 그 장소의 날, 자유 문장·빠른 수정은 지금 보던 날
      keepDayRef.current = targetOrder !== null ? targetDay : activeDay
      const body: EditRequest = { course, instruction, target_order: targetOrder, target_day: targetDay }
      void run(
        'edit',
        EDIT_NODES,
        () => startEdit(body),
        () => editCourse(body),
        () => mockEdit(course, instruction, targetOrder),
        instruction,
      )
    },
    [course, run, activeDay],
  )

  // 첫 진입: 저장된 코스가 없으면 생성 (StrictMode 이중 실행 방지)
  useEffect(() => {
    if (!req) return
    const key = JSON.stringify(req)
    // 이미 이 조건으로 생성을 시작했다면(조건 바꾸기 → 다시 만들기) 이전 코스를 복원하지 않는다.
    // 복원하면 진행 상태가 'done' 으로 덮여 새로 만드는 중인데도 이전 결과만 보인다.
    if (startedFor.current === key) return
    if (course && course.request.region === req.region && !navState.fresh) {
      if (chat.length === 0) setChat([{ id: course.course_id, role: 'odiro', text: course.answer_md, course }])
      setPhase('done')
      return
    }
    startedFor.current = key
    generate(req)
    // 새로고침 때 또 생성하지 않도록 fresh 플래그를 history state 에서 지운다
    if (navState.fresh) navigate('/plan', { replace: true, state: { request: req } })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [req])

  // 화면을 떠나면 스트림·타이머를 닫고, 진행 중이던 요청의 늦은 결과는 버린다.
  // (개발 모드 StrictMode 는 마운트 직후 정리→재마운트를 한 번 흉내 내므로, 재마운트 때 다시 true 로 돌린다)
  useEffect(() => {
    mounted.current = true
    return () => {
      mounted.current = false
      cancelRef.current?.()
    }
  }, [])

  /**
   * 조건 드로어를 닫으면서 고친 조건을 적용한다 (바깥 클릭·X·Enter 모두 같다).
   * 새 코스는 만들지 않는다. 헤더의 '다시 만들기'가 이 조건으로 만든다.
   */
  const applyDraft = () => {
    if (!draft || !req) return setDraft(null)
    const next: CourseRequest = {
      ...draft,
      // 비우거나 잘못 입력한 채 닫았을 때는 이전 값을 유지
      region: draft.region.trim() || req.region,
      date: draft.date.length === 10 ? draft.date : req.date,
    }
    setDraft(null)
    if (JSON.stringify(next) === JSON.stringify(req)) return
    saveRequest(next)
    // 이 조건으로는 자동 생성하지 않도록 표시 (첫 진입 effect 가 지역이 바뀐 걸 보고 생성하는 것을 막는다)
    startedFor.current = JSON.stringify(next)
    setReq(next)
    showToast("조건을 바꿨어요. '다시 만들기'를 누르면 새 코스를 만들어요.")
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

  const days = byDay.map(([d]) => d)
  const shownDay = days.includes(activeDay) ? activeDay : (days[0] ?? 1)

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
          <button
            className="btn btn-ghost"
            onClick={() => generate(req, true)}
            disabled={phase === 'running'}
            aria-label="다시 만들기"
            title="다시 만들기"
          >
            <I.Refresh size={16} /> <span>다시 만들기</span>
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
          <Progress steps={steps} running={phase === 'running'} elapsedMs={elapsed} failed={phase === 'error'} />

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
                  {course.request.headcount > 1 &&
                    ` · ${course.request.headcount}명 약 ${(course.meta.est_cost_total * course.request.headcount).toLocaleString('ko-KR')}원`}
                  {course.request.budget > 0 &&
                    ` / 1인 예산 ${course.request.budget.toLocaleString('ko-KR')}원${course.request.mode === 'trip' ? ` (${course.request.days}일 합계)` : ''}`}
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
                    {/* 현재 코스의 답변은 장소 목록·이동 줄을 카드가 대신 보여주므로 글에서는 소개(앞)·팁(뒤)만 쓴다.
                        이전 코스의 답변은 카드가 없으니 글 전체를 그대로 보여준다 */}
                    <div
                      className="md"
                      dangerouslySetInnerHTML={{
                        __html: renderMarkdown(m.course && m.course.course_id === course?.course_id ? splitAnswer(m.text).head : m.text),
                      }}
                    />
                    {m.course && m.course.course_id === course?.course_id && (
                      <div className="places">
                        <div className="legend" aria-label="색 구분">
                          {(Object.keys(KIND_COLOR) as Kind[])
                            .filter((k) => course.places.some((p) => placeKind(p.category) === k))
                            .map((k) => (
                              <span key={k}><i style={{ background: KIND_COLOR[k] }} />{KIND_LABEL[k]}</span>
                            ))}
                        </div>
                        <DayTabs days={days} active={shownDay} onChange={changeDay} />
                        {byDay.filter(([day]) => day === shownDay).map(([day, idxs]) => (
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
                              const leg = course.legs.find((l) => l.from_idx === i)
                              return (
                                <Fragment key={`${p.day}-${p.order}`}>
                                <button
                                  className={`place-card${selected === i ? ' selected' : ''}`}
                                  data-place-idx={i}
                                  onClick={() => selectPlace(i)}
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
                                    {!!p.est_cost && (
                                      <span className="pc-extra">
                                        <span>1인 약 {p.est_cost.toLocaleString('ko-KR')}원</span>
                                      </span>
                                    )}
                                    {p.intro && <span className="pc-credit">출처 : ⓒ한국관광공사</span>}
                                    {/* 카드는 코스의 흐름(순서·시간·이유·비용·태그). 리뷰 요약·주소·주차장·링크는 지도 정보 창(MapView) */}
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
                                {leg && <div className="pc-leg">{legLabel(leg)}</div>}
                                </Fragment>
                              )
                            })}
                          </div>
                        ))}
                      </div>
                    )}
                    {m.course && m.course.course_id === course?.course_id && splitAnswer(m.text).tail && (
                      <div className="md answer-tail" dangerouslySetInnerHTML={{ __html: renderMarkdown(splitAnswer(m.text).tail) }} />
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
                  {slow ? '생각보다 오래 걸리고 있어요. 조금만 기다려 주세요…' : '코스를 짜고 있어요…'}
                </div>
              </div>
            )}
            {phase === 'error' && (
              <div className="msg odiro">
                <span className="avatar" aria-hidden="true" />
                <div className="bubble error" role="alert">
                  <strong>{failedAction === 'edit' && course ? '코스를 바꾸지 못했어요. 지금 코스는 그대로예요.' : '코스를 만들지 못했어요.'}</strong>
                  <div className="small">{error}</div>
                  <button
                    className="btn btn-ghost small-btn"
                    onClick={() => (retryRef.current ? retryRef.current() : generate(req))}
                  >
                    다시 시도
                  </button>
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
          <p className="credit">출처 : ⓒ한국관광공사</p>
        </aside>

        <main className="right">
          <MapView
            kakaoKey={kakaoKey}
            configFailed={mapConfigFailed}
            onRetryConfig={loadMapConfig}
            places={course?.places ?? []}
            legs={course?.legs ?? []}
            selected={selected}
            focus={focus}
            onSelect={selectPlace}
            days={days}
            activeDay={shownDay}
            onDayChange={changeDay}
            showParking={course?.request.transport === 'car'}
          />
        </main>
      </div>

      {draft && (
        <div className="drawer-backdrop" onClick={applyDraft}>
          <div className="drawer" role="dialog" aria-modal="true" aria-label="조건 바꾸기" onClick={(e) => e.stopPropagation()}>
            <div className="drawer-head">
              <strong>조건 바꾸기</strong>
              <button className="icon-btn" aria-label="닫기" onClick={applyDraft}>
                <I.Close size={18} />
              </button>
            </div>
            <p className="muted small drawer-hint">닫으면 바꾼 조건이 적용돼요. 새 코스는 위의 '다시 만들기'를 눌러 만들어요.</p>
            <Builder value={draft} onChange={setDraft} moods={moods} onSubmit={applyDraft} expanded hideSubmit />
          </div>
        </div>
      )}

      {toast && <div className="toast" role="status">{toast}</div>}
    </div>
  )
}
