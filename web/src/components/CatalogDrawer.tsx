import { useState } from 'react'
import { X } from 'lucide-react'
import type { Bootstrap, CatalogEntry } from '../api'

export function CatalogDrawer({ boot, onClose, onInsert }: { boot: Bootstrap; onClose: () => void; onInsert: (text: string) => void }) {
  const [q, setQ] = useState('')
  const match = (e: CatalogEntry) => !q || [e.id, e.label, e.description, ...e.synonyms].join(' ').toLowerCase().includes(q.toLowerCase())
  const section = (title: string, items: CatalogEntry[] = []) => (
    <section>
      <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">{title} ({items.filter(match).length})</h3>
      <ul className="space-y-1">
        {items.filter(match).map((e) => (
          <li key={e.id}>
            <button onClick={() => onInsert(e.label)} className="w-full rounded-lg px-2 py-1.5 text-left hover:bg-slate-100 dark:hover:bg-slate-800">
              <span className="font-medium">{e.label}</span>
              {e.description && <span className="block text-xs text-slate-500">{e.description}</span>}
            </button>
          </li>
        ))}
      </ul>
    </section>
  )
  return (
    <div className="fixed inset-0 z-30 flex justify-end bg-black/30" onClick={onClose}>
      <aside onClick={(e) => e.stopPropagation()} aria-label="Texa biết gì"
        className="flex h-full w-full max-w-sm flex-col bg-white shadow-xl dark:bg-slate-900">
        <div className="flex items-center justify-between border-b border-slate-200 p-4 dark:border-slate-800">
          <h2 className="font-semibold">Texa biết gì</h2>
          <button aria-label="Đóng" onClick={onClose} className="rounded p-1 hover:bg-slate-100 dark:hover:bg-slate-800"><X className="h-5 w-5" /></button>
        </div>
        <div className="p-4 pb-2">
          <input autoFocus value={q} onChange={(e) => setQ(e.target.value)} placeholder="Tìm chỉ số, chiều dữ liệu…"
            className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-950" />
        </div>
        <div className="scroll-thin flex-1 space-y-5 overflow-y-auto p-4 pt-2 text-sm">
          {section('Chỉ số', boot.catalog.metrics)}
          {section('Chia theo / lọc theo', boot.catalog.dimensions)}
        </div>
      </aside>
    </div>
  )
}
