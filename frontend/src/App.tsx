import { useEffect, useState, type ComponentType } from 'react'
import { getConfigCheck, getHealth, type ConfigCheck, type Health } from './api'
import HeroScene from './HeroScene'
import * as I from './Icons'
import './App.css'

type Mode = 'date' | 'trip' | 'day'
type Icon = ComponentType<{ size?: number }>

const MODES: { key: Mode; label: string; Icon: Icon }[] = [
  { key: 'date', label: '데이트 코스', Icon: I.Heart },
  { key: 'trip', label: '여행 코스', Icon: I.Suitcase },
  { key: 'day', label: '당일치기', Icon: I.Pin },
]

const TAGS = ['강릉 2박 3일', '부산 여행', '제주도', '서울 데이트', '여유로운 힐링']

const FEATURES: { Icon: Icon; tone: string; title: string; desc: string }[] = [
  { Icon: I.Robot, tone: 'coral', title: 'AI 맞춤 추천', desc: '취향과 조건을 분석해\n딱 맞는 여행 코스를 제안해요.' },
  { Icon: I.Map, tone: 'green', title: '지도 기반 코스', desc: '추천 장소를 지도에서 확인하고\n동선까지 한눈에 볼 수 있어요.' },
  { Icon: I.Car, tone: 'sun', title: '자차 여행도 OK', desc: '차로 떠나는 여행도 편하게!\n장소별 주변 주차장도 찾아드려요.' },
  { Icon: I.Calendar, tone: 'peach', title: '일정 수정도 자유롭게', desc: '대화하듯 요청하면\n코스를 바로 수정할 수 있어요.' },
]

// Phase 0: 랜딩 화면 + 백엔드 연결 확인.
// Phase 3: 코스 만들기 버튼 → 조건 빌더 → 채팅 + 지도 스플릿 뷰 연결.
export default function App() {
  const [mode, setMode] = useState<Mode>('trip')
  const [health, setHealth] = useState<Health | null>(null)
  const [config, setConfig] = useState<ConfigCheck | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    getHealth().then(setHealth).catch((e) => setError(String(e)))
    getConfigCheck().then(setConfig).catch(() => undefined)
  }, [])

  return (
    <div className="page">
      <header className="header">
        <a className="brand" href="/">
          <span className="brand-pin" aria-hidden="true" />
          <span className="brand-name">odiro<span className="brand-dot">.</span></span>
        </a>
        <nav className="nav">
          <a href="#create">코스 만들기</a>
          <a href="#features">추천 여행지</a>
          <a href="#features">이용 가이드</a>
        </nav>
        <div className="header-actions">
          <button className="icon-btn" aria-label="저장한 코스">
            <I.Bookmark size={20} />
          </button>
          <button className="btn btn-ghost">로그인</button>
          <button className="btn btn-primary">회원가입</button>
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
              <div className="mode-tabs" role="tablist">
                {MODES.map(({ key, label, Icon }) => (
                  <button
                    key={key}
                    role="tab"
                    aria-selected={mode === key}
                    className={`mode-tab${mode === key ? ' active' : ''}`}
                    onClick={() => setMode(key)}
                  >
                    <span className="mode-icon"><Icon size={19} /></span>
                    {label}
                  </button>
                ))}
              </div>

              <div className="fields">
                <button className="field">
                  <span className="field-icon"><I.Pin /></span>
                  어디로 갈까요?
                  <I.Chevron className="chevron" />
                </button>
                <button className="field">
                  <span className="field-icon"><I.Calendar /></span>
                  {mode === 'trip' ? '언제부터, 몇 박?' : '언제 갈까요?'}
                  <I.Chevron className="chevron" />
                </button>
                <button className="field">
                  <span className="field-icon"><I.Car /></span>
                  교통수단
                  <I.Chevron className="chevron" />
                </button>
              </div>

              <button className="cta">
                <I.Sparkle size={20} />
                <span>AI로 나만의 코스 만들기</span>
                <span className="cta-arrow">→</span>
              </button>

              <div className="tags">
                {TAGS.map((t) => (
                  <button key={t} className="tag"># {t}</button>
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
