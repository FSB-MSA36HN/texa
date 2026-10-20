import { useEffect, useState } from 'react'
import { Search, X } from 'lucide-react'
import type { Bootstrap, CatalogEntry } from '../api'

export function CatalogDrawer({ boot, onClose, onInsert }: { boot: Bootstrap; onClose: () => void; onInsert: (text: string) => void }) {
  const [q, setQ] = useState('')
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])
  const match = (e: CatalogEntry) => !q || [e.id, e.label, e.description, ...e.synonyms].join(' ').toLowerCase().includes(q.toLowerCase())
  const section = (title: string, items: CatalogEntry[] = []) => {
    const shown = items.filter(match)
    if (!shown.length) return null
    return (
      <section>
        <h3 className="mb-1 px-2 text-sm font-medium text-lead">{title}</h3>
        <ul>
          {shown.map((e) => (
            <li key={e.id}>
              <button onClick={() => onInsert(e.label)} className="w-full rounded-lg px-2 py-2 text-left transition-colors hover:bg-wash">
                <span className="font-medium text-ink">{e.label}</span>
                {e.description && <span className="mt-0.5 block text-[13px] leading-snug text-lead">{e.description}</span>}
              </button>
            </li>
          ))}
        </ul>
      </section>
    )
  }
  const sections = [section('Chỉ số đo được', boot.catalog.metrics), section('Chia nhỏ hoặc lọc theo', boot.catalog.dimensions)]
  return (
    <div className="fixed inset-0 z-30 flex justify-end bg-ink/20" onClick={onClose}>
      <aside onClick={(e) => e.stopPropagation()} role="dialog" aria-modal="true" aria-label="Texa đo được gì"
        className="flex h-full w-full max-w-sm flex-col border-l border-rule bg-paper shadow-2xl">
        <div className="flex items-center justify-between px-5 pt-5 pb-3">
          <div>
            <h2 className="font-serif text-xl">Texa đo được gì</h2>
            <p className="text-sm text-lead">Bấm một mục để thêm vào câu hỏi.</p>
          </div>
          <button aria-label="Đóng" onClick={onClose} className="rounded-lg p-1.5 text-lead transition-colors hover:bg-wash hover:text-ink"><X className="h-5 w-5" /></button>
        </div>
        <div className="px-5 pb-3">
          <label className="flex items-center gap-2 rounded-xl border border-rule bg-sheet px-3 focus-within:border-ledger/50">
            <Search className="h-4 w-4 text-lead" />
            <input autoFocus value={q} onChange={(e) => setQ(e.target.value)} placeholder="Tìm doanh thu, danh mục…" aria-label="Tìm trong danh mục"
              className="flex-1 bg-transparent py-2 text-sm outline-none" />
          </label>
        </div>
        <div className="scroll-thin flex-1 space-y-5 overflow-y-auto px-3 pb-5 text-sm">
          {sections}
          {sections.every((s) => !s) && <p className="px-2 text-lead">Không có mục nào khớp “{q}”.</p>}
        </div>
      </aside>
    </div>
  )
}
