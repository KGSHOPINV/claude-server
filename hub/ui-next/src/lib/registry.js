/* registry — nav is DATA, not code.
 *
 * EMPTIED. The original carried another application's 6 app-spaces and its
 * whole nav tree; that is that app's content, not shell, so it is gone. What
 * remains is the SHAPE, with one example of each kind so the structure is
 * legible without being fiction.
 *
 * ServerHub already has this concept in hub/ui/registry.js -- 28 view entries,
 * 24 offered in nav, asserted by hub/tools/check-views.py. When this shell goes
 * live, THAT is the source and this file becomes its adapter, not a second
 * place to maintain a nav tree. Two nav registries would be exactly the defect
 * this project spent a fortnight removing.
 */
import { LayoutDashboard, Terminal, HardDrive } from 'lucide-react'

// ── App spaces: the far-left rail ────────────────────────────────────────────
// ServerHub's existing rail groups views by category. One entry per rail icon.
export const apps = [
  { id: 'ops', icon: LayoutDashboard, label: 'Ops', grants: ['admin'] },
]

// ── Nav tree: the collapsible left list, keyed by app id ─────────────────────
// Each item needs: id, path, label, icon. `mode` is optional and defaults to
// 'normal'; the original used 'config' for PIN-gated surfaces, which maps onto
// ServerHub's route gate levels (0 public / 1 user / 2 admin / 3 TOTP).
export const navTree = {
  ops: [
    {
      section: 'Watching',
      items: [
        { id: 'dashboard', path: '/dashboard', label: 'Dashboard', icon: LayoutDashboard },
        { id: 'storage', path: '/storage', label: 'Storage', icon: HardDrive },
      ],
    },
    {
      section: 'Doing',
      items: [
        { id: 'terminal', path: '/terminal', label: 'Terminal', icon: Terminal },
      ],
    },
  ],
}

// ── findNavItem — Shell.jsx calls this on every navigation ───────────────────
// It is what makes a nav click update the ACTIVE tab instead of opening a new
// one. Keep the contract: given a pathname, return the item or undefined.
export function findNavItem(pathname) {
  for (const appId of Object.keys(navTree)) {
    for (const group of navTree[appId]) {
      for (const item of group.items || []) {
        if (item.path === pathname) return { ...item, appId }
      }
    }
  }
  return undefined
}

export function itemsForApp(appId) {
  return navTree[appId] || []
}
