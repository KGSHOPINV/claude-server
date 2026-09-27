import { useNavigate, useLocation } from 'react-router-dom'
import { LogOut, Settings, ChevronDown, ChevronRight, PanelRight, X, Pin, Plus, Bell, Wifi, User, Circle, Moon, MinusCircle, WifiOff as StatusOff } from 'lucide-react'
import { cn } from 'cn'
import { useUserStore, useShellStore, useTabStore } from '@/lib/store'
import { apps, navTree, findNavItem } from '@/lib/registry'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuLabel,
} from '@/components/ui/dropdown-menu'

function getTabIcon(tabId) {
  for (const items of Object.values(navTree)) {
    const match = items.find(i => i.id === tabId)
    if (match?.icon) return match.icon
  }
  return null
}

function useBreadcrumb() {
  const location = useLocation()
  const activeApp = useShellStore((s) => s.activeApp)
  const activeTabId = useTabStore((s) => s.activeTabId)
  const tabs = useTabStore((s) => s.tabs)

  const appLabels = {
    catalog: 'Catalog', business: 'Business', operations: 'Operations',
    truck: 'Truck', portal: 'Portal', console: 'Console',
  }
  const appLabel = appLabels[activeApp] ?? activeApp
  const navItem = findNavItem(location.pathname)
  const activeTab = tabs.find(t => t.id === activeTabId)
  const pageLabel = activeTab?.label ?? navItem?.label ?? location.pathname.split('/').filter(Boolean).pop() ?? 'Page'

  const segments = [appLabel]
  if (navItem?.group) segments.push(navItem.group)
  segments.push(pageLabel)
  return { segments, pageLabel }
}

export default function Header() {
  const navigate = useNavigate()
  const location = useLocation()
  const user = useUserStore((s) => s.user)
  const logout = useUserStore((s) => s.logout)
  const activeApp = useShellStore((s) => s.activeApp)
  const contextOpen = useShellStore((s) => s.contextOpen)
  const toggleContext = useShellStore((s) => s.toggleContext)

  const tabs = useTabStore((s) => s.tabs)
  const activeTabId = useTabStore((s) => s.activeTabId)
  const closeTab = useTabStore((s) => s.closeTab)
  const setActiveTab = useTabStore((s) => s.setActiveTab)
  const openTab = useTabStore((s) => s.openTab)

  const userStatus = useShellStore((s) => s.userStatus)
  const setUserStatus = useShellStore((s) => s.setUserStatus)

  const displayName = user?.displayName ?? user?.username ?? 'Guest'
  const role = user?.role ?? 'viewer'
  const appLabel = apps.find(a => a.id === activeApp)?.label ?? activeApp

  const statusOptions = [
    { value: 'online',  label: 'Online',  color: 'text-emerald-500' },
    { value: 'away',    label: 'Away',    color: 'text-amber-500' },
    { value: 'busy',    label: 'Busy',    color: 'text-red-500' },
    { value: 'offline', label: 'Offline', color: 'text-muted-foreground' },
  ]
  const currentStatus = statusOptions.find(s => s.value === userStatus) || statusOptions[0]
  const { segments, pageLabel } = useBreadcrumb()

  function handleTabClick(tab) {
    setActiveTab(tab.id)
    navigate(tab.path)
  }

  function handleClose(e, tabId) {
    e.stopPropagation()
    closeTab(tabId)
    const state = useTabStore.getState()
    const next = state.tabs.find(t => t.id === state.activeTabId)
    if (next) navigate(next.path)
  }

  function handleNewTab() {
    openTab({
      id: 'ops-dashboard',
      path: '/ops/dashboard',
      label: 'Dashboard',
      iconId: 'ops-dashboard',
      appId: 'operations',
    })
    navigate('/ops/dashboard')
  }

  return (
    <div className="flex flex-col shrink-0">

      {/* ROW 1 — Global bar: brand + status/notifications/clock + user */}
      <div className="flex items-center h-10 border-b border-border bg-card">
        {/* Left — brand */}
        <div className="flex items-center gap-2 px-3 shrink-0">
          <span className="font-bold text-sm tracking-wider text-foreground">FK</span>
          <span className="text-[10px] text-muted-foreground font-medium uppercase tracking-wide">
            {appLabel}
          </span>
        </div>

        <div className="w-px h-5 bg-border shrink-0" />

        {/* Center — notifications + status */}
        <div className="flex-1 flex items-center gap-4 px-3 min-w-0">
          <button className="flex items-center gap-1.5 text-muted-foreground hover:text-foreground transition-colors">
            <Bell className="size-3.5" />
            <span className="text-[10px]">0</span>
          </button>
          <div className="flex items-center gap-1.5 text-muted-foreground">
            <Wifi className="size-3.5 text-emerald-500" />
            <span className="text-[10px]">Online</span>
          </div>
        </div>

        {/* Right — clock + context toggle + user */}
        <div className="flex items-center gap-2 px-2 shrink-0">
          <HeaderClock />

          <div className="w-px h-4 bg-border" />

          <Button
            variant="ghost"
            size="icon"
            className="size-7"
            onClick={toggleContext}
            aria-label="Toggle context pane"
          >
            <PanelRight className={cn('size-3.5', contextOpen && 'text-primary')} />
          </Button>

          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="ghost" size="sm" className="flex items-center gap-1.5 h-7 px-1.5">
                <div className="relative">
                  <div className="flex items-center justify-center size-5 rounded-full bg-primary text-primary-foreground text-[9px] font-bold">
                    {displayName.charAt(0).toUpperCase()}
                  </div>
                  <Circle className={cn('absolute -bottom-0.5 -right-0.5 size-2.5 fill-current', currentStatus.color)} />
                </div>
                <span className="text-xs text-muted-foreground hidden sm:inline">{displayName}</span>
                <ChevronDown className="size-3 text-muted-foreground" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" side="bottom" className="w-52">
              <DropdownMenuLabel>
                <div className="flex flex-col">
                  <span className="font-medium">{displayName}</span>
                  <span className="text-xs text-muted-foreground capitalize">{role}</span>
                </div>
              </DropdownMenuLabel>
              <DropdownMenuSeparator />
              <DropdownMenuLabel className="text-[10px] text-muted-foreground uppercase tracking-wide font-normal">
                Status
              </DropdownMenuLabel>
              {statusOptions.map((opt) => (
                <DropdownMenuItem
                  key={opt.value}
                  onClick={() => setUserStatus(opt.value)}
                  className={cn(userStatus === opt.value && 'bg-accent')}
                >
                  <Circle className={cn('size-3 fill-current', opt.color)} />
                  {opt.label}
                </DropdownMenuItem>
              ))}
              <DropdownMenuSeparator />
              <DropdownMenuItem onClick={() => navigate('/ops/dashboard')}>
                <User className="size-4" />
                My Profile
              </DropdownMenuItem>
              <DropdownMenuItem onClick={() => navigate('/mgmt/settings')}>
                <Settings className="size-4" />
                Settings
              </DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuItem variant="destructive" onClick={logout}>
                <LogOut className="size-4" />
                Sign out
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </div>

      {/* ROW 2 — Tab bar: workspace tabs only */}
      <div className="flex items-end h-9 border-b border-border bg-card/50">
        <div className="flex items-end h-9 gap-0.5 px-1 overflow-x-auto scrollbar-none flex-1 min-w-0">
          {tabs.map((tab) => {
            const Icon = getTabIcon(tab.id || tab.iconId)
            const isActive = tab.id === activeTabId
            return (
              <button
                key={tab.id}
                onClick={() => handleTabClick(tab)}
                className={cn(
                  'group flex items-center gap-1.5 h-8 w-36 px-3 rounded-t-md text-xs whitespace-nowrap shrink-0',
                  'border border-b-0 mt-auto',
                  isActive
                    ? 'bg-background text-foreground border-border'
                    : 'bg-transparent text-muted-foreground border-transparent hover:bg-accent/50 hover:text-foreground'
                )}
              >
                {tab.pinned && <Pin className="size-3 text-muted-foreground shrink-0" />}
                {Icon && !tab.pinned && <Icon className="size-3 shrink-0" />}
                <span className="max-w-28 truncate">{tab.label}</span>
                {!tab.pinned && (
                  <button
                    onClick={(e) => handleClose(e, tab.id)}
                    className={cn(
                      'flex items-center justify-center size-3.5 rounded hover:bg-accent shrink-0',
                      'opacity-0 group-hover:opacity-100 transition-opacity',
                      isActive && 'opacity-60 hover:opacity-100'
                    )}
                    aria-label={`Close ${tab.label}`}
                  >
                    <X className="size-2.5" />
                  </button>
                )}
              </button>
            )
          })}
          <button
            className="flex items-center justify-center size-6 mt-auto mb-0.5 rounded hover:bg-accent text-muted-foreground hover:text-foreground shrink-0"
            aria-label="New tab"
            title="Open new tab"
            onClick={handleNewTab}
          >
            <Plus className="size-3.5" />
          </button>
        </div>
      </div>

      {/* ROW 3 — Page bar: breadcrumb + page title (compact) */}
      <div className="flex items-center h-6 px-4 border-b border-border bg-background gap-2">
        <nav className="flex items-center gap-1 min-w-0" aria-label="Breadcrumb">
          {segments.slice(0, -1).map((seg, i) => (
            <span key={i} className="flex items-center gap-1 min-w-0">
              {i > 0 && <ChevronRight className="size-2.5 text-muted-foreground shrink-0" />}
              <span className="text-[10px] text-muted-foreground truncate">{seg}</span>
            </span>
          ))}
          <ChevronRight className="size-2.5 text-muted-foreground shrink-0" />
        </nav>
        <span className="text-xs font-medium text-foreground truncate">{pageLabel}</span>
        <div className="flex-1" />
      </div>

      {/* ROW 4 lives in page templates — sub-tabs per page (Detail/History/Notes etc.) */}
    </div>
  )
}

function HeaderClock() {
  const now = new Date()
  const time = now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
  return <span className="text-[10px] text-muted-foreground tabular-nums">{time}</span>
}
