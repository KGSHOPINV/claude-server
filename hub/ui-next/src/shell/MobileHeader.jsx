import { Menu, ScanLine } from 'lucide-react'
import { useUserStore, useShellStore, useScannerStore } from '@/lib/store'
import { apps } from '@/lib/registry'
import { Button } from '@/components/ui/button'

/**
 * MobileHeader — compact top bar for mobile shell.
 * Hamburger left, app name center, avatar + scan right.
 */
export default function MobileHeader({ onMenuOpen }) {
  const user = useUserStore((s) => s.user)
  const activeApp = useShellStore((s) => s.activeApp)
  const toggleInputMode = useScannerStore((s) => s.toggleInputMode)
  const inputMode = useScannerStore((s) => s.inputMode)

  const displayName = user?.displayName ?? user?.username ?? 'G'
  const initial = displayName.charAt(0).toUpperCase()
  const appLabel = apps.find((a) => a.id === activeApp)?.label ?? activeApp

  return (
    <header
      className="flex items-center h-12 px-3 border-b border-border bg-card shrink-0"
      style={{ paddingTop: 'env(safe-area-inset-top, 0px)' }}
    >
      {/* Left — hamburger */}
      <Button
        variant="ghost"
        size="icon"
        className="size-10 min-w-[44px] min-h-[44px]"
        onClick={onMenuOpen}
        aria-label="Open menu"
      >
        <Menu className="size-5" />
      </Button>

      {/* Center — app name */}
      <div className="flex-1 flex items-center justify-center min-w-0">
        <span className="text-sm font-bold tracking-wider text-foreground uppercase truncate">
          {appLabel}
        </span>
      </div>

      {/* Right — scan + avatar */}
      <div className="flex items-center gap-1">
        <Button
          variant="ghost"
          size="icon"
          className="size-10 min-w-[44px] min-h-[44px]"
          onClick={toggleInputMode}
          aria-label="Toggle scanner"
        >
          <ScanLine className={`size-5 ${inputMode === 'scan' ? 'text-primary' : ''}`} />
        </Button>

        <div className="flex items-center justify-center size-8 rounded-full bg-primary text-primary-foreground text-xs font-bold">
          {initial}
        </div>
      </div>
    </header>
  )
}
