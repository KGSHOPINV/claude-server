import { useState, useRef, useCallback } from 'react'
import { Outlet } from 'react-router-dom'
import MobileHeader from './MobileHeader'
import MobileNav from './MobileNav'
import MobileMenu from './MobileMenu'

/**
 * MobileShell — full mobile layout.
 *
 * Structure (top to bottom):
 *   MobileHeader  — compact bar (hamburger, app name, avatar + scan)
 *   Main content   — full-bleed Outlet with pull-to-refresh
 *   MobileNav      — fixed bottom tab bar
 *
 * No sidebar, no workspace tabs, no context pane, no widget bar, no footer.
 */
export default function MobileShell({ children }) {
  const [menuOpen, setMenuOpen] = useState(false)

  // --- Pull-to-refresh state ---
  const mainRef = useRef(null)
  const touchStartY = useRef(0)
  const [pullDistance, setPullDistance] = useState(0)
  const [refreshing, setRefreshing] = useState(false)
  const PULL_THRESHOLD = 80

  const onTouchStart = useCallback((e) => {
    const el = mainRef.current
    if (!el || el.scrollTop > 0) return
    touchStartY.current = e.touches[0].clientY
  }, [])

  const onTouchMove = useCallback((e) => {
    const el = mainRef.current
    if (!el || el.scrollTop > 0 || refreshing) return
    const dy = e.touches[0].clientY - touchStartY.current
    if (dy > 0) {
      // Dampen the pull distance
      setPullDistance(Math.min(dy * 0.4, 120))
    }
  }, [refreshing])

  const onTouchEnd = useCallback(() => {
    if (pullDistance >= PULL_THRESHOLD && !refreshing) {
      setRefreshing(true)
      // Simulate refresh — pages can hook into this via context later
      setTimeout(() => {
        setRefreshing(false)
        setPullDistance(0)
      }, 1200)
    } else {
      setPullDistance(0)
    }
  }, [pullDistance, refreshing])

  return (
    <div
      className="flex flex-col h-dvh w-screen overflow-hidden bg-background text-foreground"
      style={{
        paddingTop: 'env(safe-area-inset-top, 0px)',
      }}
    >
      {/* Slide-in drawer menu */}
      <MobileMenu open={menuOpen} onClose={() => setMenuOpen(false)} />

      {/* Top bar */}
      <MobileHeader onMenuOpen={() => setMenuOpen(true)} />

      {/* Pull-to-refresh indicator */}
      {pullDistance > 0 && (
        <div
          className="flex items-center justify-center shrink-0 overflow-hidden transition-all"
          style={{ height: `${pullDistance}px` }}
        >
          <div
            className={`size-6 rounded-full border-2 border-primary border-t-transparent ${
              refreshing ? 'animate-spin' : ''
            }`}
            style={{
              opacity: Math.min(pullDistance / PULL_THRESHOLD, 1),
              transform: `rotate(${pullDistance * 3}deg)`,
            }}
          />
        </div>
      )}

      {/* Main content — full bleed */}
      <main
        ref={mainRef}
        className="flex-1 overflow-auto overscroll-contain"
        onTouchStart={onTouchStart}
        onTouchMove={onTouchMove}
        onTouchEnd={onTouchEnd}
      >
        {children ?? <Outlet />}
      </main>

      {/* Bottom tab bar */}
      <MobileNav onMoreTap={() => setMenuOpen(true)} />
    </div>
  )
}
