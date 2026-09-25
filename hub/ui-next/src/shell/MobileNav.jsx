import { useNavigate, useLocation } from 'react-router-dom'
import { cn } from 'cn'
import {
  LayoutDashboard, ScanLine, PackageSearch, ClipboardList, MoreHorizontal,
  Truck, Download, ShoppingBag, Users, Settings, Eye,
} from 'lucide-react'
import { useShellStore } from '@/lib/store'

/**
 * MobileNav — fixed bottom tab bar for mobile shell.
 * 4-5 tabs per app surface. "More" opens the full drawer menu.
 */

// Tab definitions per app — max 5, last is always "More"
const TAB_CONFIGS = {
  operations: [
    { id: 'ops-dashboard',    path: '/ops/dashboard',     label: 'Home',   icon: LayoutDashboard },
    { id: 'ops-scan',         path: '/ops/receive',       label: 'Scan',   icon: ScanLine },
    { id: 'ops-stock',        path: '/ops/stock-search',  label: 'Stock',  icon: PackageSearch },
    { id: 'ops-orders',       path: '/ops/order-manage',  label: 'Orders', icon: ClipboardList },
    { id: 'ops-more',         path: '__more__',           label: 'More',   icon: MoreHorizontal },
  ],
  truck: [
    { id: 'truck-dashboard',  path: '/truck/dashboard',   label: 'Home',   icon: LayoutDashboard },
    { id: 'truck-stock',      path: '/truck/stock',       label: 'Stock',  icon: PackageSearch },
    { id: 'truck-sell',       path: '/truck/sell',        label: 'Sell',   icon: ShoppingBag },
    { id: 'truck-load',       path: '/truck/load',        label: 'Load',   icon: Download },
    { id: 'truck-more',       path: '__more__',           label: 'More',   icon: MoreHorizontal },
  ],
  catalog: [
    { id: 'cat-dashboard',    path: '/ops/dashboard',      label: 'Home',     icon: LayoutDashboard },
    { id: 'cat-search',       path: '/ops/product-search', label: 'Search',   icon: Search },
    { id: 'cat-fitment',      path: '/ops/fitment-search', label: 'Fitment',  icon: Search },
    { id: 'cat-more',         path: '__more__',            label: 'More',     icon: MoreHorizontal },
  ],
  business: [
    { id: 'biz-dashboard',    path: '/biz/dashboard',      label: 'Home',     icon: LayoutDashboard },
    { id: 'biz-orders',       path: '/biz/order-manage',   label: 'Orders',   icon: ClipboardList },
    { id: 'biz-customers',    path: '/biz/customers',      label: 'Clients',  icon: Users },
    { id: 'biz-more',         path: '__more__',            label: 'More',     icon: MoreHorizontal },
  ],
  portal: [
    { id: 'portal-dashboard', path: '/portal/dashboard',  label: 'Home',   icon: LayoutDashboard },
    { id: 'portal-browse',    path: '/portal/browse',     label: 'Browse', icon: Eye },
    { id: 'portal-orders',    path: '/portal/order-track', label: 'Orders', icon: ClipboardList },
    { id: 'portal-more',      path: '__more__',           label: 'More',   icon: MoreHorizontal },
  ],
  console: [
    { id: 'console-tables',   path: '/console/tables',    label: 'Tables', icon: LayoutDashboard },
    { id: 'console-health',   path: '/console/health',    label: 'Health', icon: LayoutDashboard },
    { id: 'console-more',     path: '__more__',           label: 'More',   icon: MoreHorizontal },
  ],
}

export default function MobileNav({ onMoreTap }) {
  const navigate = useNavigate()
  const location = useLocation()
  const activeApp = useShellStore((s) => s.activeApp)

  const tabs = TAB_CONFIGS[activeApp] || TAB_CONFIGS.operations

  function handleTap(tab) {
    if (tab.path === '__more__') {
      onMoreTap?.()
      return
    }
    navigate(tab.path)
  }

  // Match active tab — check if current path starts with tab path
  function isActive(tab) {
    if (tab.path === '__more__') return false
    return location.pathname === tab.path || location.pathname.startsWith(tab.path + '/')
  }

  return (
    <nav
      className="flex items-end justify-around shrink-0 border-t border-border bg-card"
      style={{ paddingBottom: 'env(safe-area-inset-bottom, 0px)' }}
    >
      {tabs.map((tab) => {
        const Icon = tab.icon
        const active = isActive(tab)
        return (
          <button
            key={tab.id}
            onClick={() => handleTap(tab)}
            className={cn(
              'flex flex-col items-center justify-center gap-0.5 pt-2 pb-1 flex-1 min-w-[44px] min-h-[56px] transition-colors',
              active
                ? 'text-primary'
                : 'text-muted-foreground active:text-foreground'
            )}
          >
            <Icon className="size-5" />
            <span className={cn(
              'text-[10px] leading-tight',
              active ? 'font-semibold' : 'font-medium'
            )}>
              {tab.label}
            </span>
          </button>
        )
      })}
    </nav>
  )
}
