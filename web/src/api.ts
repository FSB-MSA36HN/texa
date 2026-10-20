export type Source = { id: string; label: string; description: string; currency: string; min_date: string; max_date: string; row_count: number; user_count: number }
export type CatalogEntry = { id: string; label: string; description: string; unit?: string; synonyms: string[] }
export type Connection = { provider: string; base_url: string | null; allowed_models: string[]; default_model: string | null; max_output_tokens: number; daily_token_limit: number; answer_language: string; from_env?: boolean; has_key: boolean }
export type Bootstrap = {
  sources: Source[]
  catalog: { version?: number; metrics?: CatalogEntry[]; dimensions?: CatalogEntry[]; examples?: string[]; error?: string }
  connection: Connection | null
  providers: { id: string; label: string }[]
}
export type Column = { name: string; label: string; role: 'dimension' | 'metric'; unit: string; value_type: string }
export type Choice = { id: string; label: string; description?: string }
export type FormField = { id: string; label: string; kind: 'single_choice' | 'multi_choice'; required: boolean; allow_other: boolean; default: string[]; choices: Choice[] }
export type Step = { step: string; status: 'running' | 'done' | 'failed'; ms?: number; note?: string | null }
export type Insight = { headline: string; body: string[]; caveats: string[]; follow_ups: string[] }
export type QuerySpec = { source_ids: string[]; shape: string; selection: string[]; recipe: string; metrics: string[]; filters: { field: string; operator: string; values: string[] }[]; time_range: { kind: string; days?: number; start?: string; end?: string } }
export type Turn = {
  id: string; conversation_id: string; question: string; created_at: string; model: string | null
  status: 'running' | 'answered' | 'discussed' | 'needs_clarification' | 'refused' | 'conversation' | 'error' | 'cancelled'
  feedback: { rating: 'up' | 'down'; comment: string | null } | null
  message?: string | null; suggestions?: string[]
  form?: { message: string; fields: FormField[] } | null
  insight?: Insight; query_spec?: QuerySpec; compiled_sql?: string; columns?: Column[]; rows?: Record<string, unknown>[]
  row_count?: number; partial?: boolean; warnings?: string[]; notes?: string[]; variants?: Choice[]
  period?: Record<string, { start: string; end: string; data_start: string; data_end: string }>
  currency_of?: Record<string, string>; sources?: string[]
  error?: { code: string; message: string; retryable: boolean } | null
}
export type ConversationSummary = { id: string; title: string; updated_at: string }

export class ApiError extends Error {
  code: string
  constructor(code: string, message: string) { super(message); this.code = code }
}

async function call<T>(path: string, init?: RequestInit & { json?: unknown }): Promise<T> {
  const res = await fetch(path, {
    ...init,
    headers: init?.json !== undefined ? { 'content-type': 'application/json' } : undefined,
    body: init?.json !== undefined ? JSON.stringify(init.json) : init?.body,
  })
  const data = await res.json().catch(() => ({}))
  if (!res.ok) throw new ApiError(data.code ?? `HTTP_${res.status}`, data.message ?? data.detail?.[0]?.msg ?? res.statusText)
  return data as T
}

export const api = {
  bootstrap: () => call<Bootstrap>('/api/bootstrap'),
  conversations: () => call<ConversationSummary[]>('/api/conversations'),
  conversation: (id: string) => call<{ id: string; title: string; turns: Turn[] }>(`/api/conversations/${id}`),
  deleteConversation: (id: string) => call(`/api/conversations/${id}`, { method: 'DELETE' }),
  ask: (question: string, conversation_id: string | null, model: string | null, source_ids: string[]) =>
    call<{ turn_id: string; conversation_id: string }>('/api/questions', { method: 'POST', json: { question, conversation_id, model, source_ids } }),
  turn: (id: string) => call<Turn>(`/api/turns/${id}`),
  answer: (id: string, answers: Record<string, string[]>) => call(`/api/turns/${id}/answer`, { method: 'POST', json: { answers } }),
  retry: (id: string) => call(`/api/turns/${id}/retry`, { method: 'POST' }),
  cancel: (id: string) => call(`/api/turns/${id}/cancel`, { method: 'POST' }),
  variant: (id: string, metric_id: string) => call(`/api/turns/${id}/variant`, { method: 'POST', json: { metric_id } }),
  feedback: (id: string, rating: 'up' | 'down', comment = '') => call(`/api/turns/${id}/feedback`, { method: 'POST', json: { rating, comment } }),
  fullResult: (id: string) => call<{ columns: Column[]; rows: Record<string, unknown>[]; row_count: number; partial: boolean }>(`/api/turns/${id}/full-result`),
  saveConnection: (body: Partial<Connection> & { api_key?: string }) => call<Connection>('/api/model-connection', { method: 'PUT', json: body }),
  deleteConnection: () => call('/api/model-connection', { method: 'DELETE' }),
  discover: (provider: string, api_key?: string, base_url?: string) =>
    call<{ models: { id: string; label: string }[] }>('/api/model-connection/discover', { method: 'POST', json: { provider, api_key: api_key || null, base_url: base_url || null } }),
}

/** Follow a running turn: step events while it works, then the saved turn. Returns a stop function. */
export function followTurn(id: string, onStep: (s: Step) => void, onResult: (t: Turn) => void): () => void {
  const es = new EventSource(`/api/turns/${id}/stream`)
  let finished = false
  es.addEventListener('step', (e) => onStep(JSON.parse((e as MessageEvent).data)))
  es.addEventListener('result', (e) => { finished = true; es.close(); onResult(JSON.parse((e as MessageEvent).data)) })
  es.onerror = () => {
    if (finished) return
    es.close()
    // The stream dropped: read the saved state once instead.
    setTimeout(() => api.turn(id).then((t) => (t.status === 'running' ? followTurn(id, onStep, onResult) : onResult(t))).catch(() => {}), 1500)
  }
  return () => { finished = true; es.close() }
}
