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
  features?: { process_management?: boolean }
}

export type ProcessState = 'starting' | 'running' | 'stopped' | 'failed' | 'exited'

export interface ManagedProcess {
  id: string
  service_id: string
  allocation_id: string | null
  command: string
  working_directory: string | null
  pid: number | null
  state: ProcessState
  exit_code: number | null
  log_path: string | null
  last_error: string | null
  created_at: string
  started_at: string | null
  stopped_at: string | null
  alive: boolean
}

export interface ServiceLogs {
  service_id: string
  log_path: string
  tail: number
  lines: string[]
  process: ManagedProcess | null
}

export type AllocationState = 'reserved' | 'released'
export type ResourceType = 'single' | 'block' | 'count'

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
  process?: ManagedProcess | null
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

export interface WithinRange {
  start: number
  end: number
}

export interface ResourceSpec {
  name: string
  type: ResourceType
  size?: number
  count?: number
  contiguous?: boolean
  port_names?: string[]
  preferred_port?: number
  strict_preferred?: boolean
  within?: WithinRange
}

export interface AgentContext {
  type?: string | null
  project_id?: string | null
}

export interface ServiceInput {
  key: string
  instance?: string | null
  name?: string | null
  description?: string | null
  code_path?: string | null
  working_directory?: string | null
  start_command?: string | null
}

export interface EnsureRequest {
  agent?: AgentContext | null
  service: ServiceInput
  allocation_name?: string
  resources: ResourceSpec[]
}

export interface EnsureResponse {
  service_id: string
  allocation_id: string
  existing: boolean
  sticky: boolean
  ports: Record<string, number>
  blocks: Record<string, { start: number; end: number } | Record<string, number>>
  availability: Record<string, { state: string; pid?: number | null; command?: string | null }>
}

export interface ServiceCreateRequest {
  agent?: AgentContext | null
  service: ServiceInput
}

export interface ServiceUpdateRequest {
  name?: string | null
  description?: string | null
  code_path?: string | null
  working_directory?: string | null
  start_command?: string | null
}

export interface ReleaseResult {
  allocation_id: string
  state: AllocationState
  released_at: string | null
  release_reason: string | null
  ports_history: AllocatedPort[]
}

export interface DeleteServiceResult {
  service_id: string
  deleted: boolean
  reason?: string | null
  [key: string]: unknown
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
  PROCESS_MANAGEMENT_DISABLED: '进程管理未开启（需 process_management.enabled）',
  PROCESS_ALREADY_RUNNING: '服务进程已在运行',
  PROCESS_NOT_RUNNING: '服务进程未在运行',
  NO_START_COMMAND: '服务未配置启动命令',
  INTERNAL_ERROR: '服务端内部错误',
  NETWORK_ERROR: '无法连接 Registry',
  INVALID_RESPONSE: '响应不是合法 JSON',
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

/** Best-effort Chinese label for anything thrown by the client. */
export function errorLabel(error: unknown): string {
  if (error instanceof AprApiError) return error.label
  if (error && typeof error === 'object' && 'label' in error) {
    return String((error as { label: string }).label)
  }
  if (error instanceof Error) return error.message
  return String(error)
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

  ensure: (body: EnsureRequest) =>
    request<EnsureResponse>('/v1/allocations/ensure', {
      method: 'POST',
      body: JSON.stringify(body),
    }),

  createService: (body: ServiceCreateRequest) =>
    request<Service>('/v1/services', {
      method: 'POST',
      body: JSON.stringify(body),
    }),

  patchService: (id: string, body: ServiceUpdateRequest) =>
    request<Service>(`/v1/services/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(body),
    }),

  deleteService: (id: string, reason?: string) =>
    request<DeleteServiceResult>(`/v1/services/${id}`, {
      method: 'DELETE',
      body: reason ? JSON.stringify({ reason }) : undefined,
    }),

  releaseAllocation: (id: string, reason?: string) =>
    request<ReleaseResult>(`/v1/allocations/${id}/release`, {
      method: 'POST',
      body: reason ? JSON.stringify({ reason }) : undefined,
    }),

  deleteAllocation: (id: string, opts?: { force?: boolean; reason?: string }) => {
    const force = opts?.force ?? true
    const q = force ? '' : '?force=false'
    return request<{ allocation_id: string; deleted: boolean }>(
      `/v1/allocations/${id}${q}`,
      {
        method: 'DELETE',
        body: opts?.reason ? JSON.stringify({ reason: opts.reason }) : undefined,
      },
    )
  },

  startService: (id: string) =>
    request<ManagedProcess>(`/v1/services/${id}/start`, { method: 'POST' }),

  stopService: (id: string) =>
    request<ManagedProcess>(`/v1/services/${id}/stop`, { method: 'POST' }),

  serviceLogs: (id: string, tail = 200) =>
    request<ServiceLogs>(`/v1/services/${id}/logs?tail=${tail}`),

  serviceProcess: (id: string) =>
    request<{ service_id: string; process: ManagedProcess | null }>(
      `/v1/services/${id}/process`,
    ),
}

/* ------------------------------------------------------------- query utils */

export const queryKeys = {
  overview: ['overview'] as const,
  pool: ['pool'] as const,
  listeners: ['listeners'] as const,
  services: ['services'] as const,
  service: (id: string) => ['service', id] as const,
  port: (port: number) => ['port', port] as const,
  serviceLogs: (id: string) => ['service-logs', id] as const,
  serviceProcess: (id: string) => ['service-process', id] as const,
}

/** Invalidate every list/detail view that shows services or ports. */
export function invalidateServiceViews(
  client: { invalidateQueries: (opts: { queryKey: readonly unknown[] }) => Promise<unknown> },
  serviceId?: string,
) {
  const tasks = [
    client.invalidateQueries({ queryKey: queryKeys.services }),
    client.invalidateQueries({ queryKey: queryKeys.overview }),
    client.invalidateQueries({ queryKey: queryKeys.pool }),
    client.invalidateQueries({ queryKey: queryKeys.listeners }),
  ]
  if (serviceId) {
    tasks.push(client.invalidateQueries({ queryKey: queryKeys.service(serviceId) }))
    tasks.push(client.invalidateQueries({ queryKey: queryKeys.serviceLogs(serviceId) }))
    tasks.push(client.invalidateQueries({ queryKey: queryKeys.serviceProcess(serviceId) }))
  }
  return Promise.all(tasks)
}
