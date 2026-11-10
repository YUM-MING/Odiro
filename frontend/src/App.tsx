// 랜딩 페이지. 검색 카드(조건 빌더) → /plan 으로 이동.
import { useEffect, useState, type ComponentType } from 'react'
import { useNavigate } from 'react-router-dom'
import { getConfigCheck, getHealth, getMoods, MOODS, type ConfigCheck, type CourseRequest, type Health } from './api'
import Builder from './Builder'
import HeroScene from './HeroScene'
import * as I from './Icons'
import { applyPreset, defaultRequest, loadRequest, PRESETS, saveCourse, saveRequest } from './request'
import './App.css'

type Icon = ComponentType<{ size?: number }>

const FEATURES: { Icon: Icon; tone: string; title: string; desc: string }[] = [
  { Icon: I.Robot, tone: 'coral', title: 'AI 맞춤 추천', desc: '취향과 조건을 분석해\n딱 맞는 여행 코스를 제안해요.' },
  { Icon: I.Map, tone: 'green', title: '지도 기반 코스', desc: '추천 장소를 지도에서 확인하고\n동선까지 한눈에 볼 수 있어요.' },
  { Icon: I.Car, tone: 'sun', title: '자차 여행도 OK', desc: '차로 떠나는 여행도 편하게!\n장소별 이동 시간까지 계산해요.' },
  { Icon: I.Calendar, tone: 'peach', title: '일정 수정도 자유롭게', desc: '대화하듯 요청하면\n코스를 바로 수정할 수 있어요.' },
]

export default function App() {
  const navigate = useNavigate()
  const [req, setReq] = useState<CourseRequest>(() => loadRequest() ?? defaultRequest())
  const [moods, setMoods] = useState<string[]>([...MOODS])
  const [health, setHealth] = useState<Health | null>(null)
  const [config, setConfig] = useState<ConfigCheck | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    getHealth().then(setHealth).catch((e) => setError(String(e)))
    getConfigCheck().then(setConfig).catch(() => undefined)
    getMoods().then(setMoods).catch(() => undefined)
  }, [])

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
          <a href="#features">이용 가이드</a>
        </nav>
        <div className="header-actions">
          <span className="header-note">수도권(서울·인천·경기) 우선 지원</span>
        </div>
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
              <div className="tags" aria-label="추천 조건">
                {PRESETS.map((p) => (
                  <button key={p.label} type="button" className="tag" onClick={() => go(applyPreset(defaultRequest(), p))}>
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

        <section className="features" id="features">
          {FEATURES.map(({ Icon, tone, title, desc }) => (
            <article className="feature" key={title}>
              <div className={`feature-icon tone-${tone}`}><Icon size={30} /></div>
              <div>
                <h3>{title}</h3>
                <p>{desc}</p>
              </div>
            </article>
          ))}
        </section>
      </main>

      <footer className="footer">
        <span>© 2026 Odiro</span>
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
