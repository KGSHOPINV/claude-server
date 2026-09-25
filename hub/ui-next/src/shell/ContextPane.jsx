import { PanelRightClose } from 'lucide-react'
import { cn } from 'cn'
import { useShellStore } from '@/lib/store'
import { Button } from '@/components/ui/button'
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs'
import { ScrollArea } from '@/components/ui/scroll-area'

const MODES = [
  { id: 'guide',   label: 'Guide' },
  { id: 'live',    label: 'Live' },
  { id: 'receipt', label: 'Receipt' },
]

export default function ContextPane() {
  const contextMode = useShellStore((s) => s.contextMode)
  const setContextMode = useShellStore((s) => s.setContextMode)
  const closeContext = useShellStore((s) => s.closeContext)

  return (
    <div className="flex flex-col h-full w-72 bg-card border-l border-border overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between px-3 h-11 border-b border-border shrink-0">
        <span className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
          Context
        </span>
        <Button
          variant="ghost"
          size="icon"
          className="size-7"
          onClick={closeContext}
          aria-label="Close context pane"
        >
          <PanelRightClose className="size-4" />
        </Button>
      </div>

      {/* Mode tabs */}
      <Tabs
        value={contextMode}
        onValueChange={(val) => setContextMode(val)}
        className="flex flex-col flex-1 min-h-0"
      >
        <div className="px-2 pt-2 shrink-0">
          <TabsList className="w-full h-8">
            {MODES.map((mode) => (
              <TabsTrigger key={mode.id} value={mode.id} className="flex-1 text-xs">
                {mode.label}
              </TabsTrigger>
            ))}
          </TabsList>
        </div>

        <ScrollArea className="flex-1">
          <TabsContent value="guide" className="px-3 py-3 m-0">
            <div className="space-y-3">
              <p className="text-sm text-muted-foreground">
                Step-by-step guidance for the current page.
              </p>
              <div className="space-y-2">
                <StepItem step={1} text="Select or scan the item" />
                <StepItem step={2} text="Confirm details" />
                <StepItem step={3} text="Commit action" />
              </div>
            </div>
          </TabsContent>

          <TabsContent value="live" className="px-3 py-3 m-0">
            <div className="space-y-3">
              <p className="text-sm text-muted-foreground">
                Live data for the current context.
              </p>
              <div className="rounded-md border border-border p-3 text-xs text-muted-foreground">
                No active data stream
              </div>
            </div>
          </TabsContent>

          <TabsContent value="receipt" className="px-3 py-3 m-0">
            <div className="space-y-3">
              <p className="text-sm text-muted-foreground">
                Transaction receipts and confirmations.
              </p>
              <div className="rounded-md border border-border p-3 text-xs text-muted-foreground">
                No recent transactions
              </div>
            </div>
          </TabsContent>
        </ScrollArea>
      </Tabs>
    </div>
  )
}

function StepItem({ step, text }) {
  return (
    <div className="flex items-start gap-2">
      <div className="flex items-center justify-center size-5 rounded-full bg-muted text-[10px] font-bold text-muted-foreground shrink-0 mt-0.5">
        {step}
      </div>
      <span className="text-sm text-foreground">{text}</span>
    </div>
  )
}
