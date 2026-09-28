import { useNavigate, useLocation } from 'react-router-dom'
import { cn } from 'cn'
import { PanelLeftClose, Navigation, FileText, BookOpen, LayoutGrid } from 'lucide-react'
import { useShellStore } from '@/lib/store'
import { getNavGroups } from '@/lib/registry'
import { ScrollArea } from '@/components/ui/scroll-area'
import {
  Accordion,
  AccordionItem,
  AccordionTrigger,
  AccordionContent,
} from '@/components/ui/accordion'
import { Button } from '@/components/ui/button'
import {
  Tooltip,
  TooltipTrigger,
  TooltipContent,
  TooltipProvider,
} from '@/components/ui/tooltip'

const NAV_MODES = [
  { id: 'nav',       icon: Navigation, label: 'Navigation' },
  { id: 'context',   icon: FileText,   label: 'Page Context' },
  { id: 'knowledge', icon: BookOpen,   label: 'Knowledge' },
]

export default function AppNav() {
  const navigate = useNavigate()
  const location = useLocation()
  const activeApp = useShellStore((s) => s.activeApp)
  const navMode = useShellStore((s) => s.navMode)
  const setNavMode = useShellStore((s) => s.setNavMode)
  const toggleNav = useShellStore((s) => s.toggleNav)
  const toggleLauncher = useShellStore((s) => s.toggleLauncher)

  return (
    <div className="flex flex-col h-full w-60 bg-sidebar border-r border-border overflow-hidden">
      {/* Top bar — app switcher trigger + collapse */}
      <div className="flex items-center justify-between px-3 h-11 border-b border-border shrink-0">
        <button
          onClick={toggleLauncher}
          className="flex items-center gap-2 text-sm font-semibold text-foreground hover:text-primary transition-colors"
        >
          <LayoutGrid className="size-4" />
          <span className="uppercase tracking-wider text-xs">{activeApp}</span>
        </button>
        <Button
          variant="ghost"
          size="icon"
          className="size-7 shrink-0"
          onClick={toggleNav}
          aria-label="Collapse nav"
        >
          <PanelLeftClose className="size-4" />
        </Button>
      </div>

      {/* Mode tabs */}
      <TooltipProvider delay={300}>
        <div className="flex items-center border-b border-border shrink-0">
          {NAV_MODES.map((mode) => {
            const Icon = mode.icon
            const isActive = navMode === mode.id
            return (
              <Tooltip key={mode.id}>
                <TooltipTrigger asChild>
                  <button
                    onClick={() => setNavMode(mode.id)}
                    className={cn(
                      'flex-1 flex items-center justify-center h-9 transition-all text-muted-foreground hover:text-foreground',
                      isActive && 'text-foreground border-b-2 border-primary bg-accent/50'
                    )}
                  >
                    <Icon className="size-4" />
                  </button>
                </TooltipTrigger>
                <TooltipContent side="bottom" className="text-xs">{mode.label}</TooltipContent>
              </Tooltip>
            )
          })}
        </div>
      </TooltipProvider>

      {/* Content based on mode */}
      <ScrollArea className="flex-1">
        {navMode === 'nav' && <NavContent activeApp={activeApp} navigate={navigate} pathname={location.pathname} />}
        {navMode === 'context' && <PageContextContent pathname={location.pathname} />}
        {navMode === 'knowledge' && <KnowledgeContent />}
      </ScrollArea>
    </div>
  )
}

// --- NAV MODE: Navigation tree ---
function NavContent({ activeApp, navigate, pathname }) {
  const groups = getNavGroups(activeApp)

  return (
    <div className="px-2 py-2">
      <Accordion multiple defaultValue={groups.map((g) => g.label ?? '__ungrouped')}>
        {groups.map((group) => {
          const key = group.label ?? '__ungrouped'

          if (!group.label) {
            return (
              <div key={key} className="flex flex-col gap-0.5 mb-2">
                {group.items.map((item) => (
                  <NavItem
                    key={item.id}
                    item={item}
                    isActive={pathname === item.path}
                    onClick={() => navigate(item.path)}
                  />
                ))}
              </div>
            )
          }

          return (
            <AccordionItem key={key} value={key} className="border-none">
              <AccordionTrigger className="px-2 py-1.5 text-xs font-semibold uppercase tracking-wider text-muted-foreground hover:no-underline hover:text-foreground rounded-md">
                {group.label}
              </AccordionTrigger>
              <AccordionContent className="pb-1">
                <div className="flex flex-col gap-0.5 pl-1">
                  {group.items.map((item) => (
                    <NavItem
                      key={item.id}
                      item={item}
                      isActive={pathname === item.path}
                      onClick={() => navigate(item.path)}
                    />
                  ))}
                </div>
              </AccordionContent>
            </AccordionItem>
          )
        })}
      </Accordion>
    </div>
  )
}

function NavItem({ item, isActive, onClick }) {
  const Icon = item.icon
  return (
    <button
      onClick={onClick}
      className={cn(
        'flex items-center gap-2 w-full px-2 py-1.5 rounded-md text-sm transition-all duration-150 text-left',
        'text-muted-foreground hover:text-foreground hover:bg-accent',
        isActive && 'bg-accent text-foreground font-medium'
      )}
    >
      {Icon && <Icon className="size-4 shrink-0" />}
      <span className="truncate">{item.label}</span>
    </button>
  )
}

// --- CONTEXT MODE: Page relationships ---
function PageContextContent({ pathname }) {
  // Placeholder — will show related entities, linked records, page-specific actions
  const page = pathname.split('/').filter(Boolean).pop() || 'dashboard'
  return (
    <div className="p-4 space-y-4">
      <div className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
        Page Context
      </div>
      <div className="text-sm text-muted-foreground">
        Related items and in-page relationships for <span className="text-foreground font-medium">{page}</span> will appear here.
      </div>
      <div className="space-y-2">
        <div className="rounded-md border border-border p-3 text-xs text-muted-foreground">
          Related entities
        </div>
        <div className="rounded-md border border-border p-3 text-xs text-muted-foreground">
          Linked records
        </div>
        <div className="rounded-md border border-border p-3 text-xs text-muted-foreground">
          Quick actions
        </div>
      </div>
    </div>
  )
}

// --- KNOWLEDGE MODE: Help / docs ---
function KnowledgeContent() {
  return (
    <div className="p-4 space-y-4">
      <div className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
        Knowledge
      </div>
      <div className="text-sm text-muted-foreground">
        Help articles, procedures, and documentation for the current context.
      </div>
      <div className="space-y-2">
        <div className="rounded-md border border-border p-3 text-xs text-muted-foreground">
          How-to guides
        </div>
        <div className="rounded-md border border-border p-3 text-xs text-muted-foreground">
          Procedures
        </div>
        <div className="rounded-md border border-border p-3 text-xs text-muted-foreground">
          Glossary
        </div>
      </div>
    </div>
  )
}
