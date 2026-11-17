// Kakao Map JS: 번호 핀(커스텀 오버레이) + 동선 폴리라인 + 선택 장소 팝업.
import { useEffect, useRef, useState } from 'react'
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
  kakaoKey: string | null | undefined // undefined: 아직 모름, '': 미설정
  places: PlaceOut[]
  legs: LegOut[]
  selected: number | null
  onSelect: (idx: number | null) => void
  days: number[]
  activeDay: number
  onDayChange: (day: number) => void
  showParking: boolean // 자차 코스일 때만 정보 창에 주차장을 보인다
}

export default function MapView({ kakaoKey, places, legs, selected, onSelect, days, activeDay, onDayChange, showParking }: Props) {
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
    const bounds = new kakao.maps.LatLngBounds()
    places.forEach((p, idx) => {
      if (!p.verified || p.day !== activeDay) return
      const pos = new kakao.maps.LatLng(p.lat, p.lng)
      bounds.extend(pos)
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
    m.setBounds(bounds, 60, 60, 120, 60)
  }, [ready, places, legs, selected, onSelect, activeDay])

  // 선택 장소로 이동
  useEffect(() => {
    const m = map.current
    if (!ready || !m || selected === null) return
    const p = places[selected]
    if (p) m.panTo(new kakao.maps.LatLng(p.lat, p.lng))
  }, [ready, selected, places])

  const sel = selected !== null && places[selected]?.day === activeDay ? places[selected] : null

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
      {kakaoKey === undefined && !sdkError && <div className="map-placeholder">지도 불러오는 중…</div>}
      {sdkError && (
        <div className="map-placeholder">
          <strong>지도를 불러오지 못했어요</strong>
          <span>{sdkError}</span>
        </div>
      )}
      <DayTabs days={days} active={activeDay} onChange={onDayChange} className="map-day-tabs" />
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
          {sel.intro && <div className="popup-credit">출처 : ⓒ한국관광공사</div>}
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
