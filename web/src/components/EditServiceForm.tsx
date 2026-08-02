import { useEffect, useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import {
  api,
  invalidateServiceViews,
  type Service,
  type ServiceUpdateRequest,
} from '../lib/api'
import {
  Button,
  FieldLabel,
  FormError,
  Modal,
  TextInput,
  TextTextarea,
} from './ui'

interface Props {
  open: boolean
  onClose: () => void
  service: Service
}

export default function EditServiceForm({ open, onClose, service }: Props) {
  const qc = useQueryClient()
  const [name, setName] = useState(service.name)
  const [description, setDescription] = useState(service.description ?? '')
  const [codePath, setCodePath] = useState(service.code_path ?? '')
  const [workingDirectory, setWorkingDirectory] = useState(service.working_directory ?? '')
  const [startCommand, setStartCommand] = useState(service.start_command ?? '')

  const mutation = useMutation({
    mutationFn: (body: ServiceUpdateRequest) => api.patchService(service.id, body),
    onMutate: async (body) => {
      await qc.cancelQueries({ queryKey: ['service', service.id] })
      const previous = qc.getQueryData<Service>(['service', service.id])
      if (previous) {
        qc.setQueryData<Service>(['service', service.id], {
          ...previous,
          name: body.name ?? previous.name,
          description: body.description ?? previous.description,
          code_path: body.code_path ?? previous.code_path,
          working_directory: body.working_directory ?? previous.working_directory,
          start_command: body.start_command ?? previous.start_command,
        })
      }
      return { previous }
    },
    onError: (_err, _body, ctx) => {
      if (ctx?.previous) {
        qc.setQueryData(['service', service.id], ctx.previous)
      }
    },
    onSuccess: async () => {
      await invalidateServiceViews(qc, service.id)
      onClose()
    },
  })

  useEffect(() => {
    if (!open) return
    setName(service.name)
    setDescription(service.description ?? '')
    setCodePath(service.code_path ?? '')
    setWorkingDirectory(service.working_directory ?? '')
    setStartCommand(service.start_command ?? '')
    mutation.reset()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, service.id])

  const submit = (e: React.FormEvent) => {
    e.preventDefault()
    mutation.mutate({
      name: name.trim() || service.service_key,
      description: description.trim() || null,
      code_path: codePath.trim() || null,
      working_directory: workingDirectory.trim() || null,
      start_command: startCommand.trim() || null,
    })
  }

  return (
    <Modal
      open={open}
      onClose={mutation.isPending ? () => undefined : onClose}
      title="编辑服务元数据"
      hint="标识（agent / project / key / instance）创建后不可改"
    >
      <form onSubmit={submit} className="space-y-3">
        <div>
          <FieldLabel htmlFor="edit-name">显示名称</FieldLabel>
          <TextInput
            id="edit-name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            disabled={mutation.isPending}
          />
        </div>
        <div>
          <FieldLabel htmlFor="edit-desc">描述</FieldLabel>
          <TextInput
            id="edit-desc"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            disabled={mutation.isPending}
          />
        </div>
        <div>
          <FieldLabel htmlFor="edit-code">代码路径</FieldLabel>
          <TextInput
            id="edit-code"
            value={codePath}
            onChange={(e) => setCodePath(e.target.value)}
            className="font-mono"
            disabled={mutation.isPending}
          />
        </div>
        <div>
          <FieldLabel htmlFor="edit-cwd">工作目录</FieldLabel>
          <TextInput
            id="edit-cwd"
            value={workingDirectory}
            onChange={(e) => setWorkingDirectory(e.target.value)}
            className="font-mono"
            disabled={mutation.isPending}
          />
        </div>
        <div>
          <FieldLabel htmlFor="edit-cmd" hint="支持 {{ports.http}}">
            启动命令
          </FieldLabel>
          <TextTextarea
            id="edit-cmd"
            value={startCommand}
            onChange={(e) => setStartCommand(e.target.value)}
            disabled={mutation.isPending}
          />
        </div>

        {mutation.isError && <FormError error={mutation.error} />}

        <div className="flex justify-end gap-2 border-t border-line-soft pt-4">
          <Button type="button" variant="ghost" onClick={onClose} disabled={mutation.isPending}>
            取消
          </Button>
          <Button type="submit" variant="primary" disabled={mutation.isPending}>
            {mutation.isPending ? '保存中…' : '保存'}
          </Button>
        </div>
      </form>
    </Modal>
  )
}
