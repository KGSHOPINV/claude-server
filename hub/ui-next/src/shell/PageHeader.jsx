import { useLocation } from 'react-router-dom'
import { ChevronRight } from 'lucide-react'
import { cn } from 'cn'
import { useShellStore } from '@/lib/store'
import { useTabStore } from '@/lib/store'
import { findNavItem } from '@/lib/registry'

// Derive breadcrumb segments from the current route path.
// Example: /ops/receive → ['Operations', 'Receive']
function useBreadcrumb() {
  const location = useLocation()
  const activeApp = useShellStore((s) => s.activeApp)
  const tabs = useTabStore((s) => s.tabs)
  const activeTabId = useTabStore((s) => s.activeTabId)

  const activeTab = tabs.find((t) => t.id === activeTabId)

  // App label map
  const appLabels = {
    operations: 'Operations',
    truck: 'Truck',
    management: 'Management',
    portal: 'Portal',
    console: 'Console',
  }

  const appLabel = appLabels[activeApp] ?? activeApp

  // Try to find nav item for current path
  const navItem = findNavItem(location.pathname)
  const pageLabel = activeTab?.label ?? navItem?.label ?? location.pathname.split('/').filter(Boolean).pop() ?? 'Page'

  // Build segments
  const segments = [appLabel]
  if (navItem?.group) segments.push(navItem.group)
  segments.push(pageLabel)

  return { segments, pageLabel }
}

export default function PageHeader({ actions, className }) {
  const { segments, pageLabel } = useBreadcrumb()

  return (
    <div
      className={cn(
        'flex items-center h-10 px-4 border-b border-border bg-background shrink-0 gap-3',
        className
      )}
    >
      {/* Breadcrumb */}
      <nav className="flex items-center gap-1 flex-1 min-w-0" aria-label="Breadcrumb">
        {segments.map((seg, i) => {
          const isLast = i === segments.length - 1
          return (
            <span key={i} className="flex items-center gap-1 min-w-0">
              {i > 0 && (
                <ChevronRight className="size-3 text-muted-foreground shrink-0" />
              )}
              <span
                className={cn(
                  'text-sm truncate',
                  isLast
                    ? 'text-foreground font-medium'
                    : 'text-muted-foreground'
                )}
              >
                {seg}
              </span>
            </span>
          )
        })}
      </nav>

      {/* Action buttons slot */}
      {actions && (
        <div className="flex items-center gap-2 shrink-0">
          {actions}
        </div>
      )}
    </div>
  )
}
