import * as React from 'react'
import { cn } from '@/lib/utils'

const Kbd = React.forwardRef<
  HTMLElement,
  React.HTMLAttributes<HTMLElement>
>(({ className, ...props }, ref) => (
  <kbd
    ref={ref}
    className={cn(
      'inline-flex items-center justify-center rounded border border-border bg-muted px-2 py-1 font-mono text-xs font-semibold text-foreground',
      className
    )}
    {...props}
  />
))
Kbd.displayName = 'Kbd'

export { Kbd }
