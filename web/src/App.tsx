import { useCallback, useEffect, useRef, useState } from 'react'
import { ArrowUp, BookOpen, ChevronDown, PanelLeft, Plus, Settings, Trash2 } from 'lucide-react'
import { api, followTurn, type Bootstrap, type ConversationSummary, type Step, type Turn } from './api'
import { TurnView } from './components/TurnView'
import { SettingsModal } from './components/SettingsModal'
import { CatalogDrawer } from './components/CatalogDrawer'

const read = (k: string) => { try { return localStorage.getItem(k) } catch { return null } }
const write = (k: string, v: string) => { try { localStorage.setItem(k, v) } catch { /* private mode */ } }
const iconBtn = 'rounded-lg p-2 text-lead transition-colors hover:bg-wash hover:text-ink'

export default function App() {
  const [boot, setBoot] = useState<Bootstrap | null>(null)
  const [bootError, setBootError] = useState('')
  const [conversations, setConversations] = useState<ConversationSummary[]>([])
  const [activeId, setActiveId] = useState<string | null>(null)
  const [turns, setTurns] = useState<Turn[]>([])
  const [steps, setSteps] = useState<Record<string, Step[]>>({})
  const [input, setInput] = useState('')
  const [model, setModel] = useState<string>(read('texa.model') ?? '')
  const [scope, setScope] = useState<string>(read('texa.scope') ?? '')
  const [settings, setSettings] = useState(false)
  const [catalogOpen, setCatalogOpen] = useState(false)
  const [sidebar, setSidebar] = useState(() => window.innerWidth >= 768)
  const [sending, setSending] = useState(false)
  const [loadingConversation, setLoadingConversation] = useState(false)
  const [sendError, setSendError] = useState('')
  const followers = useRef<Record<string, () => void>>({})
  const conversationRequest = useRef(0)
  const activeIdRef = useRef<string | null>(activeId)
  const sendCount = useRef(0)
  const sendingRef = useRef(false)
  const bootRequest = useRef<Promise<void> | null>(null)
  const bottom = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)

  const loadBoot = useCallback(() => {
    // Establish the browser session before other requests; deduplicate React's
    // development effect replay so competing Set-Cookie responses cannot race.
    if (!bootRequest.current) bootRequest.current = api.bootstrap()
      .then((b) => { setBoot(b); setBootError('') }).catch((e) => setBootError(e.message))
      .finally(() => { bootRequest.current = null })
    return bootRequest.current
  }, [])
  const loadConversations = useCallback(() => api.conversations().then(setConversations).catch(() => {}), [])
  useEffect(() => { loadBoot().then(loadConversations) }, [loadBoot, loadConversations])
  useEffect(() => {
    if (boot && scope && !boot.sources.some((s) => s.id === scope)) { setScope(''); write('texa.scope', '') }
  }, [boot, scope])
  // Focus the question box on desktop only; on phones it would pop the keyboard over the page.
  useEffect(() => { if (window.matchMedia('(pointer: fine)').matches) inputRef.current?.focus() }, [])

  const allowed = boot?.connection?.allowed_models ?? []
  const activeModel = !boot?.read_only_settings && allowed.includes(model) ? model : boot?.connection?.default_model ?? ''

  const follow = useCallback((turnId: string) => {
    followers.current[turnId]?.()
    setSteps((s) => ({ ...s, [turnId]: [] }))
    setTurns((ts) => ts.map((t) => (t.id === turnId ? { ...t, status: 'running' } : t)))
    followers.current[turnId] = followTurn(turnId,
      (step) => setSteps((s) => ({ ...s, [turnId]: [...(s[turnId] ?? []), step] })),
      (turn) => {
        const effective = turn.source_resolution?.effective
        const uiSource = turn.source_resolution?.ui
        if (turn.status === 'answered' && effective?.length === 1 && uiSource?.length === 1 && effective[0] !== uiSource[0]) {
          setScope((current) => {
            if (current !== uiSource[0]) return current
            write('texa.scope', effective[0]); return effective[0]
          })
        }
        setTurns((ts) => ts.map((t) => (t.id === turnId ? turn : t))); delete followers.current[turnId]; loadConversations() })
  }, [loadConversations])

  const openConversation = useCallback(async (id: string | null) => {
    const request = ++conversationRequest.current
    sendCount.current += 1
    sendingRef.current = false
    setSending(false)
    activeIdRef.current = id
    Object.values(followers.current).forEach((stop) => stop())
    followers.current = {}
    setActiveId(id)
    setSteps({})
    setSendError('')
    if (!window.matchMedia('(min-width: 768px)').matches) setSidebar(false)
    setTurns([])
    if (!id) { setLoadingConversation(false); setTimeout(() => inputRef.current?.focus()); return }
    setLoadingConversation(true)
    let conv
    try { conv = await api.conversation(id) }
    catch (e) {
      if (request === conversationRequest.current) { setSendError(`Không tải được hội thoại: ${(e as Error).message}`); setLoadingConversation(false) }
      return
    }
    if (request !== conversationRequest.current) return
    setLoadingConversation(false)
    setTurns(conv.turns)
    conv.turns.filter((t) => t.status === 'running').forEach((t) => follow(t.id))
  }, [follow])

  const send = async (text?: string) => {
    const q = (text ?? input).trim()
    if (!q || sendingRef.current || turns.some((t) => t.status === 'running')) return
    if (!boot?.connection) { setSettings(true); return }
    const targetConversation = activeIdRef.current
    const request = ++sendCount.current
    sendingRef.current = true
    setSending(true)
    setSendError('')
    try {
      const { turn_id, conversation_id } = await api.ask(q, targetConversation, activeModel || null, scope ? [scope] : [])
      if (request !== sendCount.current || targetConversation !== activeIdRef.current) return
      if (!targetConversation) { activeIdRef.current = conversation_id; setActiveId(conversation_id) }
      setTurns((ts) => [...ts, { id: turn_id, conversation_id, question: q, status: 'running', created_at: new Date().toISOString(), model: activeModel, feedback: null }])
      setInput('')
      if (inputRef.current) inputRef.current.style.height = 'auto'
      follow(turn_id)
      loadConversations()
    } catch (e) {
      if (request === sendCount.current && targetConversation === activeIdRef.current) setSendError((e as Error).message)
    } finally {
      if (request === sendCount.current) { sendingRef.current = false; setSending(false) }
      if (targetConversation === activeIdRef.current) inputRef.current?.focus()
    }
  }

  // Rewind: the edited turn reruns with its new question; every later turn is dropped.
  const editTurn = async (turnId: string, question: string) => {
    const conversation = activeIdRef.current
    await api.edit(turnId, question)
    if (conversation !== activeIdRef.current) return
    setTurns((ts) => {
      const i = ts.findIndex((t) => t.id === turnId)
      ts.slice(i + 1).forEach((t) => { followers.current[t.id]?.(); delete followers.current[t.id] })
      return ts.slice(0, i + 1).map((t) => (t.id === turnId ? { ...t, question } : t))
    })
    follow(turnId)
    loadConversations()
  }

  useEffect(() => { bottom.current?.scrollIntoView({ behavior: 'smooth', block: 'end' }) }, [turns.length, steps])
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); openConversation(null) } }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [openConversation])

  const running = turns.some((t) => t.status === 'running')
  const empty = turns.length === 0
  const firstAnswered = turns.find((t) => t.status === 'answered' || t.status === 'discussed')?.id

  const composer = (
    <Composer inputRef={inputRef} value={input} onChange={setInput} onSend={() => send()} busy={sending || running || loadingConversation}
      large={empty} error={sendError}
      tools={allowed.length > 0 && !boot?.read_only_settings && (
        <Picker label="Model" quiet value={activeModel} onChange={(v) => { setModel(v); write('texa.model', v) }}
          options={allowed.map((m) => ({ value: m, label: m }))} />
      )} />
  )

  return (
    <div className="flex h-full">
      {sidebar && (
        <>
          <div className="fixed inset-0 z-10 bg-ink/20 md:hidden" onClick={() => setSidebar(false)} />
          <aside className="fixed inset-y-0 left-0 z-20 flex w-64 flex-col border-r border-rule bg-paper md:static">
            <div className="flex items-center justify-between px-3 pt-3 pb-2">
              <Wordmark />
              <button aria-label="Ẩn thanh bên" onClick={() => setSidebar(false)} className={iconBtn}><PanelLeft className="h-[18px] w-[18px]" /></button>
            </div>
            <div className="px-2">
              <button onClick={() => openConversation(null)}
                className="flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-sm font-medium text-ink transition-colors hover:bg-wash">
                <Plus className="h-4 w-4" /> Cuộc hỏi mới <kbd className="ml-auto font-sans text-xs text-lead">⌘K</kbd></button>
            </div>
            <nav aria-label="Lịch sử" className="scroll-thin mt-4 flex-1 overflow-y-auto px-2 pb-3 text-sm">
              {conversations.length > 0 && <p className="px-2.5 pb-1.5 text-xs text-lead">Gần đây</p>}
              {conversations.map((c) => (
                <div key={c.id} className={`group flex items-center rounded-lg transition-colors ${c.id === activeId ? 'bg-wash text-ink' : 'text-ink/80 hover:bg-wash/70'}`}>
                  <button onClick={() => openConversation(c.id)} className="flex-1 truncate px-2.5 py-1.5 text-left" title={c.title}>{c.title}</button>
                  <button aria-label={`Xóa “${c.title}”`} className="mr-1 rounded p-1 text-lead opacity-0 transition-opacity hover:text-rose-600 focus:opacity-100 group-hover:opacity-100"
                    onClick={async () => { if (confirm('Xóa cuộc hỏi này?')) { await api.deleteConversation(c.id); if (c.id === activeId) openConversation(null); loadConversations() } }}>
                    <Trash2 className="h-3.5 w-3.5" /></button>
                </div>
              ))}
            </nav>
            <div className="border-t border-rule p-2">
              <button onClick={() => setCatalogOpen(true)} className="flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-sm text-ink/80 transition-colors hover:bg-wash">
                <BookOpen className="h-4 w-4 text-lead" /> Texa đo được gì</button>
              <button onClick={() => setSettings(true)} className="flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-sm text-ink/80 transition-colors hover:bg-wash">
                <Settings className="h-4 w-4 text-lead" /> Cài đặt model</button>
            </div>
          </aside>
        </>
      )}

      <main className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center gap-1 px-3 py-2.5">
          {!sidebar && <>
            <button aria-label="Hiện thanh bên" onClick={() => setSidebar(true)} className={iconBtn}><PanelLeft className="h-[18px] w-[18px]" /></button>
            <button aria-label="Cuộc hỏi mới" onClick={() => openConversation(null)} className={iconBtn}><Plus className="h-[18px] w-[18px]" /></button>
          </>}
          <Picker label="Nguồn dữ liệu" value={scope} onChange={(v) => { setScope(v); write('texa.scope', v) }}
            options={[{ value: '', label: 'Mọi nguồn' }, ...(boot?.sources ?? []).map((s) => ({ value: s.id, label: s.label }))]} />
        </header>

        {boot && !boot.connection && (
          <div className="mx-auto mt-1 flex w-[min(42rem,calc(100%-2rem))] items-center gap-3 rounded-xl border border-rule bg-sheet px-4 py-3 text-sm">
            <span className="flex-1">Kết nối một model để bắt đầu hỏi.</span>
            <button onClick={() => setSettings(true)} className="rounded-lg bg-ledger px-3 py-1.5 font-medium text-white transition-opacity hover:opacity-90 dark:text-paper">Kết nối model</button>
          </div>
        )}
        {bootError && (
          <p role="alert" className="mx-auto mt-1 w-[min(42rem,calc(100%-2rem))] rounded-xl bg-rose-50 px-4 py-3 text-sm text-rose-800 dark:bg-rose-950/40 dark:text-rose-200">
            Không gọi được API ({bootError}). Kiểm tra backend đang chạy ở cổng 18000.</p>
        )}

        {empty ? (
          <div className="flex flex-1 flex-col items-center justify-center px-4 pb-[12vh]">
            {boot && <EmptyState scope={scope} boot={boot} onAsk={send} composer={composer} />}
          </div>
        ) : (
          <>
            <div className="scroll-thin flex-1 overflow-y-auto">
              <div className="mx-auto max-w-[44rem] space-y-10 px-4 pt-6 pb-10">
                {turns.map((t) => <TurnView key={t.id} turn={t} steps={steps[t.id] ?? []} boot={boot!} onAsk={send} onRefresh={follow} onEdit={editTurn} busy={running} explainMarks={t.id === firstAnswered} />)}
                <div ref={bottom} />
              </div>
            </div>
            <div className="px-4 pb-4">{composer}</div>
          </>
        )}
      </main>

      {settings && boot && <SettingsModal boot={boot} onClose={() => setSettings(false)} onSaved={() => { setSettings(false); loadBoot() }} />}
      {catalogOpen && boot && <CatalogDrawer boot={boot} onClose={() => setCatalogOpen(false)} onInsert={(t) => { setInput((i) => (i ? `${i} ${t}` : t)); setCatalogOpen(false); inputRef.current?.focus() }} />}
    </div>
  )
}

function Wordmark() {
  return (
    <span className="flex items-center gap-2 px-1.5 text-[17px] font-semibold tracking-tight">
      <span aria-hidden className="relative inline-flex h-6 w-6 items-center justify-center">
        <span className="absolute inset-x-0 bottom-0.5 h-2.5 rounded-sm bg-mark" />
        <span className="relative font-serif text-[19px] leading-none text-ledger-ink">T</span>
      </span>
      Texa
    </span>
  )
}

function Picker({ label, value, options, onChange, quiet }: {
  label: string; value: string; options: { value: string; label: string }[]; onChange: (v: string) => void; quiet?: boolean
}) {
  return (
    <label className={`relative inline-flex items-center rounded-lg text-sm transition-colors hover:bg-wash ${quiet ? 'text-lead hover:text-ink' : 'text-ink'}`}>
      <span className="sr-only">{label}</span>
      <select value={value} onChange={(e) => onChange(e.target.value)}
        className={`field-sizing-content max-w-[42vw] cursor-pointer appearance-none truncate bg-transparent py-1.5 pr-7 pl-2.5 outline-none ${quiet ? '' : 'font-medium'}`}>
        {options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
      </select>
      <ChevronDown className="pointer-events-none absolute right-2 h-3.5 w-3.5 opacity-70" />
    </label>
  )
}

function Composer({ inputRef, value, onChange, onSend, busy, large, error, tools }: {
  inputRef: React.RefObject<HTMLTextAreaElement | null>; value: string; onChange: (v: string) => void; onSend: () => void
  busy: boolean; large: boolean; error: string; tools?: React.ReactNode
}) {
  const ready = value.trim() && !busy
  return (
    <div className="mx-auto w-full max-w-[44rem]">
      <div onClick={(e) => { if (e.target === e.currentTarget) inputRef.current?.focus() }}
        className={`flex cursor-text flex-col rounded-[22px] border border-rule bg-sheet p-2 pl-4 shadow-[0_1px_2px_rgba(22,24,29,.04),0_8px_24px_-12px_rgba(22,24,29,.12)] transition-colors focus-within:border-ledger/50 ${large ? 'min-h-[7.5rem]' : ''}`}>
        <textarea ref={inputRef} value={value} rows={1} maxLength={2000}
          onChange={(e) => { onChange(e.target.value); e.target.style.height = 'auto'; e.target.style.height = `${Math.min(e.target.scrollHeight, 200)}px` }}
          onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); onSend() } }}
          placeholder={large ? "Hỏi về doanh thu, đơn hàng, khách hàng…" : "Hỏi tiếp…"}
          aria-label="Câu hỏi" className="max-h-[200px] flex-1 resize-none bg-transparent py-2 pr-2 text-[15px] leading-relaxed outline-none placeholder:text-lead/80" />
        <div className="flex items-center justify-end gap-1">
          {tools}
          <button aria-label="Gửi câu hỏi" disabled={!ready} onClick={onSend}
            className="rounded-full bg-ledger p-2 text-white transition-[opacity,transform] enabled:hover:opacity-90 enabled:active:scale-95 disabled:bg-rule disabled:text-lead dark:text-paper">
            <ArrowUp className="h-[18px] w-[18px]" strokeWidth={2.25} /></button>
        </div>
      </div>
      {error && <p role="alert" className="mt-2 px-4 text-sm text-rose-700 dark:text-rose-300">{error}</p>}
    </div>
  )
}

function EmptyState({ boot, onAsk, composer, scope }: { scope: string; boot: Bootstrap; onAsk: (q: string) => void; composer: React.ReactNode }) {
  const examples = (boot.catalog.suggestions ?? []).filter((s) => !scope || s.source_id === scope).slice(0, 4).map((s) => s.question)
  return (
    <div className="w-full max-w-[44rem]">
      <h1 className="mb-7 text-center font-serif text-[2rem] leading-tight tracking-[-0.01em] text-ink sm:text-[2.4rem]">Hôm nay bạn muốn đo gì?</h1>
      {composer}
      <ul className="mt-4 flex flex-wrap justify-center gap-2">
        {examples.map((q) => (
          <li key={q}>
            <button onClick={() => onAsk(q)}
              className="rounded-full border border-rule px-3.5 py-1.5 text-sm text-ink/80 transition-colors hover:border-ledger/40 hover:bg-sheet hover:text-ink">{q}</button>
          </li>
        ))}
      </ul>
      {boot.sources.length > 0 && (
        <p className="mt-8 text-center text-sm text-lead">
          Đang có dữ liệu của {boot.sources.map((s, i) => (
            <span key={s.id}>{i > 0 && (i === boot.sources.length - 1 ? ' và ' : ', ')}<span className="text-ink/80" title={`${s.min_date} – ${s.max_date}`}>{s.label}</span></span>
          ))}.
        </p>
      )}
    </div>
  )
}
