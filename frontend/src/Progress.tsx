// 사이드바 노드 진행 표시. SSE progress 이벤트로 갱신된다.
// 코스가 완성되면 한 줄로 접히고, 눌러서 과정을 다시 펼쳐 볼 수 있다.
import { useState } from 'react'
import * as I from './Icons'
import { NODE_LABEL } from './mock'
import type { StepState } from './steps'

export default function Progress({ steps, running, elapsedMs }: { steps: StepState[]; running: boolean; elapsedMs: number }) {
  const done = steps.filter((s) => s.status === 'done' || s.status === 'skip').length
  const finished = !running && done === steps.length
  // 기본: 진행 중엔 펼치고 끝나면 접는다. 사용자가 누른 선택은 그 상태(완료/진행)가 유지되는 동안만 따른다.
  const [choice, setChoice] = useState<{ finished: boolean; open: boolean } | null>(null)
  const open = choice && choice.finished === finished ? choice.open : !finished
  const setOpen = (fn: (v: boolean) => boolean) => setChoice({ finished, open: fn(open) })

  const totalSec = steps.reduce((sum, s) => sum + (s.ms || 0), 0) / 1000

  return (
    <section className={`progress${open ? '' : ' collapsed'}`} aria-label="진행 상태" aria-live="polite">
      <header className="progress-head">
        <strong>{running ? 'Odiro가 코스를 짜는 중' : finished ? '완성!' : '대기 중'}</strong>
        <span className="muted">
          {done}/{steps.length}
          {running && ` · ${(elapsedMs / 1000).toFixed(0)}초`}
          {finished && totalSec > 0 && ` · ${totalSec.toFixed(0)}초`}
        </span>
        {finished && (
          <button type="button" className="progress-toggle" onClick={() => setOpen((v) => !v)} aria-expanded={open}>
            {open ? '접기' : '과정 보기'}
            <I.Chevron className={`chevron${open ? ' up' : ''}`} />
          </button>
        )}
      </header>
      {open && (
        <ol className="progress-list">
          {steps.map((s) => (
            <li key={s.node} className={`step ${s.status}`}>
              <span className="step-mark" aria-hidden="true">
                {s.status === 'done' && <I.Check size={14} />}
                {s.status === 'start' && <span className="spinner" />}
                {s.status === 'error' && '!'}
                {s.status === 'skip' && '–'}
              </span>
              <span className="step-label">{NODE_LABEL[s.node] ?? s.node}</span>
              <span className="step-meta">
                {s.status === 'done' && s.ms > 0 && `${(s.ms / 1000).toFixed(1)}s`}
              </span>
              {s.detail && <span className="step-detail">{s.detail}</span>}
            </li>
          ))}
        </ol>
      )}
    </section>
  )
}
