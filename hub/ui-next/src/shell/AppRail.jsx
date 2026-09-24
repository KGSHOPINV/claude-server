import { cn } from 'cn'
import { LayoutGrid } from 'lucide-react'
import { useShellStore } from '@/lib/store'
import { apps, navTree } from '@/lib/registry'
import {
  Tooltip,
  TooltipTrigger,
  TooltipContent,
  TooltipProvider,
} from '@/components/ui/tooltip'

export default function AppRail() {
  const activeApp = useShellStore((s) => s.activeApp)
  const setActiveApp = useShellStore((s) => s.setActiveApp)
  const toggleLauncher = useShellStore((s) => s.toggleLauncher)

  return (
    <TooltipProvider delay={300}>
      <div className="flex flex-col items-center w-14 shrink-0 h-full bg-rail border-r border-rail-border py-2 gap-1">
        {/* Brand / launcher trigger at top */}
        <Tooltip>
          <TooltipTrigger asChild>
            <button
              onClick={toggleLauncher}
              className="flex items-center justify-center w-9 h-9 mb-1 rounded-lg bg-primary text-primary-foreground font-bold text-xs select-none hover:opacity-90 transition-opacity"
            >
              FK
            </button>
          </TooltipTrigger>
          <TooltipContent side="right">App Launcher</TooltipContent>
        </Tooltip>

        <div className="w-8 h-px bg-rail-border mb-1" />

        {/* App icons */}
        <nav className="flex flex-col items-center gap-1 flex-1 w-full px-1.5">
          {apps.map((app) => {
            const Icon = app.icon
            const isActive = activeApp === app.id
            return (
              <Tooltip key={app.id}>
                <TooltipTrigger asChild>
                  <button
                    onClick={() => setActiveApp(app.id)}
                    className={cn(
                      'flex items-center justify-center w-full h-10 rounded-lg transition-all duration-150',
                      'text-rail-foreground/60 hover:text-rail-foreground hover:bg-rail-accent',
                      isActive && 'bg-rail-accent text-rail-foreground shadow-sm'
                    )}
                    aria-label={app.label}
                  >
                    <Icon className="size-5 shrink-0" />
                  </button>
                </TooltipTrigger>
                <TooltipContent side="right">{app.label}</TooltipContent>
              </Tooltip>
            )
          })}
        </nav>

        <div className="w-8 h-px bg-rail-border mt-1" />

        {/* All apps grid button at bottom */}
        <Tooltip>
          <TooltipTrigger asChild>
            <button
              onClick={toggleLauncher}
              className="flex items-center justify-center w-full h-10 rounded-lg text-rail-foreground/60 hover:text-rail-foreground hover:bg-rail-accent transition-all"
              aria-label="All applications"
            >
              <LayoutGrid className="size-5" />
            </button>
          </TooltipTrigger>
          <TooltipContent side="right">All Apps</TooltipContent>
        </Tooltip>
      </div>
    </TooltipProvider>
  )
}
