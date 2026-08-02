import { useEffect, useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { Plus, Trash2 } from 'lucide-react'
import {
  api,
  invalidateServiceViews,
  type EnsureRequest,
  type ResourceSpec,
  type ResourceType,
  type Service,
} from '../lib/api'
import {
  Button,
  FieldLabel,
  FormError,
  Modal,
  TextInput,
  TextSelect,
  TextTextarea,
} from './ui'

interface Props {
  open: boolean
  onClose: () => void
  /** When set, pre-fill identity and create a new allocation for this service. */
  service?: Service | null
}

interface ResourceDraft {
  name: string
  type: ResourceType
  size: string
  count: string
  portNames: string
  preferredPort: string
}

function emptyResource(name = 'http'): ResourceDraft {
  return {
    name,
    type: 'single',
    size: '2',
    count: '2',
    portNames: '',
    preferredPort: '',
  }
}

function toSpec(r: ResourceDraft): ResourceSpec {
  const name = r.name.trim()
  if (!name) throw new Error('资源名称不能为空')

  const base: ResourceSpec = { name, type: r.type }
  if (r.type === 'block') {
    const size = Number(r.size)
    if (!Number.isInteger(size) || size < 1) throw new Error(`资源 ${name}：block 需要 size ≥ 1`)
    base.size = size
  }
  if (r.type === 'count') {
    const count = Number(r.count)
    if (!Number.isInteger(count) || count < 1) throw new Error(`资源 ${name}：count 需要 count ≥ 1`)
    base.count = count
    const names = r.portNames
      .split(/[,\s]+/)
      .map((s) => s.trim())
      .filter(Boolean)
    if (names.length > 0) {
      if (names.length !== count) {
        throw new Error(`资源 ${name}：port_names 数量必须等于 count`)
      }
      base.port_names = names
    }
  }
  if (r.preferredPort.trim()) {
    const p = Number(r.preferredPort)
    if (!Number.isInteger(p) || p < 1 || p > 65535) {
      throw new Error(`资源 ${name}：preferred_port 必须在 1–65535`)
    }
    base.preferred_port = p
  }
  return base
}

export default function EnsureForm({ open, onClose, service }: Props) {
  const isExisting = Boolean(service)
  const navigate = useNavigate()
  const qc = useQueryClient()

  const [agentType, setAgentType] = useState(service?.agent_type ?? service?.agent_type_key ?? '')
  const [projectId, setProjectId] = useState(
    service?.agent_project_id ?? service?.agent_project_key ?? '',
  )
  const [serviceKey, setServiceKey] = useState(service?.service_key ?? '')
  const [instance, setInstance] = useState(service?.instance_key ?? 'default')
  const [name, setName] = useState(service?.name ?? '')
  const [description, setDescription] = useState(service?.description ?? '')
  const [codePath, setCodePath] = useState(service?.code_path ?? '')
  const [workingDirectory, setWorkingDirectory] = useState(service?.working_directory ?? '')
  const [startCommand, setStartCommand] = useState(service?.start_command ?? '')
  const [allocationName, setAllocationName] = useState(isExisting ? '' : 'default')
  const [resources, setResources] = useState<ResourceDraft[]>([emptyResource()])
  const [localError, setLocalError] = useState<string | null>(null)

  const mutation = useMutation({
    mutationFn: (body: EnsureRequest) => api.ensure(body),
    onSuccess: async (result) => {
      await invalidateServiceViews(qc, result.service_id)
      onClose()
      navigate(`/services/${result.service_id}`)
    },
  })

  useEffect(() => {
    if (!open) return
    setAgentType(service?.agent_type ?? service?.agent_type_key ?? '')
    setProjectId(service?.agent_project_id ?? service?.agent_project_key ?? '')
    setServiceKey(service?.service_key ?? '')
    setInstance(service?.instance_key ?? 'default')
    setName(service?.name ?? '')
    setDescription(service?.description ?? '')
    setCodePath(service?.code_path ?? '')
    setWorkingDirectory(service?.working_directory ?? '')
    setStartCommand(service?.start_command ?? '')
    setAllocationName(
      service ? `alloc-${Date.now().toString(36).slice(-4)}` : 'default',
    )
    setResources([emptyResource()])
    setLocalError(null)
    mutation.reset()
    // Only re-seed when the modal opens or the target service changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, service?.id])

  const updateResource = (index: number, patch: Partial<ResourceDraft>) => {
    setResources((list) => list.map((r, i) => (i === index ? { ...r, ...patch } : r)))
  }

  const submit = (e: React.FormEvent) => {
    e.preventDefault()
    setLocalError(null)

    const key = serviceKey.trim()
    if (!key) {
      setLocalError('服务 key 不能为空')
      return
    }
    if (!allocationName.trim()) {
      setLocalError('分配名称不能为空')
      return
    }
    if (resources.length === 0) {
      setLocalError('至少需要一个资源')
      return
    }

    let specs: ResourceSpec[]
    try {
      specs = resources.map(toSpec)
    } catch (err) {
      setLocalError(err instanceof Error ? err.message : String(err))
      return
    }

    const body: EnsureRequest = {
      agent: {
        type: agentType.trim() || null,
        project_id: projectId.trim() || null,
      },
      service: {
        key,
        instance: instance.trim() || 'default',
        name: name.trim() || key,
        description: description.trim() || null,
        code_path: codePath.trim() || null,
        working_directory: workingDirectory.trim() || null,
        start_command: startCommand.trim() || null,
      },
      allocation_name: allocationName.trim() || 'default',
      resources: specs,
    }
    mutation.mutate(body)
  }

  return (
    <Modal
      open={open}
      onClose={mutation.isPending ? () => undefined : onClose}
      title={isExisting ? '申请端口' : '新建服务并分配端口'}
      hint={
        isExisting
          ? '使用同一服务标识追加一次 ensure；规格与已有分配冲突时会报错'
          : '调用 POST /v1/allocations/ensure，幂等创建服务与端口分配'
      }
      wide
    >
      <form onSubmit={submit} className="space-y-5">
        <section className="grid gap-3 sm:grid-cols-2">
          <div>
            <FieldLabel htmlFor="svc-key">服务 key *</FieldLabel>
            <TextInput
              id="svc-key"
              value={serviceKey}
              onChange={(e) => setServiceKey(e.target.value)}
              placeholder="model-api"
              required
              disabled={isExisting || mutation.isPending}
              className="font-mono"
            />
          </div>
          <div>
            <FieldLabel htmlFor="svc-name">显示名称</FieldLabel>
            <TextInput
              id="svc-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Model API"
              disabled={mutation.isPending}
            />
          </div>
          <div>
            <FieldLabel htmlFor="svc-instance">实例</FieldLabel>
            <TextInput
              id="svc-instance"
              value={instance}
              onChange={(e) => setInstance(e.target.value)}
              placeholder="default"
              disabled={isExisting || mutation.isPending}
              className="font-mono"
            />
          </div>
          <div>
            <FieldLabel htmlFor="alloc-name">分配名称 *</FieldLabel>
            <TextInput
              id="alloc-name"
              value={allocationName}
              onChange={(e) => setAllocationName(e.target.value)}
              placeholder="default"
              required
              disabled={mutation.isPending}
              className="font-mono"
            />
          </div>
          <div>
            <FieldLabel htmlFor="agent-type">Agent 类型</FieldLabel>
            <TextInput
              id="agent-type"
              value={agentType}
              onChange={(e) => setAgentType(e.target.value)}
              placeholder="codex / claude-code / grok-build"
              disabled={isExisting || mutation.isPending}
              className="font-mono"
            />
          </div>
          <div>
            <FieldLabel htmlFor="project-id">项目 ID</FieldLabel>
            <TextInput
              id="project-id"
              value={projectId}
              onChange={(e) => setProjectId(e.target.value)}
              placeholder="my-project"
              disabled={isExisting || mutation.isPending}
              className="font-mono"
            />
          </div>
        </section>

        {!isExisting && (
          <section className="space-y-3">
            <div>
              <FieldLabel htmlFor="desc">描述</FieldLabel>
              <TextInput
                id="desc"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                disabled={mutation.isPending}
              />
            </div>
            <div className="grid gap-3 sm:grid-cols-2">
              <div>
                <FieldLabel htmlFor="code-path">代码路径</FieldLabel>
                <TextInput
                  id="code-path"
                  value={codePath}
                  onChange={(e) => setCodePath(e.target.value)}
                  className="font-mono"
                  disabled={mutation.isPending}
                />
              </div>
              <div>
                <FieldLabel htmlFor="cwd">工作目录</FieldLabel>
                <TextInput
                  id="cwd"
                  value={workingDirectory}
                  onChange={(e) => setWorkingDirectory(e.target.value)}
                  className="font-mono"
                  disabled={mutation.isPending}
                />
              </div>
            </div>
            <div>
              <FieldLabel htmlFor="start-cmd" hint="支持 {{ports.http}} 占位符">
                启动命令
              </FieldLabel>
              <TextTextarea
                id="start-cmd"
                value={startCommand}
                onChange={(e) => setStartCommand(e.target.value)}
                placeholder="uv run python -m api --port {{ports.http}}"
                disabled={mutation.isPending}
              />
            </div>
          </section>
        )}

        <section className="space-y-3">
          <div className="flex items-center justify-between">
            <h3 className="text-xs font-medium text-muted">端口资源</h3>
            <Button
              type="button"
              variant="ghost"
              className="text-xs"
              disabled={mutation.isPending}
              onClick={() =>
                setResources((list) => [
                  ...list,
                  emptyResource(list.length === 0 ? 'http' : `port${list.length + 1}`),
                ])
              }
            >
              <Plus size={13} />
              添加资源
            </Button>
          </div>

          {resources.map((r, i) => (
            <div
              key={i}
              className="space-y-2 rounded-lg border border-line-soft bg-raised/40 p-3"
            >
              <div className="grid gap-2 sm:grid-cols-4">
                <div>
                  <FieldLabel>名称 *</FieldLabel>
                  <TextInput
                    value={r.name}
                    onChange={(e) => updateResource(i, { name: e.target.value })}
                    className="font-mono"
                    disabled={mutation.isPending}
                  />
                </div>
                <div>
                  <FieldLabel>类型</FieldLabel>
                  <TextSelect
                    value={r.type}
                    onChange={(e) =>
                      updateResource(i, { type: e.target.value as ResourceType })
                    }
                    disabled={mutation.isPending}
                  >
                    <option value="single">single（单端口）</option>
                    <option value="block">block（连续块）</option>
                    <option value="count">count（多个）</option>
                  </TextSelect>
                </div>
                {r.type === 'block' && (
                  <div>
                    <FieldLabel>size</FieldLabel>
                    <TextInput
                      type="number"
                      min={1}
                      value={r.size}
                      onChange={(e) => updateResource(i, { size: e.target.value })}
                      className="font-mono"
                      disabled={mutation.isPending}
                    />
                  </div>
                )}
                {r.type === 'count' && (
                  <div>
                    <FieldLabel>count</FieldLabel>
                    <TextInput
                      type="number"
                      min={1}
                      value={r.count}
                      onChange={(e) => updateResource(i, { count: e.target.value })}
                      className="font-mono"
                      disabled={mutation.isPending}
                    />
                  </div>
                )}
                <div>
                  <FieldLabel hint="可选">preferred</FieldLabel>
                  <TextInput
                    type="number"
                    min={1}
                    max={65535}
                    value={r.preferredPort}
                    onChange={(e) => updateResource(i, { preferredPort: e.target.value })}
                    className="font-mono"
                    placeholder="自动"
                    disabled={mutation.isPending}
                  />
                </div>
              </div>
              {r.type === 'count' && (
                <div>
                  <FieldLabel hint="逗号分隔，数量须等于 count">port_names</FieldLabel>
                  <TextInput
                    value={r.portNames}
                    onChange={(e) => updateResource(i, { portNames: e.target.value })}
                    className="font-mono"
                    placeholder="http, metrics"
                    disabled={mutation.isPending}
                  />
                </div>
              )}
              {resources.length > 1 && (
                <div className="flex justify-end">
                  <Button
                    type="button"
                    variant="ghost"
                    className="text-xs text-danger"
                    disabled={mutation.isPending}
                    onClick={() => setResources((list) => list.filter((_, j) => j !== i))}
                  >
                    <Trash2 size={13} />
                    移除
                  </Button>
                </div>
              )}
            </div>
          ))}
        </section>

        {(localError || mutation.isError) && (
          <FormError error={localError ?? mutation.error} />
        )}

        <div className="flex justify-end gap-2 border-t border-line-soft pt-4">
          <Button type="button" variant="ghost" onClick={onClose} disabled={mutation.isPending}>
            取消
          </Button>
          <Button type="submit" variant="primary" disabled={mutation.isPending}>
            {mutation.isPending ? '提交中…' : isExisting ? '申请端口' : '创建并分配'}
          </Button>
        </div>
      </form>
    </Modal>
  )
}
