/**
 * @module ShellGate
 * Picks the correct shell (Desktop vs Mobile) based on device type.
 * Wraps the route layout — used as a layout Route element in App.jsx.
 * Auth guard: redirects to /login if not authenticated.
 */
import { Navigate } from 'react-router-dom'
import { useDevice } from '@/lib/device'
import { useUserStore } from '@/lib/store'
import Shell from './Shell'
import MobileShell from './MobileShell'

export default function ShellGate() {
  const isAuthenticated = useUserStore((s) => s.isAuthenticated)
  const { deviceType, screenWidth } = useDevice()

  // Auth guard — kick to login if not authenticated
  if (!isAuthenticated) return <Navigate to="/login" replace />

  // DESKTOP — always desktop shell
  if (deviceType === 'DESKTOP') return <Shell />

  // MOBILE — always mobile shell
  if (deviceType === 'MOBILE') return <MobileShell />

  // TABLET — landscape gets desktop, portrait gets mobile
  const isLandscape = screenWidth > window.innerHeight || screenWidth > 1024
  return isLandscape ? <Shell /> : <MobileShell />
}
