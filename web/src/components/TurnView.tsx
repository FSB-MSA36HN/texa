import { useState } from 'react'
import { AlertTriangle, Ban, Check, ChevronDown, ChevronRight, Copy, Download, Loader2, RotateCcw, Square, ThumbsDown, ThumbsUp, X } from 'lucide-react'
import { api, type Bootstrap, type FormField, type Step, type Turn } from '../api'
import { ERROR_HINTS, STEP_LABELS, formatCell, readingChips, rowCurrency, toCsv } from '../format'

type Props = {
  turn: Turn
  steps: Step[]
  boot: Bootstrap
  onAsk: (q: string) => void
  onRefresh: (turnId: string) => void
}

export function TurnView({ turn, steps, boot, onAsk, onRefresh }: Props) {
  return (
    <div className="space-y-3">
      <div className="flex justify-end">
        <div className="max-w-[85%] rounded-2xl rounded-br-md bg-indigo-600 px-4 py-2.5 text-white whitespace-pre-wrap">{turn.question}</div>
      </div>
      <div className="flex gap-3">
        <div className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-indigo-500 to-fuchsia-500 text-xs font-bold text-white">T</div>
        <div className="min-w-0 flex-1 space-y-3">
          {(turn.status === 'running' || steps.length > 0) && <RunProgress steps={steps} running={turn.status === 'running'} onStop={() => api.cancel(turn.id)} />}
          <Body turn={turn} boot={boot} onAsk={onAsk} onRefresh={onRefresh} />
        </div>
      </div>
    </div>
  )
}

function Body({ turn, boot, onAsk, onRefresh }: Omit<Props, 'steps'>) {
  switch (turn.status) {
    case 'running':
      return null
    case 'conversation':
      return (
        <div className="space-y-3">
          <p className="whitespace-pre-wrap leading-relaxed">{turn.message}</p>
          <Chips items={turn.suggestions} onPick={onAsk} />
        </div>
      )
    case 'needs_clarification':
      return <ClarifyForm turn={turn} onSent={() => onRefresh(turn.id)} />
    case 'refused':
      return (
        <div className="space-y-3 rounded-xl border border-rose-200 bg-rose-50 p-4 dark:border-rose-900/60 dark:bg-rose-950/40">
          <div className="flex gap-2 text-rose-800 dark:text-rose-200"><Ban className="mt-0.5 h-4 w-4 shrink-0" /><p>{turn.message}</p></div>
          {!!turn.suggestions?.length && <p className="text-sm text-slate-600 dark:text-slate-400">Bạn có thể hỏi:</p>}
          <Chips items={turn.suggestions} onPick={onAsk} />
        </div>
      )
    case 'error':
    case 'cancelled':
      return (
        <div className="flex flex-wrap items-center gap-3 rounded-xl border border-amber-200 bg-amber-50 p-4 text-amber-900 dark:border-amber-900/60 dark:bg-amber-950/40 dark:text-amber-100">
          <AlertTriangle className="h-4 w-4 shrink-0" />
          <span className="flex-1">{turn.status === 'cancelled' ? 'Đã dừng.' : ERROR_HINTS[turn.error?.code ?? ''] ?? turn.error?.message}</span>
          <button className="inline-flex items-center gap-1 rounded-lg bg-amber-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-amber-700"
            onClick={() => api.retry(turn.id).then(() => onRefresh(turn.id))}><RotateCcw className="h-3.5 w-3.5" /> Thử lại</button>
        </div>
      )
    case 'discussed':
      return <><InsightBlock turn={turn} onAsk={onAsk} /><Feedback turn={turn} /></>
    case 'answered':
      return <ResultCard turn={turn} boot={boot} onAsk={onAsk} onRefresh={onRefresh} />
  }
}

function Chips({ items, onPick }: { items?: string[]; onPick: (q: string) => void }) {
  if (!items?.length) return null
  return (
    <div className="flex flex-wrap gap-2">
      {items.map((s) => (
        <button key={s} onClick={() => onPick(s)}
          className="rounded-full border border-slate-200 bg-white px-3 py-1.5 text-left text-sm text-slate-700 hover:border-indigo-400 hover:text-indigo-700 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300 dark:hover:border-indigo-500 dark:hover:text-indigo-300">{s}</button>
      ))}
    </div>
  )
}

function RunProgress({ steps, running, onStop }: { steps: Step[]; running: boolean; onStop: () => void }) {
  const [open, setOpen] = useState(false)
  // One row per step: the latest status wins.
  const latest = new Map<string, Step>()
  for (const s of steps) if (s.step !== 'result') latest.set(s.step, s)
  const list = [...latest.values()]
  const current = [...list].reverse().find((s) => s.status === 'running')
  const total = list.reduce((a, s) => a + (s.ms ?? 0), 0)
  return (
    <div className="rounded-xl border border-slate-200 bg-slate-50/70 text-sm dark:border-slate-800 dark:bg-slate-900/60">
      <div className="flex items-center gap-2 px-3 py-2">
        <button className="flex flex-1 items-center gap-2 text-left text-slate-600 dark:text-slate-400" onClick={() => setOpen(!open)}>
          {open ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
          {running ? <Loader2 className="h-4 w-4 animate-spin text-indigo-500" /> : <Check className="h-4 w-4 text-emerald-500" />}
          <span>{running ? `${STEP_LABELS[current?.step ?? ''] ?? 'Đang xử lý'}…` : `Xong ${list.length} bước · ${(total / 1000).toFixed(1)} giây`}</span>
        </button>
        {running && (
          <button onClick={onStop} className="inline-flex items-center gap-1 rounded-md border border-slate-300 px-2 py-0.5 text-xs text-slate-600 hover:bg-white dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800">
            <Square className="h-3 w-3" /> Dừng</button>
        )}
      </div>
      {open && (
        <ol className="space-y-1 border-t border-slate-200 px-3 py-2 dark:border-slate-800">
          {list.map((s) => (
            <li key={s.step} className="flex items-center gap-2">
              {s.status === 'running' ? <Loader2 className="h-3.5 w-3.5 animate-spin text-indigo-500" />
                : s.status === 'done' ? <Check className="h-3.5 w-3.5 text-emerald-500" /> : <X className="h-3.5 w-3.5 text-rose-500" />}
              <span className="w-40 shrink-0">{STEP_LABELS[s.step] ?? s.step}</span>
              <span className="flex-1 truncate text-slate-500">{s.note}</span>
              {s.ms !== undefined && <span className="tabular-nums text-slate-400">{s.ms} ms</span>}
            </li>
          ))}
        </ol>
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
    <div className="space-y-4 rounded-xl border border-amber-200 bg-amber-50/70 p-4 dark:border-amber-900/60 dark:bg-amber-950/30">
      <p className="font-medium text-amber-900 dark:text-amber-100">{turn.form?.message}</p>
      {fields.map((f) => (
        <fieldset key={f.id} className="space-y-2">
          <legend className="text-sm text-slate-700 dark:text-slate-300">{f.label}</legend>
          <div className="flex flex-wrap gap-2">
            {f.choices.map((c) => {
              const on = values[f.id]?.includes(c.id)
              return (
                <button key={c.id} type="button" aria-pressed={on} title={c.description} onClick={() => toggle(f, c.id)}
                  className={`rounded-lg border px-3 py-1.5 text-sm transition ${on ? 'border-indigo-600 bg-indigo-600 text-white' : 'border-slate-300 bg-white hover:border-indigo-400 dark:border-slate-700 dark:bg-slate-900'}`}>
                  {f.kind === 'multi_choice' && <span className="mr-1.5">{on ? '☑' : '☐'}</span>}
                  {c.label}
                  {c.description && <span className={`ml-1.5 text-xs ${on ? 'text-indigo-100' : 'text-slate-500'}`}>{c.description}</span>}
                </button>
              )
            })}
          </div>
          {f.allow_other && (
            <input value={other[f.id] ?? ''} onChange={(e) => setOther((o) => ({ ...o, [f.id]: e.target.value }))} placeholder="Khác…" maxLength={200}
              className="w-full max-w-xs rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm dark:border-slate-700 dark:bg-slate-900" />
          )}
        </fieldset>
      ))}
      {error && <p className="text-sm text-rose-600">{error}</p>}
      <button disabled={!ready || sending} onClick={send}
        className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-40">
        {sending ? 'Đang gửi…' : 'Tiếp tục'}</button>
    </div>
  )
}

function InsightBlock({ turn, onAsk }: { turn: Turn; onAsk: (q: string) => void }) {
  const ins = turn.insight
  if (!ins) return null
  return (
    <div className="space-y-2">
      <p className="text-[15px] font-semibold leading-relaxed">{ins.headline}</p>
      {ins.body.map((b, i) => <p key={i} className="leading-relaxed text-slate-700 dark:text-slate-300">{b}</p>)}
      {ins.caveats.length > 0 && (
        <ul className="space-y-1 text-sm text-slate-500">{ins.caveats.map((c, i) => <li key={i}>• {c}</li>)}</ul>
      )}
      <div className="pt-1"><Chips items={ins.follow_ups} onPick={onAsk} /></div>
    </div>
  )
}

function ResultCard({ turn, boot, onAsk, onRefresh }: Omit<Props, 'steps'>) {
  const [tab, setTab] = useState<'table' | 'sql'>('table')
  const [full, setFull] = useState<{ rows: Record<string, unknown>[]; partial: boolean } | null>(null)
  const [loadingFull, setLoadingFull] = useState(false)
  const [copied, setCopied] = useState(false)
  const columns = turn.columns ?? []
  const rows = full?.rows ?? turn.rows ?? []
  const spec = turn.query_spec!
  const current = spec.recipe

  const loadFull = async () => {
    setLoadingFull(true)
    try { setFull(await api.fullResult(turn.id)) } finally { setLoadingFull(false) }
  }
  const download = async () => {
    const data = full ?? (rows.length < (turn.row_count ?? 0) ? await api.fullResult(turn.id) : { rows })
    const blob = new Blob(['﻿' + toCsv(columns, data.rows)], { type: 'text/csv;charset=utf-8' })
    const a = Object.assign(document.createElement('a'), { href: URL.createObjectURL(blob), download: 'texa-result.csv' })
    a.click()
    URL.revokeObjectURL(a.href)
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-1.5 text-xs">
        <span className="text-slate-500">Texa hiểu là:</span>
        {readingChips(spec, boot, turn.period).map((c) => (
          <span key={c} className="rounded-md bg-slate-100 px-2 py-0.5 text-slate-700 dark:bg-slate-800 dark:text-slate-300">{c}</span>
        ))}
        {turn.variants && turn.variants.length > 1 && (
          <select value={current} onChange={(e) => api.variant(turn.id, e.target.value).then(() => onRefresh(turn.id))}
            className="rounded-md border border-slate-300 bg-white px-1.5 py-0.5 dark:border-slate-700 dark:bg-slate-900" title="Cách tính">
            {turn.variants.map((v) => <option key={v.id} value={v.id}>Cách tính: {v.label}</option>)}
          </select>
        )}
      </div>

      <InsightBlock turn={{ ...turn, insight: turn.insight && { ...turn.insight, follow_ups: [] } }} onAsk={onAsk} />

      {[...(turn.notes ?? []), ...(turn.warnings ?? [])].length > 0 && (
        <ul className="space-y-1 rounded-lg bg-amber-50 px-3 py-2 text-sm text-amber-900 dark:bg-amber-950/40 dark:text-amber-200">
          {[...(turn.notes ?? []), ...(turn.warnings ?? [])].map((w, i) => <li key={i} className="flex gap-2"><AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />{w}</li>)}
        </ul>
      )}

      <div className="overflow-hidden rounded-xl border border-slate-200 dark:border-slate-800">
        <div className="flex items-center gap-1 border-b border-slate-200 bg-slate-50 px-2 py-1.5 text-sm dark:border-slate-800 dark:bg-slate-900">
          {(['table', 'sql'] as const).map((k) => (
            <button key={k} onClick={() => setTab(k)}
              className={`rounded-md px-3 py-1 ${tab === k ? 'bg-white font-medium shadow-sm dark:bg-slate-800' : 'text-slate-500 hover:text-slate-800 dark:hover:text-slate-200'}`}>
              {k === 'table' ? 'Bảng' : 'SQL'}</button>
          ))}
          <span className="flex-1" />
          {tab === 'table' && <>
            <span className="px-2 text-xs text-slate-500">{rows.length} / {turn.row_count}{turn.partial ? '+' : ''} dòng</span>
            {rows.length < (turn.row_count ?? 0) && (
              <button onClick={loadFull} disabled={loadingFull} className="rounded-md px-2 py-1 text-xs text-indigo-600 hover:bg-white dark:text-indigo-400 dark:hover:bg-slate-800">
                {loadingFull ? 'Đang tải…' : 'Tải full'}</button>
            )}
            <button onClick={download} title="Tải CSV" className="rounded-md p-1 text-slate-500 hover:bg-white dark:hover:bg-slate-800"><Download className="h-4 w-4" /></button>
          </>}
          {tab === 'sql' && (
            <button onClick={() => { navigator.clipboard.writeText(turn.compiled_sql ?? ''); setCopied(true); setTimeout(() => setCopied(false), 1500) }}
              className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs text-slate-600 hover:bg-white dark:text-slate-300 dark:hover:bg-slate-800">
              {copied ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />} {copied ? 'Đã copy' : 'Copy'}</button>
          )}
        </div>
        {tab === 'table' ? <DataTable columns={columns} rows={rows} currencyOf={turn.currency_of} />
          : <pre className="scroll-thin max-h-80 overflow-auto bg-slate-950 p-4 text-xs leading-relaxed text-slate-100"><code>{prettySql(turn.compiled_sql ?? '')}</code></pre>}
      </div>

      {!!turn.insight?.follow_ups.length && <Chips items={turn.insight.follow_ups} onPick={onAsk} />}
      <Feedback turn={turn} />
    </div>
  )
}

const PAGE = 20

function DataTable({ columns, rows, currencyOf }: { columns: Turn['columns'] & {}; rows: Record<string, unknown>[]; currencyOf?: Record<string, string> }) {
  const [page, setPage] = useState(0)
  const pages = Math.max(1, Math.ceil(rows.length / PAGE))
  const view = rows.slice(page * PAGE, page * PAGE + PAGE)
  if (!rows.length) return <p className="p-4 text-sm text-slate-500">Không có dòng nào.</p>
  return (
    <div>
      <div className="scroll-thin max-h-96 overflow-auto">
        <table className="w-full text-sm">
          <thead className="sticky top-0 bg-white dark:bg-slate-950">
            <tr>{columns.map((c) => (
              <th key={c.name} className={`border-b border-slate-200 px-3 py-2 font-medium text-slate-600 dark:border-slate-800 dark:text-slate-400 ${c.role === 'metric' ? 'text-right' : 'text-left'}`}>{c.label}</th>
            ))}</tr>
          </thead>
          <tbody>
            {view.map((r, i) => (
              <tr key={i} className="odd:bg-slate-50/60 dark:odd:bg-slate-900/40">
                {columns.map((c) => (
                  <td key={c.name} className={`px-3 py-1.5 ${c.role === 'metric' ? 'text-right tabular-nums' : ''} ${r[c.name] == null ? 'text-slate-400' : ''}`}>
                    {formatCell(r[c.name], c, rowCurrency(r, currencyOf))}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {pages > 1 && (
        <div className="flex items-center justify-end gap-2 border-t border-slate-200 px-3 py-1.5 text-xs dark:border-slate-800">
          <button disabled={page === 0} onClick={() => setPage(page - 1)} className="rounded px-2 py-0.5 hover:bg-slate-100 disabled:opacity-30 dark:hover:bg-slate-800">‹</button>
          <span className="tabular-nums text-slate-500">{page + 1} / {pages}</span>
          <button disabled={page >= pages - 1} onClick={() => setPage(page + 1)} className="rounded px-2 py-0.5 hover:bg-slate-100 disabled:opacity-30 dark:hover:bg-slate-800">›</button>
        </div>
      )}
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
  return (
    <div className="flex flex-wrap items-center gap-2 text-slate-400">
      <button aria-label="Hữu ích" onClick={() => send('up')} className={`rounded p-1 hover:bg-slate-100 dark:hover:bg-slate-800 ${rating === 'up' ? 'text-emerald-500' : ''}`}><ThumbsUp className="h-4 w-4" /></button>
      <button aria-label="Chưa đúng" onClick={() => setAsking(!asking)} className={`rounded p-1 hover:bg-slate-100 dark:hover:bg-slate-800 ${rating === 'down' ? 'text-rose-500' : ''}`}><ThumbsDown className="h-4 w-4" /></button>
      {sent && !asking && <span className="text-xs">Cảm ơn góp ý!</span>}
      {asking && (
        <div className="flex w-full gap-2">
          <input autoFocus value={comment} onChange={(e) => setComment(e.target.value)} maxLength={1000} placeholder="Chỗ nào chưa đúng?"
            onKeyDown={(e) => e.key === 'Enter' && send('down', comment)}
            className="flex-1 rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm text-slate-800 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200" />
          <button onClick={() => send('down', comment)} className="rounded-lg bg-slate-800 px-3 py-1.5 text-sm text-white dark:bg-slate-200 dark:text-slate-900">Gửi</button>
        </div>
      )}
    </div>
  )
}
