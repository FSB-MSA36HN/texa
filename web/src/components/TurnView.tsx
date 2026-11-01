import { useState, type ReactNode } from 'react'
import { Check, ChevronDown, Copy, CornerDownRight, Download, Pencil, RotateCcw, ThumbsDown, ThumbsUp, X } from 'lucide-react'
import { api, type Bootstrap, type FormField, type Mark, type Step, type Turn } from '../api'
import { ERROR_HINTS, STEP_LABELS, formatCell, readingChips, rowCurrency, toCsv } from '../format'

type Props = {
  turn: Turn
  steps: Step[]
  boot: Bootstrap
  onAsk: (q: string) => void
  onRefresh: (turnId: string) => void
  onEdit?: (turnId: string, question: string) => Promise<void>
  busy?: boolean
  explainMarks?: boolean
}

const softBtn = 'inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1 text-sm text-lead transition-colors hover:bg-wash hover:text-ink'

export function TurnView({ turn, steps, boot, onAsk, onRefresh, onEdit, busy, explainMarks }: Props) {
  const [editing, setEditing] = useState(false)
  const done = turn.status !== 'running'
  return (
    <section className="space-y-5">
      {editing && onEdit
        ? <EditQuestion question={turn.question} onCancel={() => setEditing(false)} onSave={(q) => onEdit(turn.id, q).then(() => setEditing(false))} />
        : (
          <div className="group flex flex-col items-end gap-1">
            <p className="max-w-[85%] rounded-[20px] bg-wash px-4 py-2.5 leading-relaxed whitespace-pre-wrap">{turn.question}</p>
            <div className="flex gap-0.5 text-lead opacity-0 transition-opacity group-focus-within:opacity-100 group-hover:opacity-100 [@media(hover:none)]:opacity-100">
              <CopyButton text={turn.question} label="Chép câu hỏi" />
              {onEdit && <IconAction label="Sửa câu hỏi" disabled={busy} onClick={() => setEditing(true)}><Pencil className="h-4 w-4" /></IconAction>}
            </div>
          </div>
        )}
      <div className="min-w-0 space-y-4">
        {turn.status === 'running' && <Working steps={steps} onStop={() => api.cancel(turn.id)} />}
        <div key={turn.status} className={done ? 'answer-in' : ''}>
          <Body turn={turn} boot={boot} onAsk={onAsk} onRefresh={onRefresh} explainMarks={explainMarks} steps={steps} busy={busy} />
        </div>
      </div>
    </section>
  )
}

function IconAction({ label, onClick, disabled, children, on }: { label: string; onClick: () => void; disabled?: boolean; children: ReactNode; on?: boolean }) {
  return (
    <button aria-label={label} title={label} onClick={onClick} disabled={disabled} aria-pressed={on}
      className={`rounded-lg p-1.5 transition-colors hover:bg-wash disabled:pointer-events-none disabled:opacity-30 ${on ? 'text-ledger' : 'hover:text-ink'}`}>
      {children}
    </button>
  )
}

function CopyButton({ text, label }: { text: string; label: string }) {
  const [copied, setCopied] = useState(false)
  return (
    <IconAction label={copied ? 'Đã chép' : label} onClick={() => { navigator.clipboard.writeText(text); setCopied(true); setTimeout(() => setCopied(false), 1500) }}>
      {copied ? <Check className="h-4 w-4 text-ledger" /> : <Copy className="h-4 w-4" />}
    </IconAction>
  )
}

function EditQuestion({ question, onSave, onCancel }: { question: string; onSave: (q: string) => Promise<void>; onCancel: () => void }) {
  const [value, setValue] = useState(question)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const save = async () => {
    if (!value.trim() || saving) return
    setSaving(true)
    setError('')
    try { await onSave(value.trim()) } catch (e) { setError((e as Error).message); setSaving(false) }
  }
  return (
    <div className="ml-auto w-full max-w-[85%] rounded-[20px] border border-ledger/40 bg-sheet p-3">
      <textarea autoFocus value={value} onChange={(e) => setValue(e.target.value)} maxLength={2000} aria-label="Sửa câu hỏi"
        ref={(el) => { if (el) { el.style.height = 'auto'; el.style.height = `${Math.min(el.scrollHeight, 200)}px` } }}
        onKeyDown={(e) => {
          if (e.key === 'Escape') onCancel()
          if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); save() }
        }}
        className="w-full resize-none bg-transparent px-1 leading-relaxed outline-none" />
      <div className="mt-2 flex items-center gap-2">
        <p className="flex-1 text-xs text-lead">Các câu hỏi sau câu này sẽ bị xóa.</p>
        <button onClick={onCancel} className="rounded-full px-3 py-1.5 text-sm transition-colors hover:bg-wash">Hủy</button>
        <button onClick={save} disabled={!value.trim() || saving}
          className="rounded-full bg-ledger px-3.5 py-1.5 text-sm font-medium text-white transition-opacity hover:opacity-90 disabled:opacity-40 dark:text-paper">
          {saving ? 'Đang gửi…' : 'Gửi lại'}</button>
      </div>
      {error && <p role="alert" className="mt-2 text-sm text-rose-700 dark:text-rose-300">{error}</p>}
    </div>
  )
}

/** Plain text of an answer, for the copy button: what the user reads, without the table. */
function answerText(turn: Turn): string {
  const ins = turn.insight
  if (ins) return [ins.headline, ...ins.body, ...ins.caveats].filter(Boolean).join('\n\n')
  return turn.message ?? turn.form?.message ?? ''
}

function Body({ turn, boot, onAsk, onRefresh, explainMarks, steps, busy }: Props) {
  const retry = () => api.retry(turn.id).then(() => onRefresh(turn.id))
  switch (turn.status) {
    case 'running':
      return null
    case 'conversation':
      return (
        <div className="space-y-4">
          <p className="leading-relaxed whitespace-pre-wrap">{turn.message}</p>
          <FollowUps items={turn.suggestions} onPick={onAsk} />
          <Footer turn={turn} steps={steps} onRetry={retry} busy={busy} />
        </div>
      )
    case 'needs_clarification':
      return <ClarifyForm turn={turn} onSent={() => onRefresh(turn.id)} />
    case 'refused':
      return (
        <div className="space-y-4">
          <p className="leading-relaxed">{turn.message}</p>
          <FollowUps items={turn.suggestions} onPick={onAsk} label="Có thể hỏi thay" />
          <Footer turn={turn} steps={steps} onRetry={retry} busy={busy} />
        </div>
      )
    case 'error':
    case 'cancelled':
      return (
        <div className="flex flex-wrap items-center gap-3 border-l-2 border-amber-500 py-1 pl-4">
          <span className="flex-1 leading-relaxed">{turn.status === 'cancelled' ? 'Đã dừng câu hỏi này.' : ERROR_HINTS[turn.error?.code ?? ''] ?? turn.error?.message}</span>
          <button className={softBtn} disabled={busy} onClick={retry}><RotateCcw className="h-3.5 w-3.5" /> Hỏi lại</button>
        </div>
      )
    case 'discussed':
      return (
        <div className="space-y-5">
          <Insight turn={turn} explainMarks={explainMarks} />
          <FollowUps items={turn.insight?.follow_ups} onPick={onAsk} />
          <Footer turn={turn} steps={steps} onRetry={retry} busy={busy} />
        </div>
      )
    case 'answered':
      return <Answer turn={turn} boot={boot} onAsk={onAsk} onRefresh={onRefresh} explainMarks={explainMarks} steps={steps} busy={busy} />
  }
}

/** Marks every value the server substituted from SQL; the model never writes these digits itself. */
function Marked({ text, cited, marks }: { text: string; cited?: string[]; marks?: Mark[] }) {
  if (!cited?.length) return <>{text}</>
  const byText = new Map((marks ?? []).map((m) => [m.text, m]))
  const esc = cited.map((c) => c.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'))
  const parts = text.split(new RegExp(`(${esc.join('|')})`, 'g'))
  return <>{parts.map((p, i) => (cited.includes(p) ? <Value key={i} text={p} mark={byText.get(p)} /> : p))}</>
}

/** One cited number. SQL values are highlighted; calculations add a dotted rule and reveal their formula; values the
 * user stated are only underlined, since they are not data. */
function Value({ text, mark }: { text: string; mark?: Mark }) {
  const [open, setOpen] = useState(false)
  if (!mark || mark.kind === 'sql') return <mark className="sql-value">{text}</mark>
  if (mark.kind === 'user') return <span className="user-value" title={`${mark.label} (bạn đưa ra)`}>{text}</span>
  return (
    <span className="relative inline">
      <button type="button" onClick={() => setOpen(!open)} onBlur={() => setOpen(false)} aria-expanded={open}
        aria-label={`${text}: ${mark.label}. Xem cách tính`} className="calc-value sql-value cursor-help">{text}</button>
      {open && (
        <span role="tooltip" className="absolute top-full left-0 z-10 mt-1.5 block w-max max-w-[min(26rem,80vw)] rounded-xl border border-rule bg-sheet px-3 py-2 font-sans text-[13px] leading-snug text-ink shadow-lg">
          <span className="block font-medium">{mark.label}</span>
          <span className="mt-0.5 block text-lead">= {mark.formula}</span>
        </span>
      )}
    </span>
  )
}

function Insight({ turn, explainMarks }: { turn: Turn; explainMarks?: boolean }) {
  const ins = turn.insight
  if (!ins) return null
  return (
    <div className="space-y-3">
      <p className="font-serif text-[1.375rem] leading-snug tracking-[-0.005em] text-ink"><Marked text={ins.headline} cited={ins.cited} marks={ins.marks} /></p>
      {ins.body.map((b, i) => <p key={i} className="leading-relaxed text-ink/85"><Marked text={b} cited={ins.cited} marks={ins.marks} /></p>)}
      {ins.caveats.length > 0 && (
        <ul className="space-y-1 text-sm leading-relaxed text-lead">{ins.caveats.map((c, i) => <li key={i}><Marked text={c} cited={ins.cited} marks={ins.marks} /></li>)}</ul>
      )}
      {(explainMarks || ins.marks?.some((m) => m.kind !== 'sql')) && !!ins.cited?.length && <MarkLegend marks={ins.marks} />}
    </div>
  )
}

function MarkLegend({ marks }: { marks?: Mark[] }) {
  const kinds = new Set((marks ?? []).map((m) => m.kind))
  if (!kinds.size) kinds.add('sql')
  return (
    <p className="flex flex-wrap items-center gap-x-4 gap-y-1 pt-1 text-xs text-lead">
      {kinds.has('sql') && <span className="flex items-center gap-1.5"><span aria-hidden className="inline-block h-2.5 w-5 rounded-sm bg-mark" /> lấy thẳng từ SQL</span>}
      {kinds.has('calculation') && <span className="flex items-center gap-1.5"><span aria-hidden className="calc-swatch inline-block h-2.5 w-5 rounded-sm bg-mark" /> Texa tính từ số liệu, bấm để xem công thức</span>}
      {kinds.has('user') && <span className="flex items-center gap-1.5"><span aria-hidden className="user-value">5,2</span> số bạn đưa ra</span>}
      <span>Không con số nào do AI tự viết.</span>
    </p>
  )
}

function Answer({ turn, boot, onAsk, onRefresh, explainMarks, steps, busy }: Props) {
  const empty = !turn.row_count
  // With no rows, the insight already explains why; the server's English "no rows" note would only repeat it.
  const notes = [...(turn.notes ?? []), ...(turn.warnings ?? [])].filter((w) => !(empty && w.startsWith('No rows match')))
  return (
    <div className="space-y-5">
      <QueryReading turn={turn} boot={boot} />
      <Insight turn={turn} explainMarks={explainMarks} />
      {notes.length > 0 && (
        <ul className="space-y-1.5 border-l-2 border-amber-400 pl-4 text-sm leading-relaxed text-ink/80">
          {notes.map((w, i) => <li key={i}>{w}</li>)}
        </ul>
      )}
      {!empty && <ResultPanel turn={turn} />}
      <FollowUps items={turn.insight?.follow_ups} onPick={onAsk} />
      <Footer turn={turn} steps={steps} onRetry={() => api.retry(turn.id).then(() => onRefresh(turn.id))} busy={busy}
        details={<Computed turn={turn} boot={boot} onRefresh={onRefresh} />} />
    </div>
  )
}

/** Business interpretation stays visible without opening technical SQL details. */
function QueryReading({ turn, boot }: { turn: Turn; boot: Bootstrap }) {
  if (!turn.query_spec) return null
  const chips = readingChips(turn.query_spec, boot, turn.period)
  const inherited = turn.context?.relation === 'followup'
  return (
    <aside aria-label="Cách hiểu câu hỏi" className="space-y-2 rounded-xl border border-rule bg-wash/40 px-3 py-2.5 text-sm">
      <p className="font-medium">Phạm vi tính</p>
      <div className="flex flex-wrap gap-1.5">
        {chips.filter(Boolean).map((chip, i) => <span key={i} className="rounded-md bg-sheet px-2 py-0.5 text-ink/80">{chip}</span>)}
      </div>
      {turn.metric_definitions?.map((metric) => <p key={metric.id} className="text-xs leading-relaxed text-lead">{metric.label}: {metric.description}</p>)}
      {inherited && <p className="text-xs text-lead">Tiếp nối: {turn.context?.questions?.slice(-1)[0] ?? 'kết quả trước đã chọn'}</p>}
      {turn.dataset_version && <p className="text-xs text-lead">Phiên bản dữ liệu: {turn.dataset_version}</p>}
    </aside>
  )
}

/** The technical reading of a result: metric (and its variants), breakdowns, period, sources, SQL. */
function Computed({ turn, boot, onRefresh }: { turn: Turn; boot: Bootstrap; onRefresh: (id: string) => void }) {
  const [copied, setCopied] = useState(false)
  const spec = turn.query_spec!
  const [metric, ...rest] = readingChips(spec, boot, turn.period)
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-1.5 text-[13px]">
        <span className="mr-0.5 text-lead">Đã tính</span>
        {turn.variants && turn.variants.length > 1 ? (
          <label className="relative inline-flex items-center rounded-md border border-rule bg-sheet text-ink/80 transition-colors hover:border-ledger/40">
            <span className="sr-only">Cách tính</span>
            <select value={spec.recipe} onChange={(e) => api.variant(turn.id, e.target.value).then(() => onRefresh(turn.id))}
              className="cursor-pointer appearance-none bg-transparent py-0.5 pr-6 pl-2 outline-none">
              {turn.variants.map((v) => <option key={v.id} value={v.id}>{v.label}</option>)}
            </select>
            <ChevronDown className="pointer-events-none absolute right-1.5 h-3 w-3" />
          </label>
        ) : <span className="rounded-md border border-rule bg-sheet px-2 py-0.5 text-ink/80">{metric}</span>}
        {rest.map((c) => <span key={c} className="rounded-md border border-rule bg-sheet px-2 py-0.5 text-ink/80">{c}</span>)}
      </div>
      {turn.compiled_sql && (
        <div className="overflow-hidden rounded-xl border border-rule">
          <div className="flex items-center justify-between border-b border-rule bg-sheet px-3 py-1">
            <span className="text-xs text-lead">SQL</span>
            <button onClick={() => { navigator.clipboard.writeText(turn.compiled_sql ?? ''); setCopied(true); setTimeout(() => setCopied(false), 1500) }}
              className={`${softBtn} -mr-2 text-xs`}>
              {copied ? <Check className="h-3.5 w-3.5 text-ledger" /> : <Copy className="h-3.5 w-3.5" />} {copied ? 'Đã chép' : 'Chép SQL'}</button>
          </div>
          <pre className="scroll-thin max-h-72 overflow-auto bg-wash px-3 py-3 font-mono text-[12.5px] leading-relaxed text-ink/90"><code>{prettySql(turn.compiled_sql)}</code></pre>
        </div>
      )}
    </div>
  )
}

function FollowUps({ items, onPick, label }: { items?: string[]; onPick: (q: string) => void; label?: string }) {
  if (!items?.length) return null
  return (
    <div className="space-y-1">
      {label && <p className="text-sm text-lead">{label}</p>}
      <ul className="divide-y divide-rule border-y border-rule">
        {items.map((s) => (
          <li key={s}>
            <button onClick={() => onPick(s)} className="group flex w-full items-start gap-2.5 py-2 text-left text-[15px] text-ink/85 transition-colors hover:text-ledger-ink">
              <CornerDownRight className="mt-1 h-3.5 w-3.5 shrink-0 text-lead transition-colors group-hover:text-ledger" />{s}</button>
          </li>
        ))}
      </ul>
    </div>
  )
}

function Working({ steps, onStop }: { steps: Step[]; onStop: () => void }) {
  const latest = new Map<string, Step>()
  for (const s of steps) if (s.step !== 'result') latest.set(s.step, s)
  const current = [...latest.values()].reverse().find((s) => s.status === 'running')
  return (
    <div className="flex items-center gap-3 text-[15px] text-lead" aria-live="polite">
      <span className="dots flex gap-1" aria-hidden>{[0, 1, 2].map((i) => <span key={i} className="h-1.5 w-1.5 rounded-full bg-ledger" />)}</span>
      <span>{STEP_LABELS[current?.step ?? ''] ?? 'Đang đọc câu hỏi'}…</span>
      <button onClick={onStop} className={`${softBtn} ml-auto`}><X className="h-3.5 w-3.5" /> Dừng</button>
    </div>
  )
}

/** Thumbs, timing and the run log, quiet under each finished answer. */
function Footer({ turn, steps, onRetry, busy, details }: { turn: Turn; steps: Step[]; onRetry: () => void; busy?: boolean; details?: ReactNode }) {
  const [open, setOpen] = useState(false)
  const latest = new Map<string, Step>()
  for (const s of steps) if (s.step !== 'result') latest.set(s.step, s)
  const list = [...latest.values()]
  const total = list.reduce((a, s) => a + (s.ms ?? 0), 0)
  const hasDetails = !!details || list.length > 0
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-0.5 text-lead">
        <CopyButton text={answerText(turn)} label="Chép câu trả lời" />
        <IconAction label="Hỏi lại" disabled={busy} onClick={onRetry}><RotateCcw className="h-4 w-4" /></IconAction>
        <Feedback turn={turn} />
        {hasDetails && (
          <button onClick={() => setOpen(!open)} aria-expanded={open} className={`${softBtn} ml-auto text-xs`}>
            Chi tiết{list.length > 0 && ` · ${(total / 1000).toFixed(1)} giây`}
            <ChevronDown className={`h-3 w-3 transition-transform ${open ? 'rotate-180' : ''}`} /></button>
        )}
      </div>
      {open && (
        <div className="answer-in space-y-3 rounded-xl bg-wash/60 p-3">
          {details}
          {list.length > 0 && (
            <ol className="space-y-1 text-[13px]">
              {list.map((s) => (
                <li key={s.step} className="flex items-center gap-2.5">
                  {s.status === 'failed' ? <X className="h-3.5 w-3.5 text-rose-500" /> : <Check className="h-3.5 w-3.5 text-ledger" />}
                  <span className="w-36 shrink-0 text-ink/85">{STEP_LABELS[s.step] ?? s.step}</span>
                  <span className="flex-1 truncate text-lead">{s.note}</span>
                  {s.ms !== undefined && <span className="text-lead">{s.ms} ms</span>}
                </li>
              ))}
            </ol>
          )}
        </div>
      )}
    </div>
  )
}

function ClarifyForm({ turn, onSent }: { turn: Turn; onSent: () => void }) {
  const fields = turn.form?.fields ?? []
  const [values, setValues] = useState<Record<string, string[]>>(() => Object.fromEntries(fields.map((f) => [f.id, f.default ?? []])))
  const [other, setOther] = useState<Record<string, string>>({})
  const [sending, setSending] = useState(false)
  const [error, setError] = useState('')
  const merged = (f: FormField) => [...(values[f.id] ?? []), ...(other[f.id]?.trim() ? [other[f.id].trim()] : [])]
  const ready = fields.every((f) => !f.required || merged(f).length > 0)
  const toggle = (f: FormField, id: string) =>
    setValues((v) => ({ ...v, [f.id]: f.kind === 'single_choice' ? [id] : v[f.id]?.includes(id) ? v[f.id].filter((x) => x !== id) : [...(v[f.id] ?? []), id] }))
  const send = async () => {
    setSending(true)
    setError('')
    try {
      await api.answer(turn.id, Object.fromEntries(fields.map((f) => [f.id, merged(f)])))
      onSent()
    } catch (e) {
      setError((e as Error).message)
      setSending(false)
    }
  }
  return (
    <div className="space-y-5">
      <p className="leading-relaxed">{turn.form?.message}</p>
      {fields.map((f) => (
        <fieldset key={f.id} className="space-y-2">
          <legend className="mb-2 text-sm text-lead">{f.label}</legend>
          <div className="flex flex-wrap gap-2">
            {f.choices.map((c) => {
              const on = values[f.id]?.includes(c.id)
              return (
                <button key={c.id} type="button" aria-pressed={on} title={c.description} onClick={() => toggle(f, c.id)}
                  className={`rounded-full border px-3.5 py-1.5 text-sm transition-colors ${on ? 'border-ledger bg-ledger text-white dark:text-paper' : 'border-rule bg-sheet hover:border-ledger/40'}`}>
                  {c.label}
                  {c.description && <span className={`ml-1.5 text-xs ${on ? 'opacity-80' : 'text-lead'}`}>{c.description}</span>}
                </button>
              )
            })}
          </div>
          {f.allow_other && (
            <input value={other[f.id] ?? ''} onChange={(e) => setOther((o) => ({ ...o, [f.id]: e.target.value }))} placeholder="Ý khác…" maxLength={200} aria-label={`${f.label}: ý khác`}
              className="w-full max-w-xs rounded-lg border border-rule bg-sheet px-3 py-1.5 text-sm outline-none focus:border-ledger/50" />
          )}
        </fieldset>
      ))}
      {error && <p role="alert" className="text-sm text-rose-700 dark:text-rose-300">{error}</p>}
      <button disabled={!ready || sending} onClick={send}
        className="rounded-full bg-ledger px-4 py-2 text-sm font-medium text-white transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40 dark:text-paper">
        {sending ? 'Đang tính…' : 'Tính với lựa chọn này'}</button>
    </div>
  )
}

function ResultPanel({ turn }: { turn: Turn }) {
  const [full, setFull] = useState<{ rows: Record<string, unknown>[]; partial: boolean } | null>(null)
  const [loadingFull, setLoadingFull] = useState(false)
  const [page, setPage] = useState(0)
  const columns = turn.columns ?? []
  const rows = full?.rows ?? turn.rows ?? []
  const more = rows.length < (turn.row_count ?? 0)
  const pages = Math.max(1, Math.ceil(rows.length / PAGE))

  const loadFull = async () => {
    setLoadingFull(true)
    try { setFull(await api.fullResult(turn.id)) } finally { setLoadingFull(false) }
  }
  const download = async () => {
    const data = full ?? (more ? await api.fullResult(turn.id) : { rows })
    const blob = new Blob(['\ufeff' + toCsv(columns, data.rows)], { type: 'text/csv;charset=utf-8' })
    const a = Object.assign(document.createElement('a'), { href: URL.createObjectURL(blob), download: 'texa-result.csv' })
    a.click()
    URL.revokeObjectURL(a.href)
  }

  return (
    <div className="overflow-hidden rounded-2xl border border-rule bg-sheet">
      <DataTable columns={columns} rows={rows.slice(page * PAGE, page * PAGE + PAGE)} currencyOf={turn.currency_of} />
      <div className="flex items-center justify-end gap-3 border-t border-rule px-4 py-1.5">
        {pages > 1 && (
          <span className="mr-auto flex items-center gap-1 text-xs text-lead">
            <button aria-label="Trang trước" disabled={page === 0} onClick={() => setPage(page - 1)} className="rounded-md px-2 py-1 hover:bg-wash disabled:opacity-30">‹</button>
            {page + 1} / {pages}
            <button aria-label="Trang sau" disabled={page >= pages - 1} onClick={() => setPage(page + 1)} className="rounded-md px-2 py-1 hover:bg-wash disabled:opacity-30">›</button>
          </span>
        )}
        <span className="text-xs text-lead">{rows.length}{more || turn.partial ? ` / ${turn.row_count}${turn.partial ? '+' : ''}` : ''} dòng</span>
        {more && <button onClick={loadFull} disabled={loadingFull} className="text-xs font-medium text-ledger-ink hover:underline">{loadingFull ? 'Đang tải…' : 'Xem hết'}</button>}
        <button onClick={download} className={`${softBtn} -mr-2 text-xs`}><Download className="h-3.5 w-3.5" /> Tải CSV</button>
      </div>
    </div>
  )
}

const PAGE = 20

function DataTable({ columns, rows, currencyOf }: { columns: Turn['columns'] & {}; rows: Record<string, unknown>[]; currencyOf?: Record<string, string> }) {
  return (
    <div className="scroll-thin max-h-96 overflow-auto">
      <table className="w-full text-sm">
        <thead className="sticky top-0 bg-sheet">
          <tr>{columns.map((c) => (
            <th key={c.name} scope="col" className={`border-b border-rule px-4 py-2.5 text-[13px] font-medium text-lead ${c.role === 'metric' ? 'text-right' : 'text-left'}`}>{c.label}</th>
          ))}</tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i} className="border-b border-rule/60 last:border-0 hover:bg-wash/60">
              {columns.map((c) => (
                <td key={c.name} className={`px-4 py-2 ${c.role === 'metric' ? 'text-right' : ''} ${r[c.name] == null ? 'text-lead' : ''}`}>
                  {formatCell(r[c.name], c, c.currency ?? rowCurrency(r, currencyOf))}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function prettySql(sql: string) {
  return sql.replace(/\s+(FROM|WHERE|GROUP BY|ORDER BY|LIMIT|JOIN|LEFT JOIN|WITH|SELECT \* FROM)\s/g, '\n$1 ').replace(/,\s(?=(count|sum|avg|min|max|coalesce|\(|CASE|"))/g, ',\n  ')
}

function Feedback({ turn }: { turn: Turn }) {
  const [rating, setRating] = useState(turn.feedback?.rating)
  const [asking, setAsking] = useState(false)
  const [comment, setComment] = useState('')
  const [sent, setSent] = useState(false)
  const send = async (r: 'up' | 'down', c = '') => {
    await api.feedback(turn.id, r, c)
    setRating(r)
    setAsking(false)
    setSent(true)
  }
  const thumb = (on: boolean, label: string, icon: ReactNode, onClick: () => void) => (
    <IconAction label={label} on={on} onClick={onClick}>{icon}</IconAction>
  )
  return (
    <>
      {thumb(rating === 'up', 'Đúng ý', <ThumbsUp className="h-4 w-4" />, () => send('up'))}
      {thumb(rating === 'down', 'Chưa đúng', <ThumbsDown className="h-4 w-4" />, () => setAsking(!asking))}
      {sent && !asking && <span className="ml-1 text-xs">Đã ghi nhận</span>}
      {asking && (
        <form className="ml-1 flex flex-1 gap-2" onSubmit={(e) => { e.preventDefault(); send('down', comment) }}>
          <input autoFocus value={comment} onChange={(e) => setComment(e.target.value)} maxLength={1000} placeholder="Chỗ nào chưa đúng?" aria-label="Góp ý"
            className="min-w-0 flex-1 rounded-lg border border-rule bg-sheet px-3 py-1 text-sm text-ink outline-none focus:border-ledger/50" />
          <button className="rounded-lg bg-ink px-3 py-1 text-sm text-paper">Gửi góp ý</button>
        </form>
      )}
    </>
  )
}

