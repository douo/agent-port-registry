import { useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { Command } from 'cmdk'
import { Boxes, LayoutDashboard, Network } from 'lucide-react'
import { api, queryKeys } from '../lib/api'
import { serviceAgentLabel, servicePorts, serviceProjectKey } from '../lib/format'

interface Props {
  open: boolean
  onOpenChange: (open: boolean) => void
}

export default function CommandPalette({ open, onOpenChange }: Props) {
  const navigate = useNavigate()
  const { data: services = [] } = useQuery({
    queryKey: queryKeys.services,
    queryFn: api.services,
    enabled: open,
  })

  const items = useMemo(
    () =>
      services.map((service) => ({
        service,
        ports: servicePorts(service),
      })),
    [services],
  )

  const go = (path: string) => {
    onOpenChange(false)
    navigate(path)
  }

  return (
    <Command.Dialog
      open={open}
      onOpenChange={onOpenChange}
      label="命令面板"
      shouldFilter
      overlayClassName="fixed inset-0 z-50 bg-black/60 backdrop-blur-sm"
      contentClassName="fixed left-1/2 top-[15vh] z-50 w-[min(38rem,92vw)] -translate-x-1/2 overflow-hidden rounded-xl border border-line bg-panel shadow-2xl shadow-black/60"
    >
      <Command.Input
        autoFocus
        placeholder="搜索服务、项目或端口号…"
        className="w-full border-b border-line-soft bg-transparent px-4 py-3.5 text-sm text-fg outline-none placeholder:text-faint"
      />
      <Command.List className="max-h-80 overflow-y-auto p-2">
        <Command.Empty className="px-3 py-8 text-center text-sm text-faint">
          没有匹配结果
        </Command.Empty>

        <Command.Group
          heading="导航"
          className="[&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:py-1.5 [&_[cmdk-group-heading]]:text-[11px] [&_[cmdk-group-heading]]:text-faint"
        >
          <Item onSelect={() => go('/')} icon={<LayoutDashboard size={14} />}>
            概览
          </Item>
          <Item onSelect={() => go('/services')} icon={<Boxes size={14} />}>
            服务列表
          </Item>
          <Item onSelect={() => go('/ports')} icon={<Network size={14} />}>
            端口视图
          </Item>
        </Command.Group>

        {items.length > 0 && (
          <Command.Group
            heading="服务"
            className="[&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:py-1.5 [&_[cmdk-group-heading]]:text-[11px] [&_[cmdk-group-heading]]:text-faint"
          >
            {items.map(({ service, ports }) => (
              <Item
                key={service.id}
                // Everything searchable goes into value: cmdk filters on it.
                value={[
                  service.name,
                  service.service_key,
                  serviceProjectKey(service),
                  serviceAgentLabel(service),
                  ...ports.map((p) => String(p.port)),
                ].join(' ')}
                onSelect={() => go(`/services/${service.id}`)}
                icon={<Boxes size={14} />}
              >
                <span className="truncate">{service.name}</span>
                <span className="ml-auto flex shrink-0 items-center gap-1.5">
                  <span className="text-[11px] text-faint">
                    {serviceProjectKey(service)}
                  </span>
                  {ports.map((p) => (
                    <span key={p.port} className="chip">
                      {p.port}
                    </span>
                  ))}
                </span>
              </Item>
            ))}
          </Command.Group>
        )}
      </Command.List>
    </Command.Dialog>
  )
}

function Item({
  children,
  icon,
  value,
  onSelect,
}: {
  children: React.ReactNode
  icon: React.ReactNode
  value?: string
  onSelect: () => void
}) {
  return (
    <Command.Item
      value={value}
      onSelect={onSelect}
      className="flex cursor-pointer items-center gap-2.5 rounded-lg px-2.5 py-2 text-sm text-muted data-[selected=true]:bg-raised data-[selected=true]:text-fg"
    >
      <span className="text-faint">{icon}</span>
      {children}
    </Command.Item>
  )
}
