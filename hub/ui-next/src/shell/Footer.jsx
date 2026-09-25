import { Wifi, WifiOff, Clock, Monitor, Smartphone } from 'lucide-react'
import { cn } from 'cn'
import { useUserStore, useShellStore } from '@/lib/store'
import { roamApps } from '@/lib/registry'
import { useState, useEffect } from 'react'
import {
  Tooltip,
  TooltipTrigger,
  TooltipContent,
  TooltipProvider,
} from '@/components/ui/tooltip'

export default function Footer() {
  const user = useUserStore((s) => s.user)
  const activeApp = useShellStore((s) => s.activeApp)
  const floorMode = useShellStore((s) => s.floorMode)
  const toggleFloorMode = useShellStore((s) => s.toggleFloorMode)
  const [time, setTime] = useState(new Date())
  const [online, setOnline] = useState(navigator.onLine)

  const showFloorToggle = roamApps.includes(activeApp)

  useEffect(() => {
    const interval = setInterval(() => setTime(new Date()), 60000)
    const handleOnline = () => setOnline(true)
    const handleOffline = () => setOnline(false)
    window.addEventListener('online', handleOnline)
    window.addEventListener('offline', handleOffline)
    return () => {
      clearInterval(interval)
      window.removeEventListener('online', handleOnline)
      window.removeEventListener('offline', handleOffline)
    }
  }, [])

  const timeStr = time.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })

  return (
    <TooltipProvider delay={300}>
      <footer className="flex items-center h-7 px-4 border-t border-border bg-card shrink-0 gap-4 text-[11px] text-muted-foreground">
        {/* Left — status */}
        <div className="flex items-center gap-2">
          {online ? (
            <Wifi className="size-3 text-emerald-500" />
          ) : (
            <WifiOff className="size-3 text-destructive" />
          )}
          <span>{online ? 'Connected' : 'Offline'}</span>
        </div>

        {/* Floor mode toggle */}
        {showFloorToggle && (
          <>
            <div className="w-px h-3 bg-border" />
            <Tooltip>
              <TooltipTrigger asChild>
                <button
                  onClick={toggleFloorMode}
                  className={cn(
                    'flex items-center gap-1.5 px-2 py-0.5 rounded transition-colors',
                    floorMode
                      ? 'bg-primary/20 text-primary'
                      : 'hover:bg-accent hover:text-foreground'
                  )}
                >
                  {floorMode ? (
                    <Smartphone className="size-3" />
                  ) : (
                    <Monitor className="size-3" />
                  )}
                  <span>{floorMode ? 'Floor Mode' : 'Desk Mode'}</span>
                </button>
              </TooltipTrigger>
              <TooltipContent side="top">
                {floorMode ? 'Switch to desk view' : 'Switch to floor/scanner view'}
              </TooltipContent>
            </Tooltip>
          </>
        )}

        {/* Center — spacer */}
        <div className="flex-1" />

        {/* Right — user + time */}
        <div className="flex items-center gap-3">
          {user && (
            <span>
              {user.displayName} <span className="text-muted-foreground/60">({user.role})</span>
            </span>
          )}
          <div className="flex items-center gap-1">
            <Clock className="size-3" />
            <span>{timeStr}</span>
          </div>
        </div>
      </footer>
    </TooltipProvider>
  )
}
