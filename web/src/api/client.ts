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

// ── Token 管理 ────────────────────────────────────────────────────────────

export interface TokenStatus {
  github_configured: boolean
  reddit_configured: boolean
  github_masked: string | null
  reddit_client_masked: string | null
}

export interface TestResult {
  ok: boolean
  message: string
}

export const getTokenStatus = () => request<TokenStatus>('/tokens/status')

export const testGithubToken = (token: string) =>
  request<TestResult>('/tokens/github/test', {
    method: 'POST',
    body: JSON.stringify({ token }),
  })

export const saveGithubToken = (token: string) =>
  request<{ ok: boolean; message: string }>('/tokens/github/save', {
    method: 'POST',
    body: JSON.stringify({ token }),
  })

export const testRedditToken = (creds: {
  client_id: string
  client_secret: string
  username?: string
  password?: string
}) =>
  request<TestResult>('/tokens/reddit/test', {
    method: 'POST',
    body: JSON.stringify(creds),
  })

// ── 系统设置 ──────────────────────────────────────────────────────────────────

export interface SourceConfig { enabled: boolean; interval: string; description: string }
export interface LLMProfileConfig { profile: string; model: string; base_url: string; api_key_masked: string }
export interface SettingsOverview {
  github: SourceConfig
  reddit: SourceConfig
  active_profile: string
  yunwu: LLMProfileConfig
  heyi: LLMProfileConfig
  ollama: LLMProfileConfig
  openai: LLMProfileConfig
  max_items_per_run: number
  report_projects_cron: string
  report_communities_cron: string
}

export const getSettingsOverview = () => request<SettingsOverview>('/settings/overview')

export const updateSourceSettings = (body: {
  github_enabled: boolean
  github_interval: string
  reddit_enabled: boolean
  reddit_interval: string
}) => request<{ ok: boolean; message: string }>('/settings/sources', { method: 'POST', body: JSON.stringify(body) })

export const updateLLMSettings = (body: {
  profile: string
  model?: string
  base_url?: string
  api_key?: string
}) => request<{ ok: boolean; message: string }>('/settings/llm', { method: 'POST', body: JSON.stringify(body) })

export const testLLMSettings = (body: {
  profile: string
  model?: string
  base_url?: string
  api_key?: string
}) => request<{ ok: boolean; message: string; model_used: string }>('/settings/llm/test', { method: 'POST', body: JSON.stringify(body) })

export const saveRedditToken = (creds: {
  client_id: string
  client_secret: string
  username?: string
  password?: string
}) =>
  request<{ ok: boolean; message: string }>('/tokens/reddit/save', {
    method: 'POST',
    body: JSON.stringify(creds),
  })
