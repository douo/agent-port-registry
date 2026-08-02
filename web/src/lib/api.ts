/**
 * Typed client for the APR Registry API.
 *
 * Shapes mirror `src/apr/api/routes.py`; keep them in sync when routes change.
 */

/* ------------------------------------------------------------------ types */

export interface Overview {
  version: string
  hostname: string
  services: {
    total: number
    by_agent: Record<string, number>
    by_project: Record<string, number>
  }
  allocations: { reserved: number; released: number }
  ports: { claimed: number; live: number; idle: number; idle_ports: number[] }
  pool: {
    start: number
    end: number
    usable: number
    free: number
    utilization: number
  }
  nodes: { total: number; snapshots: number }
  forwards: { active: number }
}

export type AllocationState = 'reserved' | 'released'

export interface AllocatedPort {
  resource_name: string
  port_name: string | null
  port: number
  ordinal: number
}

export interface Allocation {
  id: string
  allocation_name: string
  state: AllocationState
  sticky: boolean
  created_at: string
  released_at: string | null
  release_reason: string | null
  request_spec: unknown
  ports: AllocatedPort[]
}

export interface Service {
  id: string
  agent_type: string | null
  agent_project_id: string | null
  agent_type_key: string
  agent_project_key: string
  service_key: string
  instance_key: string
  name: string
  description: string | null
  code_path: string | null
  working_directory: string | null
  start_command: string | null
  created_at: string
  updated_at: string
  allocations: Allocation[]
}

export interface Pool {
  start: number
  end: number
  total: number
  usable: number
  excluded_count: number
  excluded_ranges: [number, number][]
  claimed: number[]
  claimed_count: number
  claimed_ranges: [number, number][]
  listening_in_pool: number[]
  free: number
  utilization: number
}

export interface Listener {
  port: number
  pid: number | null
  command: string | null
}

export interface PortLookup {
  port: number
  active: boolean
  resource_name: string
  port_name: string | null
  service: Service | null
  allocation: { id: string; allocation_name: string; state: AllocationState } | null
}

/* ------------------------------------------------------------------ errors */

/** Business error codes from `apr.domain.errors.ErrorCode`. */
export const ERROR_MESSAGES: Record<string, string> = {
  INVALID_REQUEST: '请求不合法',
  SERVICE_IDENTITY_CONFLICT: '服务标识已存在',
  ALLOCATION_SPEC_MISMATCH: '分配规格与既有分配不一致',
  PORT_CAPACITY_EXHAUSTED: '端口池容量已耗尽',
  PREFERRED_PORT_UNAVAILABLE: '指定端口不可用',
  PORT_OCCUPIED: '端口已被占用',
  ALLOCATION_RELEASED: '分配已被释放',
  SERVICE_NOT_FOUND: '服务不存在',
  ALLOCATION_NOT_FOUND: '分配不存在',
  INTERNAL_ERROR: '服务端内部错误',
}

export class AprApiError extends Error {
  readonly status: number
  readonly code: string

  constructor(status: number, code: string, message: string) {
    super(message)
    this.name = 'AprApiError'
    this.status = status
    this.code = code
  }

  /** Localised label, falling back to the server's raw message. */
  get label(): string {
    return ERROR_MESSAGES[this.code] ?? this.message
  }
}

/* ------------------------------------------------------------------ client */

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response
  try {
    res = await fetch(path, {
      ...init,
      headers:
        init?.body != null
          ? { 'Content-Type': 'application/json', ...init?.headers }
          : init?.headers,
    })
  } catch (cause) {
    throw new AprApiError(0, 'NETWORK_ERROR', `无法连接 Registry：${String(cause)}`)
  }

  const text = await res.text()
  let body: unknown = null
  if (text) {
    try {
      body = JSON.parse(text)
    } catch {
      // The SPA fallback answers HTML for unknown paths; surface that clearly
      // instead of letting a parse error bubble up as something cryptic.
      if (!res.ok) {
        throw new AprApiError(res.status, `HTTP_${res.status}`, res.statusText)
      }
      throw new AprApiError(res.status, 'INVALID_RESPONSE', '响应不是合法 JSON')
    }
  }

  if (!res.ok) {
    const err = (body as { error?: { code?: string; message?: string } } | null)?.error
    throw new AprApiError(
      res.status,
      err?.code ?? `HTTP_${res.status}`,
      err?.message ?? res.statusText,
    )
  }
  return body as T
}

export const api = {
  overview: () => request<Overview>('/v1/overview'),
  pool: () => request<Pool>('/v1/pool'),
  listeners: (inPool = false) =>
    request<{ listeners: Listener[]; count: number }>(
      `/v1/listeners${inPool ? '?in_pool=1' : ''}`,
    ).then((r) => r.listeners),
  services: () =>
    request<{ services: Service[] }>('/v1/services').then((r) => r.services),
  service: (id: string) => request<Service>(`/v1/services/${id}`),
  port: (port: number) => request<PortLookup>(`/v1/ports/${port}`),
}

/* ------------------------------------------------------------- query utils */

export const queryKeys = {
  overview: ['overview'] as const,
  pool: ['pool'] as const,
  listeners: ['listeners'] as const,
  services: ['services'] as const,
  service: (id: string) => ['service', id] as const,
  port: (port: number) => ['port', port] as const,
}
