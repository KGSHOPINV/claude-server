import { useNavigate } from 'react-router-dom'
import { X, Pin, Plus } from 'lucide-react'
import { cn } from 'cn'
import { useTabStore } from '@/lib/store'
import { Button } from '@/components/ui/button'

export default function WorkspaceTabs() {
  const navigate = useNavigate()
  const tabs = useTabStore((s) => s.tabs)
  const activeTabId = useTabStore((s) => s.activeTabId)
  const closeTab = useTabStore((s) => s.closeTab)
  const setActiveTab = useTabStore((s) => s.setActiveTab)

  // Don't render if no tabs — nav handles routing without tabs
  if (tabs.length === 0) return null

  function handleTabClick(tab) {
    setActiveTab(tab.id)
    navigate(tab.path)
  }

  function handleClose(e, tabId) {
    e.stopPropagation()
    closeTab(tabId)
  }

  return (
    <div className="h-9 flex items-center border-b border-border bg-card/50 shrink-0 overflow-hidden">
      <div className="flex-1 min-w-0 overflow-hidden">
        <div className="flex items-end h-9 gap-0.5 px-1 overflow-x-auto scrollbar-none">
          {tabs.map((tab) => {
            const Icon = tab.icon
            const isActive = tab.id === activeTabId
            return (
              <button
                key={tab.id}
                onClick={() => handleTabClick(tab)}
                className={cn(
                  'group flex items-center gap-1.5 h-8 px-3 rounded-t-md text-sm whitespace-nowrap shrink-0',
                  'border border-b-0 transition-all duration-150',
                  isActive
                    ? 'bg-background text-foreground border-border'
                    : 'bg-transparent text-muted-foreground border-transparent hover:bg-accent/50 hover:text-foreground'
                )}
              >
                {tab.pinned && <Pin className="size-3 text-muted-foreground shrink-0" />}
                {Icon && !tab.pinned && <Icon className="size-3.5 shrink-0" />}
                <span className="max-w-32 truncate">{tab.label}</span>
                {!tab.pinned && (
                  <button
                    onClick={(e) => handleClose(e, tab.id)}
                    className={cn(
                      'flex items-center justify-center size-4 rounded hover:bg-accent shrink-0',
                      'opacity-0 group-hover:opacity-100 transition-opacity',
                      isActive && 'opacity-60 hover:opacity-100'
                    )}
                    aria-label={`Close ${tab.label}`}
                  >
                    <X className="size-3" />
                  </button>
                )}
              </button>
            )
          })}
        </div>
      </div>

      <div className="flex items-center px-1 shrink-0">
        <Button variant="ghost" size="icon" className="size-7" aria-label="New tab">
          <Plus className="size-4" />
        </Button>
      </div>
    </div>
  )
}
