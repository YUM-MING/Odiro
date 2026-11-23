// Kakao Map JS: 번호 핀(커스텀 오버레이) + 동선 폴리라인 + 선택 장소 팝업.
import { useCallback, useEffect, useRef, useState } from 'react'
import type { LegOut, PlaceOut } from './api'
import DayTabs from './DayTabs'
import * as I from './Icons'
import { DAY_COLORS, kakaoReviewLink, kakaoToLink, kindColor } from './mapUtil'

let sdkPromise: Promise<void> | null = null
function loadSdk(key: string): Promise<void> {
  if (sdkPromise) return sdkPromise
  sdkPromise = new Promise((resolve, reject) => {
    const s = document.createElement('script')
    s.src = `https://dapi.kakao.com/v2/maps/sdk.js?appkey=${encodeURIComponent(key)}&autoload=false&libraries=services`
    s.async = true
    s.onload = () => {
      if (typeof kakao === 'undefined') return reject(new Error('kakao sdk missing'))
      kakao.maps.load(() => resolve())
    }
    s.onerror = () => reject(new Error('카카오맵 SDK 로드 실패 (도메인 등록·키 확인)'))
    document.head.appendChild(s)
  })
  return sdkPromise
}

interface Props {
  kakaoKey: string | null | undefined // undefined: 아직 모름, '': 서버가 키 없음이라고 답함(개발자 설정)
  /** 지도 설정(/api/public-config) 요청 자체가 실패함 — 서버 연결 문제. 키 미설정과 구분한다 */
  configFailed?: boolean
  onRetryConfig?: () => void
  places: PlaceOut[]
  legs: LegOut[]
  selected: number | null
  /** 사용자가 핀·카드를 눌러 고른 장소. seq 가 바뀔 때만 그 장소로 이동한다 (자동 선택은 이동하지 않음) */
  focus: { idx: number; seq: number } | null
  onSelect: (idx: number | null) => void
  days: number[]
  activeDay: number
  onDayChange: (day: number) => void
  showParking: boolean // 자차 코스일 때만 정보 창에 주차장을 보인다
}

export default function MapView({
  kakaoKey, configFailed, onRetryConfig, places, legs, selected, focus, onSelect, days, activeDay, onDayChange, showParking,
}: Props) {
  const box = useRef<HTMLDivElement>(null)
  const map = useRef<kakao.maps.Map | null>(null)
  const overlays = useRef<kakao.maps.CustomOverlay[]>([])
  const lines = useRef<kakao.maps.Polyline[]>([])
  const [ready, setReady] = useState(false)
  const [sdkError, setSdkError] = useState<string | null>(null)
  const alive = useRef(true)

  // SDK 로드 + 지도 생성
  useEffect(() => {
    if (!kakaoKey || !box.current || map.current) return
    alive.current = true
    loadSdk(kakaoKey)
      .then(() => {
        if (!alive.current || !box.current) return
        map.current = new kakao.maps.Map(box.current, { center: new kakao.maps.LatLng(37.5665, 126.978), level: 7 })
        setReady(true)
      })
      .catch((e: Error) => setSdkError(e.message))
    return () => {
      alive.current = false
    }
  }, [kakaoKey])

  // 창 크기 바뀌면 relayout
  useEffect(() => {
    const onResize = () => map.current?.relayout()
    window.addEventListener('resize', onResize)
    return () => window.removeEventListener('resize', onResize)
  }, [])

  // 핀·동선 그리기
  useEffect(() => {
    const m = map.current
    if (!ready || !m) return
    overlays.current.forEach((o) => o.setMap(null))
    lines.current.forEach((l) => l.setMap(null))
    overlays.current = []
    lines.current = []
    if (!places.length) return

    // 하루치만 그린다 (여러 날이 한꺼번에 보이면 복잡하다). 단일 날 코스는 전부 day 1 이라 그대로 다 보인다
    places.forEach((p, idx) => {
      if (!p.verified || p.day !== activeDay) return
      const pos = new kakao.maps.LatLng(p.lat, p.lng)
      const el = document.createElement('button')
      el.type = 'button'
      el.className = `pin${selected === idx ? ' selected' : ''}`
      el.style.setProperty('--pin', kindColor(p)) // 핀은 종류별 색(밥집·카페·놀거리·숙소), 동선은 Day 별 색
      el.setAttribute('aria-label', `${p.order}번 ${p.name}`)
      el.textContent = String(p.order)
      el.addEventListener('click', () => onSelect(idx))
      const ov = new kakao.maps.CustomOverlay({ position: pos, content: el, yAnchor: 1.15, zIndex: selected === idx ? 10 : 1 })
      ov.setMap(m)
      overlays.current.push(ov)
    })
    legs.forEach((leg) => {
      const a = places[leg.from_idx]
      const b = places[leg.to_idx]
      if (!a || !b || a.day !== activeDay || b.day !== activeDay) return
      const path = (leg.polyline.length >= 2 ? leg.polyline : [[a.lat, a.lng], [b.lat, b.lng]]).map(
        ([lat, lng]) => new kakao.maps.LatLng(lat, lng),
      )
      const line = new kakao.maps.Polyline({
        path,
        strokeWeight: 5,
        strokeColor: DAY_COLORS[(a.day - 1) % DAY_COLORS.length],
        strokeOpacity: leg.estimated ? 0.55 : 0.85,
        strokeStyle: leg.estimated ? 'shortdash' : 'solid',
      })
      line.setMap(m)
      lines.current.push(line)
    })
  }, [ready, places, legs, selected, onSelect, activeDay])

  // 그날의 핀 전체가 보이게 맞춘다. 핀을 고를 때마다 다시 맞추지 않도록 그리기와 분리했다
  const fitDay = useCallback(() => {
    const m = map.current
    if (!ready || !m) return
    const pts = places.filter((p) => p.verified && p.day === activeDay)
    if (!pts.length) return
    m.relayout() // 지도 영역 크기가 바뀐 뒤일 수 있으므로 크기를 다시 잰 다음 맞춘다
    if (pts.length === 1) {
      m.setCenter(new kakao.maps.LatLng(pts[0].lat, pts[0].lng))
      m.setLevel(4)
      return
    }
    const bounds = new kakao.maps.LatLngBounds()
    pts.forEach((p) => bounds.extend(new kakao.maps.LatLng(p.lat, p.lng)))
    m.setBounds(bounds, 60, 60, 120, 60)
  }, [ready, places, activeDay])

  // 새 코스·Day 탭이 바뀌면 전체 보기 (첫 장소 정보 창이 자동으로 열려도 확대·이동하지 않는다)
  useEffect(() => fitDay(), [fitDay])

  // 사용자가 핀·카드를 눌렀을 때만 그 장소로 이동
  useEffect(() => {
    const m = map.current
    if (!ready || !m || !focus) return
    const p = places[focus.idx]
    if (p && p.day === activeDay) m.panTo(new kakao.maps.LatLng(p.lat, p.lng))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready, focus])

  const hasPins = places.some((p) => p.verified && p.day === activeDay)

  const sel = selected !== null && places[selected]?.day === activeDay ? places[selected] : null
  // 정보 창 대표 이미지 (TourAPI). https 만, 불러오지 못한 주소는 영역째 숨긴다
  const [brokenImg, setBrokenImg] = useState<string | null>(null)
  const selImg = sel?.image && sel.image.startsWith('https://') && sel.image !== brokenImg ? sel.image : ''

  return (
    <div className="map-wrap">
      <div ref={box} className="map" role="region" aria-label="코스 지도" />
      {kakaoKey === '' && (
        <div className="map-placeholder">
          <I.Map size={36} />
          <strong>지도 키 미설정</strong>
          <span>백엔드 .env 의 KAKAO_JS_API_KEY 를 채우고, 카카오 콘솔에 이 도메인을 등록하세요.</span>
        </div>
      )}
      {kakaoKey === undefined && !sdkError && configFailed && (
        <div className="map-placeholder" role="status">
          <I.Map size={36} />
          <strong>지도를 불러오지 못했어요</strong>
          <span>서버에 연결되면 자동으로 다시 불러와요.</span>
          {onRetryConfig && (
            <button type="button" className="btn btn-ghost small-btn" onClick={onRetryConfig}>
              다시 시도
            </button>
          )}
        </div>
      )}
      {kakaoKey === undefined && !sdkError && !configFailed && <div className="map-placeholder">지도 불러오는 중…</div>}
      {sdkError && (
        <div className="map-placeholder">
          <strong>지도를 불러오지 못했어요</strong>
          <span>{sdkError}</span>
        </div>
      )}
      <DayTabs days={days} active={activeDay} onChange={onDayChange} className="map-day-tabs" />
      {ready && hasPins && (
        <button type="button" className="map-fit" onClick={fitDay} aria-label="이 날 코스 전체 보기" title="이 날 코스 전체 보기">
          전체 보기
        </button>
      )}
      {sel && (
        <div className="popup" role="dialog" aria-label={`${sel.name} 정보`}>
          <button className="popup-close" aria-label="닫기" onClick={() => onSelect(null)}>
            <I.Close size={16} />
          </button>
          <div className="popup-head">
            <span className="popup-order" style={{ background: kindColor(sel) }}>
              {sel.order}
            </span>
            <div>
              <strong>{sel.name}</strong>
              <span className="muted"> · {sel.category}</span>
              {/* 도착·체류 시간, 추천 이유, 비용, 태그는 채팅의 장소 카드에서 본다. 여기는 장소 자체의 세부 정보 */}
            </div>
          </div>
          {selImg && (
            <img className="popup-img" src={selImg} alt="" loading="lazy" referrerPolicy="no-referrer" onError={() => setBrokenImg(selImg)} />
          )}
          {sel.address && <div className="small">{sel.address}</div>}
          {sel.intro && (
            <dl className="popup-intro">
              {sel.intro.rest_date && (<><dt>쉬는 날</dt><dd>{sel.intro.rest_date}</dd></>)}
              {sel.intro.use_time && (<><dt>이용시간</dt><dd>{sel.intro.use_time}</dd></>)}
              {sel.intro.use_fee && (<><dt>이용요금</dt><dd>{sel.intro.use_fee}</dd></>)}
              {(sel.intro.parking || sel.intro.parking_fee) && (
                <><dt>전용 주차</dt><dd>{[sel.intro.parking, sel.intro.parking_fee && `요금 ${sel.intro.parking_fee}`].filter(Boolean).join(' · ')}</dd></>
              )}
            </dl>
          )}
          {(sel.intro || selImg) && <div className="popup-credit">출처 : ⓒ한국관광공사</div>}
          {showParking && (
            <div className="popup-parking">
              <span aria-hidden="true">🅿</span> {sel.parking ? `근처 주차장 ${sel.parking}` : '근처 주차장 정보가 없어요'}
            </div>
          )}
          {sel.review_summary && <p className="popup-review">“{sel.review_summary}”</p>}
          <div className="popup-links">
            <a href={kakaoReviewLink(sel)} target="_blank" rel="noopener noreferrer">리뷰 보기</a>
            <a href={kakaoToLink(sel)} target="_blank" rel="noopener noreferrer">길찾기</a>
            {sel.phone && <a href={`tel:${sel.phone}`}>{sel.phone}</a>}
          </div>
        </div>
      )}
    </div>
  )
}
