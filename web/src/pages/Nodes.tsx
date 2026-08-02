import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Plus, RefreshCw, Server, Trash2 } from 'lucide-react'
import { api, errorLabel, queryKeys, type Node, type NodeCreateRequest } from '../lib/api'
import { relativeTime } from '../lib/format'
import {
  Button,
  ConfirmDialog,
  Empty,
  ErrorNote,
  FieldLabel,
  FormError,
  Loading,
  Modal,
  Panel,
  TextInput,
} from '../components/ui'

function statusOf(node: Node): { label: string; tone: string } {
  const snap = node.snapshot
  if (!node.enabled) return { label: '已禁用', tone: 'text-faint' }
  if (!snap) return { label: '未同步', tone: 'text-idle' }
  if (snap.status === 'ok') return { label: '在线', tone: 'text-live' }
  return { label: '错误', tone: 'text-danger' }
}

export default function Nodes() {
  const qc = useQueryClient()
  const [addOpen, setAddOpen] = useState(false)
  const [deleteId, setDeleteId] = useState<string | null>(null)
  const [actionError, setActionError] = useState<unknown>(null)

  const nodes = useQuery({
    queryKey: queryKeys.nodes,
    queryFn: api.nodes,
    refetchInterval: 15000,
  })

  const refreshMut = useMutation({
    mutationFn: (id: string) => api.refreshNode(id),
    onSuccess: async () => {
      setActionError(null)
      await qc.invalidateQueries({ queryKey: queryKeys.nodes })
    },
    onError: (err) => setActionError(err),
  })

  const deleteMut = useMutation({
    mutationFn: (id: string) => api.deleteNode(id),
    onSuccess: async () => {
      setDeleteId(null)
      setActionError(null)
      await qc.invalidateQueries({ queryKey: queryKeys.nodes })
      await qc.invalidateQueries({ queryKey: queryKeys.overview })
    },
    onError: (err) => setActionError(err),
  })

  if (nodes.isError) return <ErrorNote error={nodes.error} />

  const list = nodes.data ?? []

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <p className="text-sm text-muted">
          通过 SSH 管理从节点；服务列表与启停走远程 <code className="text-xs">svcctl</code>，
          端口转发用 <code className="text-xs">autossh</code>。
        </p>
        <Button variant="primary" className="ml-auto shrink-0" onClick={() => setAddOpen(true)}>
          <Plus size={14} />
          添加节点
        </Button>
      </div>

      {actionError != null && (
        <div className="panel border-danger/30 bg-danger/5 px-4 py-3 text-sm text-danger">
          {errorLabel(actionError)}
        </div>
      )}

      <Panel className="overflow-hidden">
        {nodes.isLoading ? (
          <Loading />
        ) : list.length === 0 ? (
          <Empty
            title="还没有从节点"
            hint="添加一台可通过 SSH 访问、且已安装 svcctl 的机器"
          />
        ) : (
          <div className="divide-y divide-line-soft">
            {list.map((node) => {
              const st = statusOf(node)
              const svcCount =
                node.snapshot?.status === 'ok'
                  ? (node.snapshot.payload?.services?.length ?? 0)
                  : null
              return (
                <div
                  key={node.id}
                  className="flex flex-wrap items-center gap-3 px-4 py-3.5 transition-colors hover:bg-hover/40"
                >
                  <div className="grid h-9 w-9 place-items-center rounded-lg bg-raised text-muted">
                    <Server size={16} strokeWidth={1.75} />
                  </div>
                  <div className="min-w-0 flex-1">
                    <Link
                      to={`/nodes/${node.id}`}
                      className="block truncate text-sm font-medium hover:text-brand"
                    >
                      {node.name}
                    </Link>
                    <div className="truncate font-mono text-[11px] text-faint">
                      {node.ssh_user ? `${node.ssh_user}@` : ''}
                      {node.ssh_host}
                      {node.ssh_port ? `:${node.ssh_port}` : ''}
                      {' · '}
                      {node.apr_command}
                    </div>
                  </div>
                  <div className="text-right text-xs">
                    <div className={st.tone}>{st.label}</div>
                    <div className="text-faint">
                      {svcCount != null ? `${svcCount} 个服务 · ` : ''}
                      {relativeTime(node.snapshot?.fetched_at ?? node.last_seen_at)}
                    </div>
                    {node.snapshot?.status === 'error' && node.snapshot.error && (
                      <div className="mt-0.5 max-w-xs truncate text-danger" title={node.snapshot.error}>
                        {node.snapshot.error}
                      </div>
                    )}
                  </div>
                  <div className="flex items-center gap-1.5">
                    <Button
                      variant="ghost"
                      title="立即同步"
                      disabled={refreshMut.isPending}
                      onClick={() => refreshMut.mutate(node.id)}
                    >
                      <RefreshCw size={14} className={refreshMut.isPending ? 'animate-spin' : ''} />
                    </Button>
                    <Button
                      variant="ghost"
                      title="删除"
                      onClick={() => setDeleteId(node.id)}
                    >
                      <Trash2 size={14} />
                    </Button>
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </Panel>

      <AddNodeModal
        open={addOpen}
        onClose={() => setAddOpen(false)}
        onCreated={async () => {
          setAddOpen(false)
          await qc.invalidateQueries({ queryKey: queryKeys.nodes })
          await qc.invalidateQueries({ queryKey: queryKeys.overview })
        }}
      />

      <ConfirmDialog
        open={deleteId != null}
        title="删除从节点？"
        body="将停止该节点的本地转发，并删除节点记录（不影响从节点本身）。"
        confirmLabel="删除"
        danger
        loading={deleteMut.isPending}
        onConfirm={() => {
          if (deleteId) deleteMut.mutate(deleteId)
        }}
        onClose={() => setDeleteId(null)}
      />
    </div>
  )
}

function AddNodeModal({
  open,
  onClose,
  onCreated,
}: {
  open: boolean
  onClose: () => void
  onCreated: () => void | Promise<void>
}) {
  const [form, setForm] = useState<NodeCreateRequest>({
    name: '',
    ssh_host: '',
    ssh_user: '',
    ssh_port: undefined,
    identity_file: '',
    apr_command: 'svcctl',
  })
  const [error, setError] = useState<unknown>(null)

  const mut = useMutation({
    mutationFn: () =>
      api.createNode({
        name: form.name.trim(),
        ssh_host: form.ssh_host.trim(),
        ssh_user: form.ssh_user?.trim() || null,
        ssh_port: form.ssh_port || null,
        identity_file: form.identity_file?.trim() || null,
        apr_command: form.apr_command?.trim() || 'svcctl',
      }),
    onSuccess: async () => {
      setError(null)
      setForm({
        name: '',
        ssh_host: '',
        ssh_user: '',
        ssh_port: undefined,
        identity_file: '',
        apr_command: 'svcctl',
      })
      await onCreated()
    },
    onError: (err) => setError(err),
  })

  return (
    <Modal open={open} onClose={onClose} title="添加从节点" hint="需已配置 SSH 密钥登录（BatchMode）">
      <div className="space-y-3 px-1 pb-1">
        <div>
          <FieldLabel>显示名称</FieldLabel>
          <TextInput
            value={form.name}
            onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
            placeholder="lab-box"
          />
        </div>
        <div className="grid gap-3 sm:grid-cols-2">
          <div>
            <FieldLabel>SSH 主机</FieldLabel>
            <TextInput
              value={form.ssh_host}
              onChange={(e) => setForm((f) => ({ ...f, ssh_host: e.target.value }))}
              placeholder="192.168.1.50 或 host.local"
            />
          </div>
          <div>
            <FieldLabel hint="可选">用户</FieldLabel>
            <TextInput
              value={form.ssh_user ?? ''}
              onChange={(e) => setForm((f) => ({ ...f, ssh_user: e.target.value }))}
              placeholder="默认当前用户"
            />
          </div>
        </div>
        <div className="grid gap-3 sm:grid-cols-2">
          <div>
            <FieldLabel hint="可选">端口</FieldLabel>
            <TextInput
              type="number"
              value={form.ssh_port ?? ''}
              onChange={(e) =>
                setForm((f) => ({
                  ...f,
                  ssh_port: e.target.value ? Number(e.target.value) : undefined,
                }))
              }
              placeholder="22"
            />
          </div>
          <div>
            <FieldLabel hint="可选">私钥路径</FieldLabel>
            <TextInput
              value={form.identity_file ?? ''}
              onChange={(e) => setForm((f) => ({ ...f, identity_file: e.target.value }))}
              placeholder="~/.ssh/id_ed25519"
            />
          </div>
        </div>
        <div>
          <FieldLabel hint="从节点上的可执行方式">apr_command</FieldLabel>
          <TextInput
            value={form.apr_command ?? 'svcctl'}
            onChange={(e) => setForm((f) => ({ ...f, apr_command: e.target.value }))}
            placeholder="svcctl 或 uv run svcctl"
          />
        </div>
        {error != null && <FormError error={error} />}
        <div className="flex justify-end gap-2 pt-1">
          <Button variant="ghost" onClick={onClose}>
            取消
          </Button>
          <Button
            variant="primary"
            disabled={!form.name.trim() || !form.ssh_host.trim() || mut.isPending}
            onClick={() => mut.mutate()}
          >
            {mut.isPending ? '添加中…' : '添加'}
          </Button>
        </div>
      </div>
    </Modal>
  )
}
