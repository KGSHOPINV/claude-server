import { useState } from 'react'
import {
  ScanLine,
  Bell,
  Plus,
  Activity,
  Clock,
  Wifi,
  User,
} from 'lucide-react'
import { cn } from 'cn'
import { useShellStore } from '@/lib/store'
import {
  Tooltip,
  TooltipTrigger,
  TooltipContent,
  TooltipProvider,
} from '@/components/ui/tooltip'
import LookupWidget from '@/components/widgets/LookupWidget'
import NotificationWidget from '@/components/widgets/NotificationWidget'
import QuickCreateWidget from '@/components/widgets/QuickCreateWidget'
import ActivityWidget from '@/components/widgets/ActivityWidget'
import ClockWidget from '@/components/widgets/ClockWidget'

const WIDGETS = [
  { id: 'scan',          icon: ScanLine,  label: 'Scan'          },
  { id: 'notifications', icon: Bell,      label: 'Notifications' },
  { id: 'quick-create',  icon: Plus,      label: 'Quick Create'  },
  { id: 'activity',      icon: Activity,  label: 'Activity'      },
  { id: 'clock',         icon: Clock,     label: 'Clock'         },
]

const BOTTOM_WIDGETS = [
  { id: 'status', icon: Wifi,  label: 'Status' },
  { id: 'user',   icon: User,  label: 'User'   },
]

export default function WidgetBar() {
  const [activeWidget, setActiveWidget] = useState(null)

  function toggleWidget(id) {
    setActiveWidget((prev) => (prev === id ? null : id))
  }

  function closeWidget() {
    setActiveWidget(null)
  }

  return (
    <TooltipProvider delay={300}>
      <div className="flex flex-col items-center w-14 shrink-0 h-full bg-sidebar border-l border-border py-2 gap-1">
        {/* Top widgets */}
        <div className="flex flex-col items-center gap-1 flex-1 w-full px-1.5">
          {WIDGETS.map((widget) => (
            <WidgetButton
              key={widget.id}
              widget={widget}
              active={activeWidget === widget.id}
              onClick={() => toggleWidget(widget.id)}
            />
          ))}
        </div>

        <div className="w-full h-px bg-border my-1" />

        {/* Bottom widgets */}
        <div className="flex flex-col items-center gap-1 w-full px-1.5">
          {BOTTOM_WIDGETS.map((widget) => (
            <WidgetButton
              key={widget.id}
              widget={widget}
              active={false}
              onClick={() => {}}
            />
          ))}
        </div>
      </div>

      {/* Widget panels */}
      <LookupWidget open={activeWidget === 'scan'} onClose={closeWidget} />
      <NotificationWidget open={activeWidget === 'notifications'} onClose={closeWidget} />
      <QuickCreateWidget open={activeWidget === 'quick-create'} onClose={closeWidget} />
      <ActivityWidget open={activeWidget === 'activity'} onClose={closeWidget} />
      <ClockWidget open={activeWidget === 'clock'} onClose={closeWidget} />
    </TooltipProvider>
  )
}

function WidgetButton({ widget, active, onClick }) {
  const Icon = widget.icon
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <button
          onClick={onClick}
          className={cn(
            'flex items-center justify-center w-full h-10 rounded-md transition-all duration-150',
            active
              ? 'text-foreground bg-accent'
              : 'text-muted-foreground hover:text-foreground hover:bg-accent'
          )}
          aria-label={widget.label}
        >
          <Icon className="size-5 shrink-0" />
        </button>
      </TooltipTrigger>
      <TooltipContent side="left">{widget.label}</TooltipContent>
    </Tooltip>
  )
}
