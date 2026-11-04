import { useState } from 'react'
import { Loader2, X } from 'lucide-react'
import { api, type Bootstrap } from '../api'

const KEY_HINT: Record<string, string> = { gemini: 'AIza…', anthropic: 'sk-ant-…', openai: 'sk-…' }
const BASE_URL_HINT: Record<string, string> = {
  gemini: 'https://generativelanguage.googleapis.com',
  anthropic: 'https://api.anthropic.com',
  openai: 'https://api.openai.com/v1  ·  vd. https://litellm.congty.vn/v1',
}

export function SettingsModal({ boot, onClose, onSaved }: { boot: Bootstrap; onClose: () => void; onSaved: () => void }) {
  const conn = boot.connection
  const [provider, setProvider] = useState(conn?.provider ?? 'gemini')
  const [apiKey, setApiKey] = useState('')
  const [baseUrl, setBaseUrl] = useState(conn?.base_url ?? '')
  const [models, setModels] = useState<{ id: string; label: string }[]>((conn?.allowed_models ?? []).map((id) => ({ id, label: id })))
  const [allowed, setAllowed] = useState<string[]>(conn?.allowed_models ?? [])
  const [defaultModel, setDefaultModel] = useState(conn?.default_model ?? '')
  const [maxOut, setMaxOut] = useState(conn?.max_output_tokens ?? 8192)
  const [daily, setDaily] = useState(conn?.daily_token_limit ?? 0)
  const [lang, setLang] = useState(conn?.answer_language ?? 'auto')
  const [busy, setBusy] = useState<'' | 'discover' | 'save'>('')
  const [error, setError] = useState('')
  const savedKey = !!conn?.has_key && !conn.from_env && conn.provider === provider
  const hint = KEY_HINT[provider] ?? ''

  const discover = async () => {
    setBusy('discover'); setError('')
    try {
      const { models } = await api.discover(provider, apiKey, baseUrl)
      setModels(models)
      if (!allowed.length) {
        const pick = models.slice(0, 4).map((m) => m.id)
        setAllowed(pick)
        setDefaultModel(pick[0] ?? '')
      }
    } catch (e) { setError((e as Error).message) } finally { setBusy('') }
  }
  const save = async () => {
    setBusy('save'); setError('')
    try {
      await api.saveConnection({ provider, api_key: apiKey || undefined, base_url: baseUrl.trim() || null, allowed_models: allowed, default_model: defaultModel || null,
        max_output_tokens: maxOut, daily_token_limit: daily, answer_language: lang })
      onSaved()
    } catch (e) { setError((e as Error).message) } finally { setBusy('') }
  }
  const toggle = (id: string) => {
    const next = allowed.includes(id) ? allowed.filter((m) => m !== id) : [...allowed, id]
    setAllowed(next)
    if (!next.includes(defaultModel)) setDefaultModel(next[0] ?? '')
  }

  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center bg-ink/25 p-4 backdrop-blur-[2px]" onClick={onClose}>
      <div role="dialog" aria-modal="true" aria-label="Cài đặt" onClick={(e) => e.stopPropagation()}
        className="scroll-thin max-h-[90vh] w-full max-w-lg overflow-y-auto rounded-3xl border border-rule bg-paper p-7 shadow-2xl">
        <div className="mb-5 flex items-center justify-between">
          <h2 className="font-serif text-2xl">{boot.read_only_settings ? 'Model của buổi demo' : 'Kết nối model'}</h2>
          <button aria-label="Đóng" onClick={onClose} className="rounded-lg p-1.5 text-lead transition-colors hover:bg-wash hover:text-ink"><X className="h-5 w-5" /></button>
        </div>
        {boot.read_only_settings ? (
          <div className="space-y-4 text-sm">
            {conn?.default_model ? (
              <p>Buổi demo đang dùng model <span className="font-medium text-ink">{conn.default_model}</span>.</p>
            ) : (
              <p>Buổi demo chưa được cấu hình model.</p>
            )}
            <p className="text-lead">Cài đặt model do người tổ chức quản lý. Nếu không gửi được câu hỏi, hãy liên hệ người cung cấp đường dẫn demo.</p>
            <div className="flex justify-end pt-2"><button onClick={onClose} className="rounded-full bg-ledger px-4 py-2 font-medium text-white dark:text-paper">Đóng</button></div>
          </div>
        ) : <div className="space-y-5 text-sm">
          <label className="block space-y-1.5">
            <span className="font-medium text-ink">Provider</span>
            <select value={provider} onChange={(e) => { setProvider(e.target.value); setModels([]); setAllowed([]); setDefaultModel('') }} className="w-full rounded-xl border border-rule bg-sheet px-3 py-2 outline-none focus:border-ledger/50">
              {boot.providers.map((p) => <option key={p.id} value={p.id}>{p.label}</option>)}
            </select>
          </label>
          <label className="block space-y-1.5">
            <span className="font-medium text-ink">API key</span>
            <input type="password" value={apiKey} onChange={(e) => setApiKey(e.target.value)} autoComplete="off"
              placeholder={savedKey ? 'Đã lưu an toàn – nhập key mới để thay' : conn?.from_env && conn.provider === provider ? 'Đang dùng key từ biến môi trường' : hint}
              className="w-full rounded-xl border border-rule bg-sheet px-3 py-2 outline-none focus:border-ledger/50" />
            <span className="text-xs text-lead">Key được mã hóa trước khi lưu và không bao giờ gửi lại trình duyệt.</span>
          </label>
          <label className="block space-y-1.5">
            <span className="font-medium text-ink">Base URL <span className="font-normal text-lead">(tùy chọn)</span></span>
            <input type="url" value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} autoComplete="off"
              placeholder={BASE_URL_HINT[provider] ?? ''}
              className="w-full rounded-xl border border-rule bg-sheet px-3 py-2 outline-none focus:border-ledger/50" />
            <span className="text-xs text-lead">Chỉ điền khi đi qua gateway của tổ chức.</span>
          </label>
          <button onClick={discover} disabled={busy !== '' || (!apiKey && !conn)}
            className="inline-flex items-center gap-2 rounded-full border border-rule bg-sheet px-3.5 py-1.5 transition-colors hover:border-ledger/40 disabled:opacity-40">
            {busy === 'discover' && <Loader2 className="h-4 w-4 animate-spin" />} Kiểm tra key và tải danh sách model</button>

          {models.length > 0 && (
            <div className="space-y-1.5">
              <span className="font-medium text-ink">Model được phép dùng</span>
              <div className="scroll-thin max-h-48 space-y-1 overflow-y-auto rounded-xl border border-rule bg-sheet p-2">
                {models.map((m) => (
                  <label key={m.id} className="flex items-center gap-2 rounded-lg px-1.5 py-1 hover:bg-wash">
                    <input type="checkbox" className="accent-[var(--color-ledger)]" checked={allowed.includes(m.id)} onChange={() => toggle(m.id)} />
                    <span>{m.label}</span>{m.label !== m.id && <span className="text-xs text-lead">{m.id}</span>}
                  </label>
                ))}
              </div>
            </div>
          )}
          <label className="block space-y-1.5">
            <span className="font-medium text-ink">Model mặc định</span>
            <select value={defaultModel} onChange={(e) => setDefaultModel(e.target.value)} className="w-full rounded-xl border border-rule bg-sheet px-3 py-2 outline-none focus:border-ledger/50">
              <option value="">—</option>
              {allowed.map((m) => <option key={m} value={m}>{m}</option>)}
            </select>
          </label>
          <div className="grid grid-cols-2 gap-3">
            <label className="block space-y-1.5">
              <span className="font-medium text-ink">Token output tối đa / lần gọi</span>
              <input type="number" min={256} max={65536} value={maxOut} onChange={(e) => setMaxOut(+e.target.value)}
                className="w-full rounded-xl border border-rule bg-sheet px-3 py-2 outline-none focus:border-ledger/50" />
            </label>
            <label className="block space-y-1.5">
              <span className="font-medium text-ink">Token / ngày (0 = không giới hạn)</span>
              <input type="number" min={0} value={daily} onChange={(e) => setDaily(+e.target.value)}
                className="w-full rounded-xl border border-rule bg-sheet px-3 py-2 outline-none focus:border-ledger/50" />
            </label>
          </div>
          <label className="block space-y-1.5">
            <span className="font-medium text-ink">Ngôn ngữ trả lời</span>
            <select value={lang} onChange={(e) => setLang(e.target.value)} className="w-full rounded-xl border border-rule bg-sheet px-3 py-2 outline-none focus:border-ledger/50">
              <option value="auto">Theo ngôn ngữ câu hỏi</option><option value="vi">Tiếng Việt</option><option value="en">English</option>
            </select>
          </label>
          {error && <p className="rounded-xl bg-rose-50 px-3 py-2 text-rose-800 dark:bg-rose-950/40 dark:text-rose-200">{error}</p>}
          <div className="flex justify-end gap-2 pt-2">
            {savedKey && <button onClick={() => api.deleteConnection().then(onSaved)} className="mr-auto rounded-full px-3 py-2 text-rose-700 transition-colors hover:bg-rose-50 dark:text-rose-300 dark:hover:bg-rose-950/40">Ngắt kết nối</button>}
            <button onClick={onClose} className="rounded-full px-4 py-2 transition-colors hover:bg-wash">Hủy</button>
            <button onClick={save} disabled={busy !== '' || (!apiKey && !savedKey) || !defaultModel}
              className="inline-flex items-center gap-2 rounded-full bg-ledger px-4 py-2 font-medium text-white transition-opacity hover:opacity-90 disabled:opacity-40 dark:text-paper">
              {busy === 'save' && <Loader2 className="h-4 w-4 animate-spin" />} Lưu kết nối</button>
          </div>
        </div>}
      </div>
    </div>
  )
}
