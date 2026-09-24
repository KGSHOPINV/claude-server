import { useNavigate, useLocation } from 'react-router-dom'
import { cn } from 'cn'
import { LogOut, ChevronRight } from 'lucide-react'
import { useShellStore, useUserStore } from '@/lib/store'
import { apps, getNavGroups } from '@/lib/registry'
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
} from '@/components/ui/sheet'
import { ScrollArea } from '@/components/ui/scroll-area'

/**
 * MobileMenu — slide-in drawer from left.
 * Full nav tree + app switcher + user actions.
 */
export default function MobileMenu({ open, onClose }) {
  const navigate = useNavigate()
  const location = useLocation()
  const activeApp = useShellStore((s) => s.activeApp)
  const setActiveApp = useShellStore((s) => s.setActiveApp)
  const user = useUserStore((s) => s.user)
  const facility = useUserStore((s) => s.facility)
  const logout = useUserStore((s) => s.logout)

  const displayName = user?.displayName ?? user?.username ?? 'Guest'
  const role = user?.role ?? 'viewer'
  const facilityName = facility?.name ?? 'No Facility'
  const groups = getNavGroups(activeApp)

  function handleNav(path) {
    navigate(path)
    onClose()
  }

  function handleAppSwitch(appId) {
    setActiveApp(appId)
    // Navigate to that app's dashboard
    const appDashboards = {
      catalog: '/ops/dashboard',
      business: '/biz/dashboard',
      operations: '/ops/dashboard',
      truck: '/truck/dashboard',
      portal: '/portal/dashboard',
      console: '/console/tables',
    }
    navigate(appDashboards[appId] || '/ops/dashboard')
    onClose()
  }

  function handleLogout() {
    logout()
    navigate('/login')
    onClose()
  }

  return (
    <Sheet open={open} onOpenChange={(val) => { if (!val) onClose() }}>
      <SheetContent side="left" showCloseButton={false} className="w-[280px] p-0 flex flex-col">
        {/* User header */}
        <SheetHeader className="border-b border-border px-4 py-4 gap-1">
          <div className="flex items-center gap-3">
            <div className="flex items-center justify-center size-10 rounded-full bg-primary text-primary-foreground text-sm font-bold shrink-0">
              {displayName.charAt(0).toUpperCase()}
            </div>
            <div className="flex flex-col min-w-0">
              <SheetTitle className="text-sm font-semibold truncate">{displayName}</SheetTitle>
              <span className="text-xs text-muted-foreground capitalize">{role}</span>
              <span className="text-[10px] text-muted-foreground truncate">{facilityName}</span>
            </div>
          </div>
        </SheetHeader>

        {/* App switcher */}
        <div className="border-b border-border px-2 py-2">
          <div className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground px-2 pb-1">
            Apps
          </div>
          <div className="flex flex-wrap gap-1">
            {apps.map((app) => {
              const Icon = app.icon
              const isActive = activeApp === app.id
              return (
                <button
                  key={app.id}
                  onClick={() => handleAppSwitch(app.id)}
                  className={cn(
                    'flex items-center gap-1.5 px-2.5 py-1.5 rounded-md text-xs transition-colors min-h-[44px]',
                    isActive
                      ? 'bg-primary/10 text-primary font-semibold'
                      : 'text-muted-foreground hover:text-foreground hover:bg-accent'
                  )}
                >
                  <Icon className="size-4" />
                  <span>{app.label}</span>
                </button>
              )
            })}
          </div>
        </div>

        {/* Full nav tree */}
        <ScrollArea className="flex-1">
          <div className="px-2 py-2">
            {groups.map((group) => {
              const key = group.label ?? '__ungrouped'
              return (
                <div key={key} className="mb-2">
                  {group.label && (
                    <div className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground px-2 py-1.5">
                      {group.label}
                    </div>
                  )}
                  <div className="flex flex-col gap-0.5">
                    {group.items.map((item) => {
                      const Icon = item.icon
                      const active = location.pathname === item.path
                      return (
                        <button
                          key={item.id}
                          onClick={() => handleNav(item.path)}
                          className={cn(
                            'flex items-center gap-3 w-full px-3 py-2.5 rounded-md text-sm transition-colors text-left min-h-[44px]',
                            active
                              ? 'bg-accent text-foreground font-medium'
                              : 'text-muted-foreground active:bg-accent active:text-foreground'
                          )}
                        >
                          {Icon && <Icon className="size-4 shrink-0" />}
                          <span className="flex-1 truncate">{item.label}</span>
                          <ChevronRight className="size-3.5 text-muted-foreground/50" />
                        </button>
                      )
                    })}
                  </div>
                </div>
              )
            })}
          </div>
        </ScrollArea>

        {/* Footer — logout */}
        <div className="border-t border-border px-2 py-2" style={{ paddingBottom: 'env(safe-area-inset-bottom, 0px)' }}>
          <button
            onClick={handleLogout}
            className="flex items-center gap-3 w-full px-3 py-2.5 rounded-md text-sm text-destructive hover:bg-destructive/10 transition-colors min-h-[44px]"
          >
            <LogOut className="size-4" />
            <span>Sign out</span>
          </button>
        </div>
      </SheetContent>
    </Sheet>
  )
}
