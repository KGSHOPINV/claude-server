/* main — the entry point. Written here, not copied: the original app's main
 * wired its own routes, auth and data layer, none of which belong in a
 * template.
 *
 * This mounts the shell around an empty router. It runs, it is navigable, and
 * it renders nothing of consequence -- which is exactly what a template should
 * do.
 */
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter, Routes, Route } from 'react-router-dom'
import Shell from './shell/Shell'
import './index.css'

function Placeholder({ name }) {
  return (
    <div className="p-8">
      <h1 className="text-lg font-medium">{name}</h1>
      <p className="mt-2 text-sm text-muted-foreground">
        Empty. Views mount here — during migration this is where an existing
        ServerHub view's HTML gets injected, so the shell can go live before a
        single view is rewritten.
      </p>
    </div>
  )
}

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <BrowserRouter>
      <Routes>
        <Route element={<Shell />}>
          <Route path="/" element={<Placeholder name="Dashboard" />} />
          <Route path="/dashboard" element={<Placeholder name="Dashboard" />} />
          <Route path="/storage" element={<Placeholder name="Storage" />} />
          <Route path="/terminal" element={<Placeholder name="Terminal" />} />
        </Route>
      </Routes>
    </BrowserRouter>
  </StrictMode>
)
