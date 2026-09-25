import { cn } from 'cn'

export default function PageSection({ title, actions, children, className }) {
  return (
    <section className={cn('space-y-3', className)}>
      {(title || actions) && (
        <div className="flex items-center justify-between">
          {title && <h3 className="text-sm font-medium text-foreground">{title}</h3>}
          {actions && <div className="flex items-center gap-2">{actions}</div>}
        </div>
      )}
      {children}
    </section>
  )
}
