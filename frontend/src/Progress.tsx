// 사이드바 노드 진행 표시. SSE progress 이벤트로 갱신된다.
import * as I from './Icons'
import { NODE_LABEL } from './mock'
import type { StepState } from './steps'

export default function Progress({ steps, running, elapsedMs }: { steps: StepState[]; running: boolean; elapsedMs: number }) {
  const done = steps.filter((s) => s.status === 'done' || s.status === 'skip').length
  return (
    <section className="progress" aria-label="진행 상태" aria-live="polite">
      <header className="progress-head">
        <strong>{running ? 'Odiro가 코스를 짜는 중' : done === steps.length ? '완성!' : '대기 중'}</strong>
        <span className="muted">
          {done}/{steps.length}
          {running && ` · ${(elapsedMs / 1000).toFixed(0)}초`}
        </span>
      </header>
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
    </section>
  )
}
