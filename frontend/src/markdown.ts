// 아주 작은 마크다운 → HTML 변환기. answer_md 가 쓰는 문법만 지원한다:
// 제목(#, ##, ###), **굵게**, [링크](https://…), 번호/글머리 목록, > 인용, 빈 줄 단락.
// HTML 은 먼저 전부 이스케이프하므로 스크립트 삽입이 불가능하다.

function escapeHtml(s: string): string {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;')
}

function inline(s: string): string {
  let out = escapeHtml(s)
  out = out.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
  out = out.replace(/`([^`]+)`/g, '<code>$1</code>')
  out = out.replace(/\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>')
  return out
}

/**
 * 답변 글에서 장소 카드가 이미 보여주는 줄(번호 목록·이동 안내 ↳·Day 소제목)을 빼고,
 * 카드 앞(head: 소개 등)과 뒤(tail: 팁·참고)로 나눈다.
 * 이동 정보는 카드 사이에 구조화된 데이터(legs)로 따로 그린다.
 */
export function splitAnswer(md: string): { head: string; tail: string } {
  const head: string[] = []
  const tail: string[] = []
  let afterPlaces = false
  for (const raw of md.replace(/\r\n/g, '\n').split('\n')) {
    const line = raw.trimEnd()
    if (/^\s*\d+[.)]\s+/.test(line) || /^#{1,3}\s*day\s*\d/i.test(line.trim())) {
      afterPlaces = true
      continue
    }
    if (/^\s*↳/.test(line)) continue
    // 장소 줄이 줄바꿈으로 나뉘어 온 꼬리(예상 비용·주차장·리뷰·추천 이유)는 카드가 이미 보여 주므로 버린다
    if (afterPlaces && isPlaceTail(line)) continue
    ;(afterPlaces ? tail : head).push(line)
  }
  return { head: head.join('\n').trim(), tail: tail.join('\n').trim() }
}

/**
 * 이전 답변(카드 없이 글 목록으로 보이는 답변)용: 줄바꿈으로 떨어져 나온 장소 꼬리(isPlaceTail)를 바로 앞 번호 항목 끝에 붙인다.
 * 비용·주차장·리뷰 같은 정보는 그대로 남기고(숨기지 않는다) 항목 밖에 따로 뜨지 않게만 한다.
 * 앞에 번호 항목이 없거나, 그 사이에 다른 문장이 있으면 붙이지 않는다. 빈 줄·이동 안내(↳)는 건너뛰고 찾는다.
 */
export function mergePlaceTails(md: string): string {
  const out: string[] = []
  let item = -1 // 붙일 대상인 마지막 번호 항목의 out 위치
  for (const raw of md.replace(/\r\n/g, '\n').split('\n')) {
    const line = raw.trimEnd()
    if (/^\s*\d+[.)]\s+/.test(line)) {
      item = out.length
      out.push(line)
      continue
    }
    if (item >= 0 && isPlaceTail(line)) {
      out[item] = `${out[item]} ${line.trim()}`
      continue
    }
    if (line.trim() && !/^\s*↳/.test(line)) item = -1
    out.push(line)
  }
  return out.join('\n')
}

/**
 * 장소 항목의 꼬리로만 쓰이는 조각인지. answer_md 의 장소 형식
 * `**장소명** (도착 HH:MM · 체류 N분 · 약 N원) — 이유 🅿 주차장 (약 Nm) 💬 리뷰` 이 줄바꿈으로 끊겨
 * 다음 줄이 `(약 20,000원) · 🅿 …`, `· 약 N원`, `🅿 …`, `💬 …`, `— 이유` 로 시작할 때만 해당한다.
 * 팁·안내·경고 문장(예: '**팁** …', '비 예보가 있어요')은 이런 기호로 시작하지 않으므로 그대로 남는다.
 */
export function isPlaceTail(line: string): boolean {
  return /^\s*(?:\(\s*(?:도착\s*\d|약\s*[\d,]+\s*원|체류\s*\d)|[·•]\s*(?:약\s*[\d,]+\s*원|🅿|체류\s*\d)|🅿|💬|[—–]\s)/u.test(line)
}

export function renderMarkdown(md: string): string {
  const lines = md.replace(/\r\n/g, '\n').split('\n')
  const html: string[] = []
  let list: 'ul' | 'ol' | null = null
  let para: string[] = []

  const flushPara = () => {
    if (para.length) {
      html.push(`<p>${para.map(inline).join('<br/>')}</p>`)
      para = []
    }
  }
  const closeList = () => {
    if (list) {
      html.push(`</${list}>`)
      list = null
    }
  }

  for (const raw of lines) {
    const line = raw.trimEnd()
    if (!line.trim()) {
      flushPara()
      closeList()
      continue
    }
    const h = /^(#{1,3})\s+(.*)$/.exec(line)
    if (h) {
      flushPara()
      closeList()
      html.push(`<h${h[1].length + 2}>${inline(h[2])}</h${h[1].length + 2}>`)
      continue
    }
    const q = /^>\s?(.*)$/.exec(line)
    if (q) {
      flushPara()
      closeList()
      html.push(`<blockquote>${inline(q[1])}</blockquote>`)
      continue
    }
    const ol = /^\s*(\d+)[.)]\s+(.*)$/.exec(line)
    const ul = /^\s*[-*•]\s+(.*)$/.exec(line)
    if (ol || ul) {
      flushPara()
      const kind = ol ? 'ol' : 'ul'
      if (list !== kind) {
        closeList()
        html.push(`<${kind}>`)
        list = kind
      }
      // 번호 목록은 항목 사이에 이동 안내(↳) 줄이 끼면 목록이 끊겨 전부 1 로 보인다 → 원문 번호를 그대로 쓴다
      html.push(ol ? `<li value="${Number(ol[1])}">${inline(ol[2])}</li>` : `<li>${inline(ul![1])}</li>`)
      continue
    }
    closeList()
    para.push(line)
  }
  flushPara()
  closeList()
  return html.join('\n')
}
