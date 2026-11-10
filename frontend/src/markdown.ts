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
    const ol = /^\s*\d+[.)]\s+(.*)$/.exec(line)
    const ul = /^\s*[-*•]\s+(.*)$/.exec(line)
    if (ol || ul) {
      flushPara()
      const kind = ol ? 'ol' : 'ul'
      if (list !== kind) {
        closeList()
        html.push(`<${kind}>`)
        list = kind
      }
      html.push(`<li>${inline((ol ?? ul)![1])}</li>`)
      continue
    }
    closeList()
    para.push(line)
  }
  flushPara()
  closeList()
  return html.join('\n')
}
