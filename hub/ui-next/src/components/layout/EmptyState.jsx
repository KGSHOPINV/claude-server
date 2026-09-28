import { cn } from 'cn'

export default function EmptyState({ icon: Icon, title, message, action, className }) {
  return (
    <div className={cn('flex flex-col items-center justify-center py-16 px-4 text-center', className)}>
      {Icon && <Icon className="size-12 text-muted-foreground/50 mb-4" />}
      <h3 className="text-sm font-medium text-foreground mb-1">{title || 'Nothing here'}</h3>
      {message && <p className="text-sm text-muted-foreground max-w-sm">{message}</p>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  )
}
