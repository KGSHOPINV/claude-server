import { useShellStore } from '@/lib/store'
import { apps } from '@/lib/registry'
import { cn } from 'cn'
import { X } from 'lucide-react'

export default function AppLauncher() {
  const open = useShellStore((s) => s.launcherOpen)
  const closeLauncher = useShellStore((s) => s.closeLauncher)
  const activeApp = useShellStore((s) => s.activeApp)
  const setActiveApp = useShellStore((s) => s.setActiveApp)

  if (!open) return null

  function handleSelect(appId) {
    setActiveApp(appId)
    closeLauncher()
  }

  return (
    <>
      {/* Backdrop */}
      <div
        className="fixed inset-0 z-50 bg-black/60 backdrop-blur-sm"
        onClick={closeLauncher}
      />

      {/* Launcher panel */}
      <div className="fixed inset-0 z-50 flex items-center justify-center p-8">
        <div
          className="relative w-full max-w-md rounded-2xl border border-border bg-card p-8 shadow-2xl"
          onClick={(e) => e.stopPropagation()}
        >
          {/* Close */}
          <button
            onClick={closeLauncher}
            className="absolute top-4 right-4 text-muted-foreground hover:text-foreground transition-colors"
          >
            <X className="size-5" />
          </button>

          {/* Title */}
          <div className="mb-6">
            <h2 className="text-lg font-semibold text-foreground">Applications</h2>
            <p className="text-sm text-muted-foreground mt-1">Switch workspace</p>
          </div>

          {/* App grid */}
          <div className="grid grid-cols-2 gap-4">
            {apps.map((app) => {
              const Icon = app.icon
              const isActive = activeApp === app.id
              return (
                <button
                  key={app.id}
                  onClick={() => handleSelect(app.id)}
                  className={cn(
                    'flex flex-col items-center gap-3 p-6 rounded-xl border transition-all duration-150',
                    'hover:bg-accent hover:border-accent-foreground/20',
                    isActive
                      ? 'bg-accent border-primary/30 ring-1 ring-primary/20'
                      : 'border-border bg-background'
                  )}
                >
                  <div className={cn(
                    'flex items-center justify-center size-12 rounded-xl',
                    isActive ? 'bg-primary text-primary-foreground' : 'bg-muted text-muted-foreground'
                  )}>
                    <Icon className="size-6" />
                  </div>
                  <span className={cn(
                    'text-sm font-medium',
                    isActive ? 'text-foreground' : 'text-muted-foreground'
                  )}>
                    {app.label}
                  </span>
                </button>
              )
            })}
          </div>
        </div>
      </div>
    </>
  )
}
