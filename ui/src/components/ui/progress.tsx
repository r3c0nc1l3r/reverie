import * as React from 'react'
import { cn } from '@/lib/utils'

const Progress = React.forwardRef<
  HTMLDivElement,
  React.HTMLAttributes<HTMLDivElement> & {
    value?: number
    max?: number
  }
>(({ className, value = 0, max = 100, ...props }, ref) => {
  const percentage = (value / max) * 100
  return (
    <div
      ref={ref}
      className={cn('relative h-2 w-full overflow-hidden rounded-full bg-muted', className)}
      {...props}
    >
      <div
        className="h-full w-full flex-1 bg-primary transition-all"
        style={{ width: `${percentage}%` }}
      />
    </div>
  )
})
Progress.displayName = 'Progress'

export { Progress }
