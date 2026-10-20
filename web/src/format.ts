import type { Bootstrap, Column, QuerySpec } from './api'

export const STEP_LABELS: Record<string, string> = {
  read_conversation: 'Đọc hội thoại',
  prepare_context: 'Chuẩn bị ngữ cảnh',
  interpret: 'Hiểu câu hỏi',
  check_interpretation: 'Kiểm tra diễn giải',
  validate_query: 'Kiểm tra truy vấn',
  check_data: 'Soát dữ liệu',
  compile_sql: 'Dựng SQL',
  run_query: 'Chạy truy vấn',
  write_answer: 'Viết nhận xét',
}

export const ERROR_HINTS: Record<string, string> = {
  NO_KEY: 'Chưa kết nối model. Mở Cài đặt để thêm API key.',
  AUTH: 'API key bị từ chối. Kiểm tra lại key trong Cài đặt.',
  QUOTA: 'Provider báo hết hạn mức. Thử lại sau ít phút.',
  DAILY_LIMIT: 'Đã dùng hết ngân sách token hôm nay.',
  BAD_MODEL: 'Model không dùng được. Chọn model khác.',
  MODEL_OUTPUT_INVALID: 'Model trả lời sai định dạng. Thử lại hoặc diễn đạt khác.',
  MODEL_OUTPUT_TRUNCATED: 'Câu trả lời bị cắt. Hỏi ngắn gọn hơn.',
  TIMEOUT: 'Model phản hồi quá lâu. Thử lại.',
  INTERRUPTED: 'Server khởi động lại khi đang chạy. Thử lại.',
}

const nf = (digits: number) => new Intl.NumberFormat('vi-VN', { maximumFractionDigits: digits, minimumFractionDigits: 0 })

export function formatCell(value: unknown, col: Column, currency?: string): string {
  if (value === null || value === undefined) return col.role === 'metric' ? '—' : '(trống)'
  if (typeof value !== 'number') return String(value)
  switch (col.unit) {
    case 'percent': return `${nf(1).format(value * 100)}%`
    case 'currency': return `${nf(2).format(value)}${currency ? ` ${currency}` : ''}`
    case 'count': return nf(0).format(value)
    default: return nf(2).format(value)
  }
}

export function rowCurrency(row: Record<string, unknown>, currencyOf?: Record<string, string>): string | undefined {
  if (!currencyOf) return undefined
  if (typeof row.source === 'string') return currencyOf[row.source]
  const all = Object.values(currencyOf)
  return all.length === 1 ? all[0] : undefined
}

/** "Texa hiểu là…" chips: metric · breakdowns · filters · period · stores. */
export function readingChips(spec: QuerySpec, boot: Bootstrap, period?: Record<string, { start: string; end: string }>): string[] {
  const m = Object.fromEntries((boot.catalog.metrics ?? []).map((x) => [x.id, x.label]))
  const d = Object.fromEntries((boot.catalog.dimensions ?? []).map((x) => [x.id, x.label]))
  const s = Object.fromEntries(boot.sources.map((x) => [x.id, x.label]))
  const chips: string[] = []
  const metrics = spec.recipe ? [spec.recipe] : spec.metrics
  if (metrics.length) chips.push(metrics.map((x) => m[x] ?? x).join(', '))
  if (spec.selection.length) chips.push('theo ' + spec.selection.map((x) => d[x] ?? x).join(', '))
  for (const f of spec.filters) chips.push(`${d[f.field] ?? f.field} ${f.operator} ${f.values.join(', ')}`)
  const tr = spec.time_range
  if (period) {
    const spans = [...new Set(Object.values(period).map((p) => `${p.start} → ${p.end}`))]
    chips.push(spans.join(' · '))
  } else if (tr.kind === 'last_n_days') chips.push(`${tr.days} ngày gần nhất`)
  chips.push(spec.source_ids.map((x) => s[x] ?? x).join(' + '))
  return chips
}

export function toCsv(columns: Column[], rows: Record<string, unknown>[]): string {
  const esc = (v: unknown) => {
    const t = v === null || v === undefined ? '' : String(v)
    return /[",\n]/.test(t) ? `"${t.replace(/"/g, '""')}"` : t
  }
  return [columns.map((c) => esc(c.label)).join(','), ...rows.map((r) => columns.map((c) => esc(r[c.name])).join(','))].join('\n')
}
