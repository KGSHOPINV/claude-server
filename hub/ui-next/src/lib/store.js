import { create } from 'zustand'
import { persist } from 'zustand/middleware'

// --- SHELL STORE ---
export const useShellStore = create(persist((set, get) => ({
  // Current app
  activeApp: 'operations',
  setActiveApp: (appId) => set({ activeApp: appId }),

  // App launcher overlay (iOS-style popup)
  launcherOpen: false,
  toggleLauncher: () => set((s) => ({ launcherOpen: !s.launcherOpen })),
  closeLauncher: () => set({ launcherOpen: false }),

  // Left nav
  navCollapsed: false,
  navMode: 'nav', // nav | context | knowledge
  toggleNav: () => set((s) => ({ navCollapsed: !s.navCollapsed })),
  setNavCollapsed: (v) => set({ navCollapsed: v }),
  setNavMode: (mode) => set({ navMode: mode }),

  // Floor mode — simplified touch/scan layout for warehouse floor + truck
  floorMode: false,
  toggleFloorMode: () => set((s) => ({ floorMode: !s.floorMode })),

  // Config mode — PIN-gated management surfaces
  configMode: false,
  toggleConfigMode: () => set((s) => ({ configMode: !s.configMode })),
  setConfigMode: (v) => set({ configMode: v }),

  // User presence status
  userStatus: 'online', // online | away | busy | offline
  setUserStatus: (status) => set({ userStatus: status }),

  // Right context pane
  contextOpen: true, // open by default
  contextMode: 'guide', // guide | live | receipt
  toggleContext: () => set((s) => ({ contextOpen: !s.contextOpen })),
  setContextMode: (mode) => set({ contextMode: mode, contextOpen: true }),
  closeContext: () => set({ contextOpen: false }),
}), {
  name: 'fks-shell',
  partialize: (state) => ({
    activeApp: state.activeApp,
    navCollapsed: state.navCollapsed,
    floorMode: state.floorMode,
    contextOpen: state.contextOpen,
  }),
}))

// --- TAB STORE ---
// Chrome-style workspace tabs — auto-created on navigation, persist across refresh
export const useTabStore = create(persist((set, get) => ({
  // tabs: [{ id, path, label, icon?, pinned?, appId }]
  tabs: [],
  activeTabId: null,

  // Open a brand new tab (+ button)
  openTab: ({ id, path, label, iconId, appId }) => {
    const { tabs } = get()
    const exists = tabs.find(t => t.id === id)
    if (exists) {
      set({ activeTabId: id })
      return
    }
    let next = [...tabs, { id, path, label, iconId, appId, pinned: false }]
    if (next.length > 8) {
      const oldest = next.find(t => !t.pinned && t.id !== id)
      if (oldest) next = next.filter(t => t.id !== oldest.id)
    }
    set({ tabs: next, activeTabId: id })
  },

  // Update the active tab in-place (nav click = same tab, new page)
  updateActiveTab: ({ id, path, label, iconId, appId }) => {
    const { tabs, activeTabId } = get()
    if (!activeTabId || tabs.length === 0) {
      // No tabs yet — create the first one
      set({ tabs: [{ id, path, label, iconId, appId, pinned: false }], activeTabId: id })
      return
    }
    set({
      tabs: tabs.map(t => t.id === activeTabId
        ? { ...t, id, path, label, iconId, appId }
        : t
      ),
      activeTabId: id,
    })
  },

  closeTab: (tabId) => {
    const { tabs, activeTabId } = get()
    const idx = tabs.findIndex(t => t.id === tabId)
    const next = tabs.filter(t => t.id !== tabId)
    let nextActive = activeTabId
    if (activeTabId === tabId) {
      nextActive = next[Math.min(idx, next.length - 1)]?.id || null
    }
    set({ tabs: next, activeTabId: nextActive })
  },

  setActiveTab: (tabId) => set({ activeTabId: tabId }),

  pinTab: (tabId) => set((s) => ({
    tabs: s.tabs.map(t => t.id === tabId ? { ...t, pinned: !t.pinned } : t),
  })),

  reorderTabs: (fromIdx, toIdx) => set((s) => {
    const tabs = [...s.tabs]
    const [moved] = tabs.splice(fromIdx, 1)
    tabs.splice(toIdx, 0, moved)
    return { tabs }
  }),

  closeAllUnpinned: () => set((s) => {
    const pinned = s.tabs.filter(t => t.pinned)
    return { tabs: pinned, activeTabId: pinned[0]?.id || null }
  }),
}), {
  name: 'fks-tabs',
  version: 2,
  partialize: (state) => ({
    tabs: state.tabs,
    activeTabId: state.activeTabId,
  }),
  migrate: (persisted, version) => {
    if (version < 2) {
      // v1 stored icon components — strip them, keep only serializable fields
      const clean = (persisted.tabs || []).map(t => ({
        id: t.id,
        path: t.path,
        label: t.label,
        iconId: t.iconId || t.id,
        appId: t.appId,
        pinned: t.pinned || false,
      }))
      return { ...persisted, tabs: clean }
    }
    return persisted
  },
}))

// --- SCANNER STORE ---
// Scanner input — always has manual fallback
export const useScannerStore = create((set) => ({
  // Input mode: scan (camera/bluetooth) or manual (type it in)
  inputMode: 'manual', // manual | scan
  setInputMode: (mode) => set({ inputMode: mode }),
  toggleInputMode: () => set((s) => ({ inputMode: s.inputMode === 'manual' ? 'scan' : 'manual' })),

  // Last scanned value
  lastScan: null,
  setScan: (value) => set({ lastScan: value }),
  clearScan: () => set({ lastScan: null }),
}))

// --- USER STORE ---
export const useUserStore = create(persist((set) => ({
  user: null,
  facility: null,
  clientOrg: null,
  sessionId: null,
  isAuthenticated: false,

  login: (user, facility, clientOrg, sessionId) => set({
    user, facility, clientOrg, sessionId, isAuthenticated: true,
  }),

  logout: () => {
    // Clear session token from browser storage
    if (typeof sessionStorage !== 'undefined') {
      sessionStorage.removeItem('fks_session_id')
    }
    if (typeof localStorage !== 'undefined') {
      localStorage.removeItem('fks-session-id')
    }
    set({
      user: null, facility: null, clientOrg: null, sessionId: null, isAuthenticated: false,
    })
  },

  setFacility: (facility) => set({ facility }),
  setClientOrg: (clientOrg) => set({ clientOrg }),
}), { name: 'fks-user' }))

// --- TRUCK STORE ---
// Two modes: FIXED (management assigns driver to truck) or SELECT (driver picks at login)
// Truck profile carries: identity, inventory, assets, safety checks, driver history
// useTruckStore removed: fksinv business state, zero references from the shell.

// --- DRAFT STORE ---
// useDraftStore removed: fksinv business state, zero references from the shell.
