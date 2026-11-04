import { useEffect, useState } from 'react'
import { getConfigCheck, getHealth, type ConfigCheck, type Health } from './api'
import './App.css'

// Phase 0: 백엔드 연결 확인 화면.
// Phase 3: 인트로(지도 줌아웃 애니메이션) → 조건 빌더 → 채팅 + 지도 스플릿 뷰로 교체.
export default function App() {
  const [health, setHealth] = useState<Health | null>(null)
  const [config, setConfig] = useState<ConfigCheck | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    getHealth().then(setHealth).catch((e) => setError(String(e)))
    getConfigCheck().then(setConfig).catch(() => undefined)
  }, [])

  return (
    <main className="intro">
      <h1 className="logo">Odiro</h1>
      <p className="tagline">어디로 갈까요? 묻기만 하세요. 길까지 Odiro가 짭니다.</p>

      <section className="status">
        {error && <p className="bad">백엔드 연결 실패: {error}</p>}
        {health && (
          <p className="good">
            백엔드 연결됨 (v{health.version})
          </p>
        )}
        {config && !config.ready && (
          <p className="warn">비어 있는 API 키: {config.missing.join(', ')}</p>
        )}
        {config?.ready && <p className="good">모든 API 키 설정 완료</p>}
      </section>
    </main>
  )
}
