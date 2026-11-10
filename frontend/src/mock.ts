// 백엔드 없이 UI 를 끝까지 확인하기 위한 목 데이터. VITE_MOCK=1 이거나 백엔드에 연결이 안 될 때 사용.
import type { CourseRequest, CourseResponse, TraceStep } from './api'

export const MOCK_ENABLED = import.meta.env.VITE_MOCK === '1'

export const GENERATE_NODES = [
  'parse_intent',
  'retrieve',
  'draft_course',
  'verify_places',
  'optimize_route',
  'enrich',
  'compose_answer',
] as const
export const EDIT_NODES = ['modify', 'verify_places', 'optimize_route', 'enrich', 'compose_answer'] as const

export const NODE_LABEL: Record<string, string> = {
  parse_intent: '조건 이해하기',
  retrieve: '큐레이션·웹 검색',
  draft_course: '코스 초안 작성',
  verify_places: '장소 실존 확인',
  optimize_route: '동선 최적화',
  enrich: '날씨·일몰·리뷰 요약',
  compose_answer: '답변 정리',
  modify: '수정 요청 반영',
}

export function mockCourse(req: CourseRequest): CourseResponse {
  const places = [
    {
      order: 1, day: 1, name: '서울숲', category: '관광지',
      lat: 37.5444, lng: 127.0374, address: '서울 성동구 뚝섬로 273',
      kakao_place_id: '8128830', place_url: 'http://place.map.kakao.com/8128830', phone: '02-460-2905',
      reason: '오후 햇살 아래 은행나무길 산책으로 가볍게 시작해요.',
      tags: ['자연/산책', '사진맛집'], review_summary: '평일 오후엔 한산하고 가을 단풍이 예쁘다는 평이 많아요.',
      arrive: req.start_time, stay_min: 70, image: '', verified: true, source: 'rag',
    },
    {
      order: 2, day: 1, name: '로우키 성수', category: '카페',
      lat: 37.5448, lng: 127.0552, address: '서울 성동구 연무장길 45',
      kakao_place_id: '1234567', place_url: 'http://place.map.kakao.com/1234567', phone: '',
      reason: '통창으로 빛이 들어오는 조용한 로스터리. 작업하거나 대화하기 좋아요.',
      tags: ['감성/조용한'], review_summary: '웨이팅이 거의 없고 커피 맛이 안정적이라는 후기.',
      arrive: '13:00', stay_min: 60, image: '', verified: true, source: 'rag',
    },
    {
      order: 3, day: 1, name: '성수 연무장길', category: '놀거리',
      lat: 37.5425, lng: 127.0565, address: '서울 성동구 연무장길',
      kakao_place_id: '7654321', place_url: 'http://place.map.kakao.com/7654321', phone: '',
      reason: '팝업과 편집숍이 모여 있어 해 질 녘 산책하며 구경하기 좋아요.',
      tags: ['힙한/트렌디', '사진맛집'], review_summary: '주말엔 붐비니 평일 저녁이 여유롭다는 평.',
      arrive: '14:30', stay_min: 90, image: '', verified: true, source: 'web',
    },
  ]
  return {
    course_id: `mock_${Date.now()}`,
    request: req,
    title: `${req.region || '성수동'} 골목 감성 ${req.mode === 'trip' ? '여행' : '데이트'}`,
    places,
    legs: [
      { from_idx: 0, to_idx: 1, transport: 'walk', duration_min: 18, distance_m: 1500, polyline: [[37.5444, 127.0374], [37.5452, 127.047], [37.5448, 127.0552]], estimated: false },
      { from_idx: 1, to_idx: 2, transport: 'walk', duration_min: 5, distance_m: 320, polyline: [[37.5448, 127.0552], [37.5425, 127.0565]], estimated: true },
    ],
    answer_md: [
      `**Odiro:** ${req.region || '성수동'}에서 ${req.moods.length ? req.moods.join(', ') + ' 분위기로' : '조용히'} 걷는 하루를 짜봤어요. (목 데이터)`,
      '',
      `1. **서울숲** (${req.start_time}, 70분) — 은행나무길 산책으로 시작. 평일 오후라 한산해요.`,
      '2. **로우키 성수** (13:00, 60분) — 도보 18분. 통창 로스터리에서 커피 한 잔.',
      '3. **성수 연무장길** (14:30, 90분) — 도보 5분. 팝업·편집숍 구경하며 해 질 녘까지.',
      '',
      '> 꿀팁: 일몰 17:22 즈음 서울숲 호수 쪽으로 돌아오면 사진이 잘 나와요.',
    ].join('\n'),
    meta: {
      sun: { sunrise: '07:10', sunset: '17:22' },
      weather: { available: true, summary: '맑음', temp_c: 9.5, pop: 0.1, rain: false, note: '' },
      rag_docs: 8, web_docs: 3,
      warnings: ['2→3 구간은 길찾기 실패로 직선거리 추정'],
      trace: [], cached: false, elapsed_ms: 4200,
    },
  }
}

export function mockEdit(course: CourseResponse, instruction: string, targetOrder: number | null): CourseResponse {
  const idx = targetOrder ? course.places.findIndex((p) => p.order === targetOrder) : 1
  const places = course.places.map((p, i) =>
    i === idx
      ? { ...p, name: '어니언 성수', category: '카페', lat: 37.5445, lng: 127.0586, address: '서울 성동구 아차산로9길 8',
          reason: `요청(${instruction})을 반영해 바꿨어요. 레트로 공장 리모델링 카페.`, tags: ['레트로', '사진맛집'],
          review_summary: '빵이 맛있고 공간이 넓어 사진 찍기 좋다는 평.', source: 'rag' }
      : p,
  )
  return {
    ...course,
    course_id: `mock_${Date.now()}`,
    places,
    answer_md: `**Odiro:** ${idx + 1}번 장소를 **${places[idx]?.name}** 로 바꿨어요. 동선은 그대로 도보로 이어져요. (목 데이터)\n\n` +
      places.map((p) => `${p.order}. **${p.name}** (${p.arrive}, ${p.stay_min}분) — ${p.reason}`).join('\n'),
    meta: { ...course.meta, warnings: [], elapsed_ms: 2100 },
  }
}

/** 진행 이벤트를 흉내 낸다. 반환 함수로 취소. */
export function simulateProgress(
  nodes: readonly string[],
  onStep: (s: TraceStep) => void,
  onDone: () => void,
): () => void {
  const timers: number[] = []
  let t = 0
  nodes.forEach((node, i) => {
    const dur = 500 + (i % 3) * 300
    timers.push(window.setTimeout(() => onStep({ node, status: 'start', ms: 0, detail: '' }), t))
    t += dur
    timers.push(window.setTimeout(() => onStep({ node, status: 'done', ms: dur, detail: i === 0 ? '성수동 → 서울 성동구' : '' }), t))
  })
  timers.push(window.setTimeout(onDone, t + 200))
  return () => timers.forEach((id) => window.clearTimeout(id))
}
