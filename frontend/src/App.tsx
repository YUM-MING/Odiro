// 랜딩 페이지. 검색 카드(조건 빌더) → /plan 으로 이동.
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { getConfigCheck, getHealth, getMoods, MOODS, type ConfigCheck, type CourseRequest, type Health } from './api'
import Builder from './Builder'
import DailyPick from './DailyPick'
import Guide from './Guide'
import HeroScene from './HeroScene'
import { MOCK_ENABLED } from './mock'
import { applyPreset, defaultRequest, loadRequest, PRESETS, saveCourse, saveRequest } from './request'
import './App.css'

export default function App() {
  const navigate = useNavigate()
  const [req, setReq] = useState<CourseRequest>(() => loadRequest() ?? defaultRequest())
  const [moods, setMoods] = useState<string[]>([...MOODS])
  const [health, setHealth] = useState<Health | null>(null)
  const [config, setConfig] = useState<ConfigCheck | null>(null)
  const [error, setError] = useState<string | null>(null)

  // 서버 상태 확인. 콜드스타트로 늦을 수 있어 타임아웃을 넉넉히(getHealth 기본 60초) 두고,
  // 실패하면 만들기 버튼 근처에 안내를 띄운 채 15초마다 다시 확인해 연결되면 지운다. 버튼은 막지 않는다
  useEffect(() => {
    let alive = true
    let timer: number | undefined
    const check = () => {
      getHealth()
        .then((h) => {
          if (!alive) return
          setHealth(h)
          setError(null)
        })
        .catch((e) => {
          if (!alive) return
          console.error('[odiro] 서버 상태 확인 실패:', e)
          setHealth(null)
          setError(String(e))
          timer = window.setTimeout(check, 15_000)
        })
    }
    check()
    getConfigCheck().then(setConfig).catch(() => undefined)
    getMoods().then(setMoods).catch(() => undefined)
    return () => {
      alive = false
      window.clearTimeout(timer)
    }
  }, [])

  // 숨은 여행지 배너: 지역만 바꾸고 빌더로 올라간다 (코스는 만들지 않는다)
  const applyRegion = (region: string) => {
    setReq((r) => ({ ...r, region }))
    document.getElementById('create')?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }

  const go = (r: CourseRequest) => {
    saveRequest(r)
    saveCourse(null) // 새 조건이면 이전 코스는 버린다
    navigate('/plan', { state: { request: r, fresh: true } })
  }

  return (
    <div className="page">
      <header className="header">
        <a className="brand" href="/">
          <span className="brand-pin" aria-hidden="true" />
          <span className="brand-name">odiro<span className="brand-dot">.</span></span>
        </a>
        <nav className="nav">
          <a href="#create">코스 만들기</a>
          <a href="#guide">이용 가이드</a>
        </nav>
      </header>

      <main>
        <section className="hero" id="create">
          <div className="hero-copy">
            <span className="badge">AI 여행·데이트 코스 플래너 ✦</span>
            <h1 className="headline">
              오늘, <em>어디로</em> 떠날까?
            </h1>
            <p className="sub">
              당신의 취향과 조건에 맞춰
              <br />
              AI가 맞춤 여행 코스를 만들어드려요.
            </p>

            <div className="search-card">
              <Builder value={req} onChange={setReq} moods={moods} onSubmit={() => go(req)} />
              {error && !MOCK_ENABLED && (
                <p className="server-notice" role="status">
                  지금 서버에 연결할 수 없어요. 잠시 후 다시 시도해 주세요.
                </p>
              )}
              <div className="tags" aria-label="추천 조건">
                {PRESETS.map((p) => (
                  <button key={p.label} type="button" className="tag" onClick={() => go(applyPreset(req, p))}>
                    # {p.label}
                  </button>
                ))}
              </div>
            </div>
          </div>

          <div className="hero-art" aria-hidden="true">
            <HeroScene />
          </div>
        </section>

        <DailyPick onUseRegion={applyRegion} />

        <Guide />
      </main>

      <footer className="footer">
        <span>© 2026 Odiro · 출처 : ⓒ한국관광공사</span>
        <span className="status">
          {error && <span className="dot bad" title={error} />}
          {error && '백엔드 연결 실패'}
          {health && <span className="dot good" />}
          {health && `백엔드 연결됨 v${health.version}`}
          {config && !config.ready && (
            <span className="warn" title={config.missing.join(', ')}>
              · API 키 {config.missing.length}개 미설정
            </span>
          )}
          {config?.ready && <span className="good"> · API 키 설정 완료</span>}
        </span>
      </footer>
    </div>
  )
}
