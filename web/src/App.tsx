import { useCallback, useEffect, useRef, useState } from 'react'
import { BookOpen, Database, Menu, MessageSquarePlus, SendHorizontal, Settings, Trash2 } from 'lucide-react'
import { api, followTurn, type Bootstrap, type ConversationSummary, type Step, type Turn } from './api'
import { TurnView } from './components/TurnView'
import { SettingsModal } from './components/SettingsModal'
import { CatalogDrawer } from './components/CatalogDrawer'

const read = (k: string) => { try { return localStorage.getItem(k) } catch { return null } }
const write = (k: string, v: string) => { try { localStorage.setItem(k, v) } catch { /* private mode */ } }

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
  const followers = useRef<Record<string, () => void>>({})
  const bottom = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)

  const loadBoot = useCallback(() => api.bootstrap().then((b) => { setBoot(b); setBootError('') }).catch((e) => setBootError(e.message)), [])
  const loadConversations = useCallback(() => api.conversations().then(setConversations).catch(() => {}), [])
  useEffect(() => { loadBoot(); loadConversations() }, [loadBoot, loadConversations])

  const allowed = boot?.connection?.allowed_models ?? []
  const activeModel = allowed.includes(model) ? model : boot?.connection?.default_model ?? ''

  const follow = useCallback((turnId: string) => {
    followers.current[turnId]?.()
    setSteps((s) => ({ ...s, [turnId]: [] }))
    setTurns((ts) => ts.map((t) => (t.id === turnId ? { ...t, status: 'running' } : t)))
    followers.current[turnId] = followTurn(turnId,
      (step) => setSteps((s) => ({ ...s, [turnId]: [...(s[turnId] ?? []), step] })),
      (turn) => { setTurns((ts) => ts.map((t) => (t.id === turnId ? turn : t))); loadConversations() })
  }, [loadConversations])

  const openConversation = useCallback(async (id: string | null) => {
    Object.values(followers.current).forEach((stop) => stop())
    followers.current = {}
    setActiveId(id)
    setSteps({})
    if (!window.matchMedia('(min-width: 768px)').matches) setSidebar(false)
    if (!id) { setTurns([]); return }
    const conv = await api.conversation(id)
    setTurns(conv.turns)
    conv.turns.filter((t) => t.status === 'running').forEach((t) => follow(t.id))
  }, [follow])

  const send = async (text?: string) => {
    const q = (text ?? input).trim()
    if (!q || sending) return
    if (!boot?.connection) { setSettings(true); return }
    setSending(true)
    try {
      const { turn_id, conversation_id } = await api.ask(q, activeId, activeModel || null, scope ? [scope] : [])
      if (!activeId) setActiveId(conversation_id)
      setTurns((ts) => [...ts, { id: turn_id, conversation_id, question: q, status: 'running', created_at: new Date().toISOString(), model: activeModel, feedback: null }])
      setInput('')
      follow(turn_id)
      loadConversations()
    } catch (e) {
      alert((e as Error).message)
    } finally {
      setSending(false)
      inputRef.current?.focus()
    }
  }

  useEffect(() => { bottom.current?.scrollIntoView({ behavior: 'smooth', block: 'end' }) }, [turns.length, steps])
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); openConversation(null) } }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [openConversation])

  const running = turns.some((t) => t.status === 'running')

  return (
    <div className="flex h-full">
      {sidebar && (
        <>
          <div className="fixed inset-0 z-10 bg-black/30 md:hidden" onClick={() => setSidebar(false)} />
          <aside className="fixed inset-y-0 left-0 z-20 flex w-72 flex-col border-r border-slate-200 bg-slate-50 md:static dark:border-slate-800 dark:bg-slate-900">
            <div className="flex items-center gap-2 p-4">
              <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-gradient-to-br from-indigo-500 to-fuchsia-500 font-bold text-white">T</div>
              <span className="text-lg font-semibold">Texa</span>
            </div>
            <div className="px-3">
              <button onClick={() => openConversation(null)} className="flex w-full items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm hover:border-indigo-400 dark:border-slate-700 dark:bg-slate-950">
                <MessageSquarePlus className="h-4 w-4" /> Chat mới <kbd className="ml-auto text-xs text-slate-400">⌘K</kbd></button>
            </div>
            <nav className="scroll-thin mt-3 flex-1 space-y-0.5 overflow-y-auto px-3 pb-3 text-sm">
              {conversations.length === 0 && <p className="px-2 py-4 text-slate-400">Chưa có hội thoại.</p>}
              {conversations.map((c) => (
                <div key={c.id} className={`group flex items-center rounded-lg ${c.id === activeId ? 'bg-indigo-50 text-indigo-800 dark:bg-indigo-950/60 dark:text-indigo-200' : 'hover:bg-slate-100 dark:hover:bg-slate-800'}`}>
                  <button onClick={() => openConversation(c.id)} className="flex-1 truncate px-2 py-2 text-left" title={c.title}>{c.title}</button>
                  <button aria-label="Xóa hội thoại" className="mr-1 hidden rounded p-1 text-slate-400 hover:text-rose-600 group-hover:block"
                    onClick={async () => { if (confirm('Xóa hội thoại này?')) { await api.deleteConversation(c.id); if (c.id === activeId) openConversation(null); loadConversations() } }}>
                    <Trash2 className="h-3.5 w-3.5" /></button>
                </div>
              ))}
            </nav>
          </aside>
        </>
      )}

      <main className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center gap-2 border-b border-slate-200 px-3 py-2 dark:border-slate-800">
          <button aria-label="Mở danh sách hội thoại" onClick={() => setSidebar(!sidebar)} className="rounded-lg p-2 hover:bg-slate-100 dark:hover:bg-slate-800"><Menu className="h-5 w-5" /></button>
          <label className="flex items-center gap-1.5 text-sm">
            <Database className="h-4 w-4 text-slate-400" />
            <select aria-label="Nguồn dữ liệu" value={scope} onChange={(e) => { setScope(e.target.value); write('texa.scope', e.target.value) }}
              className="rounded-lg border border-slate-200 bg-transparent px-2 py-1 dark:border-slate-700">
              <option value="">Tất cả nguồn</option>
              {boot?.sources.map((s) => <option key={s.id} value={s.id}>{s.label}</option>)}
            </select>
          </label>
          <span className="flex-1" />
          {allowed.length > 0 && (
            <select aria-label="Model" value={activeModel} onChange={(e) => { setModel(e.target.value); write('texa.model', e.target.value) }}
              className="max-w-[45vw] truncate rounded-lg border border-slate-200 bg-transparent px-2 py-1 text-sm dark:border-slate-700">
              {allowed.map((m) => <option key={m} value={m}>{boot?.providers.find((p) => p.id === boot.connection?.provider)?.label.split(' (')[0] ?? ''} · {m}</option>)}
            </select>
          )}
          <button aria-label="Texa biết gì" title="Texa biết gì" onClick={() => setCatalogOpen(true)} className="rounded-lg p-2 hover:bg-slate-100 dark:hover:bg-slate-800"><BookOpen className="h-5 w-5" /></button>
          <button aria-label="Cài đặt" title="Cài đặt" onClick={() => setSettings(true)} className="rounded-lg p-2 hover:bg-slate-100 dark:hover:bg-slate-800"><Settings className="h-5 w-5" /></button>
        </header>

        {boot && !boot.connection && (
          <div className="flex items-center justify-center gap-3 bg-indigo-50 px-4 py-2 text-sm text-indigo-900 dark:bg-indigo-950/50 dark:text-indigo-200">
            Kết nối một model (Gemini, Claude, OpenAI hoặc gateway) để bắt đầu.
            <button onClick={() => setSettings(true)} className="rounded-md bg-indigo-600 px-3 py-1 font-medium text-white hover:bg-indigo-700">Mở Cài đặt</button>
          </div>
        )}
        {bootError && <div className="bg-rose-50 px-4 py-2 text-center text-sm text-rose-700 dark:bg-rose-950/50 dark:text-rose-300">Không kết nối được API: {bootError}</div>}

        <div className="scroll-thin flex-1 overflow-y-auto">
          <div className="mx-auto max-w-3xl space-y-8 px-4 py-6">
            {turns.length === 0 && boot && <EmptyState boot={boot} onAsk={send} />}
            {turns.map((t) => <TurnView key={t.id} turn={t} steps={steps[t.id] ?? []} boot={boot!} onAsk={send} onRefresh={follow} />)}
            <div ref={bottom} />
          </div>
        </div>

        <div className="px-4 pb-4">
          <div className="mx-auto flex max-w-3xl items-end gap-2 rounded-2xl border border-slate-300 bg-white p-2 shadow-sm focus-within:border-indigo-500 dark:border-slate-700 dark:bg-slate-900">
            <textarea ref={inputRef} value={input} rows={1} maxLength={2000}
              onChange={(e) => { setInput(e.target.value); e.target.style.height = 'auto'; e.target.style.height = `${Math.min(e.target.scrollHeight, 192)}px` }}
              onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); send() } }}
              placeholder="Hỏi Texa về dữ liệu… (vd: doanh thu theo danh mục tháng 12/2019)"
              aria-label="Câu hỏi" className="max-h-48 flex-1 resize-none bg-transparent px-2 py-2 outline-none" />
            <button aria-label="Gửi" disabled={!input.trim() || sending || running} onClick={() => send()}
              className="rounded-xl bg-indigo-600 p-2.5 text-white hover:bg-indigo-700 disabled:opacity-30"><SendHorizontal className="h-4 w-4" /></button>
          </div>
          <p className="mx-auto mt-1.5 max-w-3xl text-center text-xs text-slate-400">Texa chỉ tính các chỉ số đã định nghĩa trong catalog; mọi con số đến từ SQL, không do AI tự viết.</p>
        </div>
      </main>

      {settings && boot && <SettingsModal boot={boot} onClose={() => setSettings(false)} onSaved={() => { setSettings(false); loadBoot() }} />}
      {catalogOpen && boot && <CatalogDrawer boot={boot} onClose={() => setCatalogOpen(false)} onInsert={(t) => { setInput((i) => (i ? `${i} ${t}` : t)); setCatalogOpen(false); inputRef.current?.focus() }} />}
    </div>
  )
}

function EmptyState({ boot, onAsk }: { boot: Bootstrap; onAsk: (q: string) => void }) {
  const examples = [
    'Doanh thu theo danh mục sản phẩm tháng 12/2019 của cosmetics shop',
    'Tỉ lệ giao hàng trễ theo bang của Olist năm 2018',
    'Phễu xem → giỏ → mua theo tuần trong 30 ngày gần nhất',
    'So sánh AOV giữa 2 cửa hàng',
    ...(boot.catalog.examples ?? []).slice(0, 2),
  ]
  const fmt = new Intl.NumberFormat('vi-VN')
  return (
    <div className="space-y-8 pt-8">
      <div className="text-center">
        <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-2xl bg-gradient-to-br from-indigo-500 to-fuchsia-500 text-xl font-bold text-white">T</div>
        <h1 className="text-2xl font-semibold">Xin chào, mình là Texa</h1>
        <p className="mt-1 text-slate-500">Hỏi bằng ngôn ngữ tự nhiên — Texa dựng SQL từ semantic catalog, chạy trên dữ liệu thật và tóm tắt insight.</p>
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        {boot.sources.map((s) => (
          <div key={s.id} className="rounded-xl border border-slate-200 p-4 dark:border-slate-800">
            <div className="flex items-center justify-between"><span className="font-medium">{s.label}</span><span className="text-xs text-slate-400">{s.currency}</span></div>
            <p className="mt-1 line-clamp-2 text-sm text-slate-500">{s.description}</p>
            <p className="mt-2 text-xs text-slate-400">{s.min_date} → {s.max_date} · {fmt.format(s.row_count)} sự kiện · {fmt.format(s.user_count)} người dùng</p>
          </div>
        ))}
      </div>
      <div className="flex flex-wrap justify-center gap-2">
        {examples.map((q) => (
          <button key={q} onClick={() => onAsk(q)} className="rounded-full border border-slate-200 px-3 py-1.5 text-sm text-slate-700 hover:border-indigo-400 hover:text-indigo-700 dark:border-slate-700 dark:text-slate-300 dark:hover:text-indigo-300">{q}</button>
        ))}
      </div>
    </div>
  )
}
