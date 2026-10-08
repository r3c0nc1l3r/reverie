import * as React from 'react'
import { cn } from '@/lib/utils'

interface SliderProps {
  className?: string
  min?: number
  max?: number
  step?: number
  value?: number
  onChange?: (value: number) => void
}

const Slider = React.forwardRef<HTMLDivElement, SliderProps>(
  ({ className, min = 0, max = 100, step = 1, value = 50, onChange }, ref) => {
    return (
      <div
        ref={ref}
        className={cn('relative flex items-center w-full h-6', className)}
      >
        <div className="absolute w-full h-1 bg-muted rounded-full" />
        <input
          type="range"
          min={min}
          max={max}
          step={step}
          value={value}
          onChange={(e) => onChange?.(Number(e.target.value))}
          className="absolute w-full h-1 appearance-none bg-transparent cursor-pointer z-5 accent-primary"
        />
      </div>
    )
  }
)
Slider.displayName = 'Slider'

export { Slider }
