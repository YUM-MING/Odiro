// 랜딩의 "오늘의 숨은 여행지" 배너. 관광 수요가 덜 몰리는 지역의 TourAPI 관광지를 날짜마다 한 곳 (GET /api/daily-pick).
// 실패·후보 없음(404)이면 아무것도 그리지 않는다. 코스를 자동으로 만들지 않고 빌더의 지역만 바꾼다
// (지방은 블로그 데이터가 없어 사용자가 조건을 직접 고르게 한다).
import { useEffect, useState } from 'react'
import { getDailyPick, type DailyPick as Pick } from './api'
import * as I from './Icons'
import { MOCK_ENABLED, mockDailyPick } from './mock'
import { kstYmd } from './request'

export default function DailyPick({ onUseRegion }: { onUseRegion: (region: string) => void }) {
  const [pick, setPick] = useState<Pick | null>(() => (MOCK_ENABLED ? mockDailyPick(kstYmd()) : null))
  const [imgFailed, setImgFailed] = useState(false)

  useEffect(() => {
    if (MOCK_ENABLED) return
    let alive = true
    getDailyPick(kstYmd())
      .then((p) => alive && setPick(p))
      .catch(() => alive && setPick(null)) // 404·네트워크 오류: 배너 없음
    return () => {
      alive = false
    }
  }, [])

  if (!pick) return null
  const showImg = pick.image && !imgFailed

  return (
    <section className="daily-wrap" aria-labelledby="daily-title">
      <div className="daily">
        <div className="daily-photo">
          {showImg ? (
            <img src={pick.image} alt={pick.name} loading="lazy" onError={() => setImgFailed(true)} />
          ) : (
            <div className="daily-photo-fallback" aria-hidden="true">
              <I.Map size={40} />
            </div>
          )}
        </div>
        <div className="daily-body">
          <span className="daily-label">
            <I.Sparkle size={12} /> 오늘의 숨은 여행지
          </span>
          <h2 id="daily-title" className="daily-name">{pick.name}</h2>
          <p className="daily-region">
            <span className="daily-region-icon" aria-hidden="true">
              <I.Pin size={14} />
            </span>
            {pick.region}
          </p>
          {pick.description && (
            <p className="daily-desc" title={pick.description}>
              {pick.description}
            </p>
          )}
          <p className="daily-meta">
            덜 알려진 지역을 매일 한 곳씩 소개해요
            <span className="daily-meta-sep" aria-hidden="true">·</span>
            사진·정보: ⓒ{pick.source || '한국관광공사'}
          </p>
        </div>
        <div className="daily-actions">
          <a className="btn daily-btn daily-btn-line" href={pick.kakao_map_url} target="_blank" rel="noopener noreferrer">
            <I.Map size={14} /> 카카오맵에서 보기
          </a>
          <button type="button" className="btn btn-primary daily-btn" onClick={() => onUseRegion(pick.region)}>
            <I.Sparkle size={14} /> 이 지역으로 코스 만들기
          </button>
        </div>
      </div>
    </section>
  )
}
