// 이용 가이드 (#guide) · 일러스트 카드형 (CSS 접두 .guide-). 일러스트는 인라인 SVG, 색은 CSS 클래스(.gd-*)로.
// 문구는 실제 기능 기준 (근거는 항목 옆 주석). 화면 버튼을 가리킬 때는 실제 표시 이름을 따옴표로 쓴다
import * as I from './Icons'

const STEPS = [
  {
    // Builder.tsx: 데이트 코스·여행 코스·당일치기, 지역, 날짜, 뚜벅이/자차, 상세 조건(1인 예산·분위기)
    title: '여행 조건 설정하기',
    desc: '여행 유형, 지역, 날짜, 이동수단을 선택하고 상세 조건에서 예산과 취향을 설정해 보세요.',
    Art: ArtForm,
  },
  {
    // graph.py 생성 흐름: 조건 이해 → 검색 → 초안(예산·분위기 반영) → 실존 확인 → 동선 최적화
    title: 'AI 맞춤 코스 만들기',
    desc: 'AI가 여행 조건과 취향, 이동 동선을 고려해 나만의 맞춤 여행 코스를 추천해요.',
    Art: ArtList,
  },
  {
    // Plan.tsx: 지도·장소 카드, '바꾸기'·대화 수정, '공유'
    title: '나만의 여행 완성하기',
    desc: '지도에서 코스를 확인하고, 원하는 대로 수정한 뒤 완성된 여행 코스를 공유해 보세요.',
    Art: ArtMap,
  },
]

const TIPS = [
  // App.tsx 검색 카드 아래 추천 조건 태그(# 성수동 데이트 등): 누르면 그 조건으로 바로 코스를 만든다
  { Icon: I.Click, title: '어디로 갈지 고민된다면?', desc: '추천 코스 태그를 선택해 간편하게 여행 계획을 시작해 보세요.' },
  // Builder.tsx '상세 조건 펼치기' → 분위기 선택·자유 조건 입력 (꼭 넣을 장소·분위기 반영: nodes.py parse_intent)
  { Icon: I.Chat, title: '원하는 여행을 자유롭게', desc: "'상세 조건 펼치기'를 눌러 꼭 가고 싶은 장소나 원하는 분위기를 직접 입력해 보세요." },
  // Builder.tsx 1인 예산 → nodes.py 초안 조건·예산 초과 안내
  { Icon: I.Wallet, title: '내 예산에 맞는 여행', desc: '여행 예산을 설정하면 예산을 고려한 맞춤 코스를 추천해요.' },
  // get_weather.py 예보 범위(5일), nodes.py 비 예보 시 실내 위주
  { Icon: I.CloudSun, title: '날씨까지 고려한 여행', desc: '예보가 제공되는 날짜에는 날씨를 고려해 코스를 추천해요.' },
  // Plan.tsx 장소 카드 '바꾸기'
  { Icon: I.Swap, title: '마음에 들지 않는 장소는 교체', desc: "장소 카드의 '바꾸기'를 누르면 코스 전체를 다시 만들지 않고 그 장소만 바꿀 수 있어요." },
  // MapView.tsx 핀 정보 창 '리뷰 보기'(카카오맵 장소 페이지)·'길찾기'(카카오맵 길찾기, 출발지는 현재 위치)
  { Icon: I.Map, title: '카카오맵으로 자세히 확인', desc: "지도 핀의 '리뷰 보기'로 장소 정보를, '길찾기'로 이동 방법과 소요 시간을 카카오맵에서 확인할 수 있어요." },
  // Plan.tsx '공유' → '복사하기': 체크한 조건 + 장소·경로 링크를 글로 복사
  { Icon: I.Share, title: '완성된 여행 코스 공유하기', desc: "'공유'를 누르면 장소·경로 링크가 담긴 코스를 복사해 함께 나눌 수 있어요." },
  // DailyPick.tsx 오늘의 숨은 여행지
  { Icon: I.Compass, title: '새로운 여행지 발견하기', desc: '매일 소개되는 숨은 여행지에서 새로운 여행의 영감을 얻어 보세요.' },
]

/** 4각 반짝이 (cx, cy 중심, r 반지름) */
function sparkle(cx: number, cy: number, r: number): string {
  const k = r * 0.18
  return `M${cx} ${cy - r} Q${cx + k} ${cy - k} ${cx + r} ${cy} Q${cx + k} ${cy + k} ${cx} ${cy + r} Q${cx - k} ${cy + k} ${cx - r} ${cy} Q${cx - k} ${cy - k} ${cx} ${cy - r}Z`
}

function ArtForm() {
  return (
    <svg viewBox="0 0 240 150" aria-hidden="true">
      <circle className="gd-bg-sun" cx="62" cy="44" r="34" />
      <circle className="gd-bg-mint" cx="190" cy="104" r="30" />
      <rect className="gd-card" x="60" y="14" width="120" height="118" rx="12" />
      <rect className="gd-coral" x="72" y="26" width="28" height="10" rx="5" />
      <rect className="gd-gray" x="104" y="26" width="28" height="10" rx="5" />
      <rect className="gd-gray" x="136" y="26" width="28" height="10" rx="5" />
      <rect className="gd-field" x="72" y="44" width="96" height="16" rx="6" />
      <path className="gd-coral" d="M81 57s-4.5-3.8-4.5-7.2a4.5 4.5 0 0 1 9 0c0 3.4-4.5 7.2-4.5 7.2z" />
      <circle className="gd-white" cx="81" cy="49.8" r="1.6" />
      <rect className="gd-line" x="90" y="50" width="52" height="4" rx="2" />
      <rect className="gd-field" x="72" y="66" width="46" height="16" rx="6" />
      <rect className="gd-field" x="122" y="66" width="46" height="16" rx="6" />
      <rect className="gd-coral" x="72" y="92" width="96" height="14" rx="7" />
      <circle className="gd-sun" cx="178" cy="120" r="16" />
      <path className="gd-stroke-white" d="M170.5 120.5l5 5 9-10" />
    </svg>
  )
}

function ArtList() {
  const rows = [
    { y: 38, cls: 'gd-peach' },
    { y: 66, cls: 'gd-mint' },
    { y: 94, cls: 'gd-sky' },
  ]
  return (
    <svg viewBox="0 0 240 150" aria-hidden="true">
      <circle className="gd-bg-mint" cx="58" cy="108" r="32" />
      <circle className="gd-bg-sun" cx="196" cy="40" r="30" />
      <rect className="gd-card" x="52" y="22" width="136" height="106" rx="12" />
      {rows.map(({ y, cls }) => (
        <g key={y}>
          <rect className={cls} x="66" y={y} width="18" height="18" rx="5" />
          <rect className="gd-line" x="92" y={y + 3} width="74" height="5" rx="2.5" />
          <rect className="gd-line-soft" x="92" y={y + 12} width="48" height="4" rx="2" />
        </g>
      ))}
      <circle className="gd-coral" cx="186" cy="28" r="17" />
      <path className="gd-white" d={sparkle(186, 28, 9)} />
      <path className="gd-sun" d={sparkle(38, 62, 8)} />
      <path className="gd-sun" d={sparkle(30, 84, 4)} />
    </svg>
  )
}

function ArtMap() {
  const pins = [
    { x: 74, y: 96, n: 1 },
    { x: 120, y: 62, n: 2 },
    { x: 168, y: 92, n: 3 },
  ]
  return (
    <svg viewBox="0 0 240 150" aria-hidden="true">
      <circle className="gd-bg-sun" cx="56" cy="36" r="28" />
      <circle className="gd-bg-mint" cx="200" cy="118" r="26" />
      {/* 접힌 지도 세 면 */}
      <path className="gd-map-a" d="M40 30 L93 40 L93 128 L40 118Z" />
      <path className="gd-map-b" d="M93 40 L147 30 L147 118 L93 128Z" />
      <path className="gd-map-a" d="M147 30 L200 40 L200 128 L147 118Z" />
      <path className="gd-wave-sky" d="M44 66 C70 56 90 80 120 70 S170 58 197 72" />
      <path className="gd-wave-mint" d="M44 104 C78 96 100 114 140 104 S180 96 197 108" />
      <path className="gd-route" d="M74 96 C90 78 104 66 120 62 S152 74 168 92" />
      {pins.map(({ x, y, n }) => (
        <g key={n} transform={`translate(${x} ${y})`}>
          <path className="gd-pin" d="M0 0C-8-9-9-13-9-16a9 9 0 1 1 18 0c0 3-1 7-9 16z" />
          <text className="gd-pin-num" x="0" y="-12.5" textAnchor="middle">{n}</text>
        </g>
      ))}
      <circle className="gd-sun" cx="190" cy="122" r="16" />
      <path className="gd-stroke-white" d="M196 117a7.5 7.5 0 1 0 1.5 6.5M196 111.5v6h-6" />
    </svg>
  )
}

export default function Guide() {
  // 빌더로 부드럽게 올라가 지역 칸에 포커스 (코스를 자동으로 만들지 않는다)
  const toBuilder = () => {
    document.getElementById('create')?.scrollIntoView({ behavior: 'smooth', block: 'start' })
    document.querySelector<HTMLInputElement>('#create input[aria-label="지역"]')?.focus({ preventScroll: true })
  }

  return (
    <section className="guide" id="guide" aria-labelledby="guide-title">
      <div className="guide-head">
        <span className="guide-label">HOW TO USE ODIRO ✦</span>
        <h2 id="guide-title">
          여행 준비, 이제 <em>어렵지 않아요.</em>
        </h2>
        <p className="guide-desc">간단한 세 단계로 나만의 여행을 완성해 보세요.</p>
      </div>

      <ol className="guide-steps">
        {STEPS.map(({ title, desc, Art }, i) => (
          <li className="guide-card" key={title}>
            <div className="guide-art">
              <Art />
            </div>
            <div className="guide-body">
              <span className="guide-step">STEP {String(i + 1).padStart(2, '0')}</span>
              <h3>{title}</h3>
              <p>{desc}</p>
            </div>
          </li>
        ))}
      </ol>

      <div className="guide-tips">
        <h3 className="guide-tips-title">
          <I.Bulb size={22} /> Odiro를 더 잘 활용하는 TIP!
        </h3>
        <ul>
          {TIPS.map(({ Icon, title, desc }) => (
            <li key={title}>
              <span className="guide-tip-icon" aria-hidden="true"><Icon size={20} /></span>
              <span>
                <strong>{title}</strong>
                <small>{desc}</small>
              </span>
            </li>
          ))}
        </ul>
      </div>

      <div className="guide-cta">
        <p>
          자, 이제 <em>어디로</em> 떠나볼까요?
        </p>
        <button type="button" className="guide-cta-btn" onClick={toBuilder}>
          ✦ 나만의 코스 만들기 <span aria-hidden="true">→</span>
        </button>
      </div>
    </section>
  )
}
