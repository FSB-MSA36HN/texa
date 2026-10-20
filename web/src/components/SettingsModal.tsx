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
    <div className="fixed inset-0 z-40 flex items-center justify-center bg-black/40 p-4" onClick={onClose}>
      <div role="dialog" aria-modal="true" aria-label="Cài đặt" onClick={(e) => e.stopPropagation()}
        className="scroll-thin max-h-[90vh] w-full max-w-lg overflow-y-auto rounded-2xl bg-white p-6 shadow-xl dark:bg-slate-900">
        <div className="mb-5 flex items-center justify-between">
          <h2 className="text-lg font-semibold">Cài đặt model</h2>
          <button aria-label="Đóng" onClick={onClose} className="rounded p-1 hover:bg-slate-100 dark:hover:bg-slate-800"><X className="h-5 w-5" /></button>
        </div>
        <div className="space-y-5 text-sm">
          <label className="block space-y-1.5">
            <span className="font-medium">Provider</span>
            <select value={provider} onChange={(e) => { setProvider(e.target.value); setModels([]); setAllowed([]); setDefaultModel('') }} className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 dark:border-slate-700 dark:bg-slate-950">
              {boot.providers.map((p) => <option key={p.id} value={p.id}>{p.label}</option>)}
            </select>
          </label>
          <label className="block space-y-1.5">
            <span className="font-medium">API key</span>
            <input type="password" value={apiKey} onChange={(e) => setApiKey(e.target.value)} autoComplete="off"
              placeholder={savedKey ? 'Đã lưu an toàn – nhập key mới để thay' : conn?.from_env && conn.provider === provider ? 'Đang dùng key từ biến môi trường' : hint}
              className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 dark:border-slate-700 dark:bg-slate-950" />
            <span className="text-xs text-slate-500">Key được mã hóa trước khi lưu và không bao giờ gửi lại trình duyệt.</span>
          </label>
          <label className="block space-y-1.5">
            <span className="font-medium">Base URL <span className="font-normal text-slate-400">(tùy chọn)</span></span>
            <input type="url" value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} autoComplete="off"
              placeholder={BASE_URL_HINT[provider] ?? ''}
              className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 dark:border-slate-700 dark:bg-slate-950" />
            <span className="text-xs text-slate-500">Để trống để gọi thẳng provider. Điền URL gateway của tổ chức (LiteLLM, OpenRouter, Azure, proxy nội bộ…) nếu gateway dùng chung API với provider đã chọn.</span>
          </label>
          <button onClick={discover} disabled={busy !== '' || (!apiKey && !conn)}
            className="inline-flex items-center gap-2 rounded-lg border border-slate-300 px-3 py-1.5 hover:bg-slate-50 disabled:opacity-40 dark:border-slate-700 dark:hover:bg-slate-800">
            {busy === 'discover' && <Loader2 className="h-4 w-4 animate-spin" />} Kiểm tra key & tải danh sách model</button>

          {models.length > 0 && (
            <div className="space-y-1.5">
              <span className="font-medium">Model được phép dùng</span>
              <div className="scroll-thin max-h-48 space-y-1 overflow-y-auto rounded-lg border border-slate-200 p-2 dark:border-slate-700">
                {models.map((m) => (
                  <label key={m.id} className="flex items-center gap-2 rounded px-1 py-0.5 hover:bg-slate-50 dark:hover:bg-slate-800">
                    <input type="checkbox" checked={allowed.includes(m.id)} onChange={() => toggle(m.id)} />
                    <span>{m.label}</span><span className="text-xs text-slate-400">{m.id}</span>
                  </label>
                ))}
              </div>
            </div>
          )}
          <label className="block space-y-1.5">
            <span className="font-medium">Model mặc định</span>
            <select value={defaultModel} onChange={(e) => setDefaultModel(e.target.value)} className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 dark:border-slate-700 dark:bg-slate-950">
              <option value="">—</option>
              {allowed.map((m) => <option key={m} value={m}>{m}</option>)}
            </select>
          </label>
          <div className="grid grid-cols-2 gap-3">
            <label className="block space-y-1.5">
              <span className="font-medium">Token output tối đa / lần gọi</span>
              <input type="number" min={256} max={65536} value={maxOut} onChange={(e) => setMaxOut(+e.target.value)}
                className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 dark:border-slate-700 dark:bg-slate-950" />
            </label>
            <label className="block space-y-1.5">
              <span className="font-medium">Token / ngày (0 = không giới hạn)</span>
              <input type="number" min={0} value={daily} onChange={(e) => setDaily(+e.target.value)}
                className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 dark:border-slate-700 dark:bg-slate-950" />
            </label>
          </div>
          <label className="block space-y-1.5">
            <span className="font-medium">Ngôn ngữ trả lời</span>
            <select value={lang} onChange={(e) => setLang(e.target.value)} className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 dark:border-slate-700 dark:bg-slate-950">
              <option value="auto">Theo ngôn ngữ câu hỏi</option><option value="vi">Tiếng Việt</option><option value="en">English</option>
            </select>
          </label>
          {error && <p className="rounded-lg bg-rose-50 px-3 py-2 text-rose-700 dark:bg-rose-950/50 dark:text-rose-300">{error}</p>}
          <div className="flex justify-end gap-2 pt-2">
            {savedKey && <button onClick={() => api.deleteConnection().then(onSaved)} className="mr-auto rounded-lg px-3 py-2 text-rose-600 hover:bg-rose-50 dark:hover:bg-rose-950/40">Ngắt kết nối</button>}
            <button onClick={onClose} className="rounded-lg px-4 py-2 hover:bg-slate-100 dark:hover:bg-slate-800">Hủy</button>
            <button onClick={save} disabled={busy !== '' || (!apiKey && !savedKey) || !defaultModel}
              className="inline-flex items-center gap-2 rounded-lg bg-indigo-600 px-4 py-2 font-medium text-white hover:bg-indigo-700 disabled:opacity-40">
              {busy === 'save' && <Loader2 className="h-4 w-4 animate-spin" />} Lưu</button>
          </div>
        </div>
      </div>
    </div>
  )
}
