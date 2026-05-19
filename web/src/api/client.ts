// API 客户端 — 封装所有后端接口调用

const BASE = import.meta.env.VITE_API_BASE ?? ''

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}/api${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  })
  if (!res.ok) {
    const err = await res.text()
    throw new Error(`${res.status}: ${err}`)
  }
  return res.json()
}

// ── 系统 ─────────────────────────────────────────────────────────────────

export const getHealth = () => request<{ status: string; version: string; db_url: string; llm_profile: string }>('/health')

// ── 数据源 ────────────────────────────────────────────────────────────────

export interface SourceInfo {
  source: string
  total_items: number
  last_run_status: string | null
  last_run_at: string | null
  last_run_items_in: number
  last_run_items_new: number
}

export const getSources = () => request<SourceInfo[]>('/sources')

export const triggerCrawl = (source: string) =>
  request<{ status: string; source: string }>(`/sources/${source}/crawl`, { method: 'POST' })

// ── 报告 ─────────────────────────────────────────────────────────────────

export interface ReportInfo {
  id: string
  template: string
  period_key: string
  file_path: string | null
  item_count: number
  status: string
  generated_at: string
}

export const getReports = (template?: string) =>
  request<ReportInfo[]>(template ? `/reports?template=${template}` : '/reports')

export const getLatestReport = (template: string) =>
  request<ReportInfo>(`/reports/latest/${template}`)

export const downloadReport = (reportId: string) =>
  `${BASE}/api/reports/${reportId}/file`

// ── Incidents ────────────────────────────────────────────────────────────

export interface ActionInfo {
  id: string
  action_key: string
  label: string
  endpoint: string | null
  order: number
  executed_at: string | null
}

export interface IncidentInfo {
  id: string
  signal_type: string
  severity: 'critical' | 'warning' | 'info'
  affected_resource: string | null
  title: string
  detail: string | null
  status: 'open' | 'resolving' | 'resolved' | 'dismissed'
  detected_at: string
  resolved_at: string | null
  actions: ActionInfo[]
}

export const getIncidents = (status?: string) =>
  request<IncidentInfo[]>(status ? `/incidents?status=${status}` : '/incidents')

export const dismissIncident = (id: string) =>
  request<{ ok: boolean }>(`/incidents/${id}/dismiss`, { method: 'POST' })

export const executeAction = (incidentId: string, actionKey: string) =>
  request<{ ok: boolean; result: Record<string, unknown> }>(
    `/incidents/${incidentId}/actions/${actionKey}`,
    { method: 'POST' }
  )
