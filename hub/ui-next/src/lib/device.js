/**
 * @module device
 * Device detection utility for FKSINV shell routing.
 * Classifies viewport into MOBILE / TABLET / DESKTOP.
 */
import { useState, useEffect } from 'react'

// ---------------------------------------------------------------------------
// Breakpoints
// ---------------------------------------------------------------------------
const MOBILE_MAX = 767
const TABLET_MAX = 1024

// ---------------------------------------------------------------------------
// Pure functions (no React dependency)
// ---------------------------------------------------------------------------

/**
 * Returns device type based on screen width.
 * @param {number} [width=window.innerWidth]
 * @returns {'MOBILE'|'TABLET'|'DESKTOP'}
 */
export function getDeviceType(width) {
  const w = width ?? window.innerWidth
  if (w < 768) return 'MOBILE'
  if (w <= 1024) return 'TABLET'
  return 'DESKTOP'
}

/**
 * Returns full device info snapshot.
 * @returns {{ device_type: string, screen_width: number, user_agent: string }}
 */
export function getDeviceInfo() {
  return {
    device_type: getDeviceType(),
    screen_width: window.innerWidth,
    user_agent: navigator.userAgent,
  }
}

// ---------------------------------------------------------------------------
// React hook — reactive device type
// ---------------------------------------------------------------------------

/**
 * React hook that tracks device type reactively on window resize.
 * @returns {{ deviceType: string, screenWidth: number, userAgent: string }}
 */
export function useDevice() {
  const [state, setState] = useState(() => ({
    deviceType: getDeviceType(),
    screenWidth: window.innerWidth,
    userAgent: navigator.userAgent,
  }))

  useEffect(() => {
    function onResize() {
      const w = window.innerWidth
      const dt = getDeviceType(w)
      setState((prev) => {
        // Only update if device type or width actually changed
        if (prev.deviceType === dt && prev.screenWidth === w) return prev
        return { deviceType: dt, screenWidth: w, userAgent: prev.userAgent }
      })
    }

    window.addEventListener('resize', onResize)
    return () => window.removeEventListener('resize', onResize)
  }, [])

  return state
}
