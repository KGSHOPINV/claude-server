import { useEffect } from 'react'
import { useLocation, Outlet } from 'react-router-dom'
import { cn } from 'cn'
import { PanelLeftOpen, PanelLeftClose, PanelRightOpen, PanelRightClose } from 'lucide-react'
import { useShellStore, useTabStore } from '@/lib/store'
import { findNavItem } from '@/lib/registry'
import AppRail from './AppRail'
import AppLauncher from './AppLauncher'
import AppNav from './AppNav'
import Header from './Header'
import ContextPane from './ContextPane'
import WidgetBar from './WidgetBar'
import Footer from './Footer'

export default function Shell({ children }) {
  const navCollapsed = useShellStore((s) => s.navCollapsed)
  const contextOpen = useShellStore((s) => s.contextOpen)
  const toggleNav = useShellStore((s) => s.toggleNav)
  const toggleContext = useShellStore((s) => s.toggleContext)

  const location = useLocation()

  // When navigating, update the ACTIVE tab (don't create a new one)
  // New tabs only created via the + button
  useEffect(() => {
    const navItem = findNavItem(location.pathname)
    if (!navItem) return
    const timer = setTimeout(() => {
      useTabStore.getState().updateActiveTab({
        id: navItem.id,
        path: location.pathname,
        label: navItem.label,
        iconId: navItem.id,
        appId: navItem.appId,
      })
    }, 50)
    return () => clearTimeout(timer)
  }, [location.pathname])

  return (
    <div className="flex h-screen w-screen overflow-hidden bg-background text-foreground">
      {/* iOS-style app launcher overlay */}
      <AppLauncher />

      {/* Far left — always visible rail */}
      <AppRail />

      {/* Collapsible left nav */}
      <div
        className={cn(
          'relative transition-all duration-200 overflow-hidden shrink-0',
          navCollapsed ? 'w-0' : 'w-60'
        )}
      >
        <AppNav />
      </div>

      {/* Expand nav handle (visible when collapsed) */}
      {navCollapsed && (
        <button
          onClick={toggleNav}
          className="shrink-0 flex flex-col items-center justify-center gap-1 w-7 hover:bg-accent border-r border-border text-muted-foreground hover:text-foreground transition-colors"
          aria-label="Open navigation"
          title="Open navigation"
        >
          <PanelLeftOpen className="size-4" />
        </button>
      )}

      {/* Center column */}
      <div className="flex flex-col flex-1 min-w-0 overflow-hidden">
        <Header />
        <main className="flex-1 overflow-auto">
          {children ?? <Outlet />}
        </main>
        <Footer />
      </div>

      {/* Expand context handle (visible when collapsed) */}
      {!contextOpen && (
        <button
          onClick={toggleContext}
          className="shrink-0 flex flex-col items-center justify-center gap-1 w-7 hover:bg-accent border-l border-border text-muted-foreground hover:text-foreground transition-colors"
          aria-label="Open context pane"
          title="Open context pane"
        >
          <PanelRightOpen className="size-4" />
        </button>
      )}

      {/* Right inner — collapsible context pane */}
      <div
        className={cn(
          'transition-all duration-200 overflow-hidden shrink-0',
          contextOpen ? 'w-72' : 'w-0'
        )}
      >
        <ContextPane />
      </div>

      {/* Far right — widget bar */}
      <WidgetBar />
    </div>
  )
}
