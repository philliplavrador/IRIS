import * as React from 'react'
import { cn } from '../../lib/utils'

interface TabsContextValue {
  value: string
  onValueChange: (value: string) => void
  registerTrigger: (value: string, el: HTMLButtonElement | null) => void
  focusSibling: (fromValue: string, direction: 'prev' | 'next' | 'first' | 'last') => void
}

const TabsContext = React.createContext<TabsContextValue | null>(null)

function useTabs() {
  const ctx = React.useContext(TabsContext)
  if (!ctx) throw new Error('Tabs components must be used within <Tabs>')
  return ctx
}

interface TabsProps extends React.HTMLAttributes<HTMLDivElement> {
  value: string
  onValueChange: (value: string) => void
}

function Tabs({ value, onValueChange, className, children, ...props }: TabsProps) {
  // Ordered registry of trigger values + DOM refs, used for arrow-key nav.
  const triggersRef = React.useRef<Array<{ value: string; el: HTMLButtonElement }>>([])

  const registerTrigger = React.useCallback((val: string, el: HTMLButtonElement | null) => {
    const list = triggersRef.current
    const existing = list.findIndex((t) => t.value === val)
    if (el) {
      if (existing >= 0) list[existing] = { value: val, el }
      else list.push({ value: val, el })
    } else if (existing >= 0) {
      list.splice(existing, 1)
    }
  }, [])

  const focusSibling = React.useCallback(
    (fromValue: string, direction: 'prev' | 'next' | 'first' | 'last') => {
      const list = triggersRef.current
      if (list.length === 0) return
      const idx = list.findIndex((t) => t.value === fromValue)
      let target = idx
      if (direction === 'first') target = 0
      else if (direction === 'last') target = list.length - 1
      else if (direction === 'prev') target = idx <= 0 ? list.length - 1 : idx - 1
      else if (direction === 'next') target = idx < 0 || idx >= list.length - 1 ? 0 : idx + 1
      const entry = list[target]
      if (entry) {
        entry.el.focus()
        onValueChange(entry.value)
      }
    },
    [onValueChange]
  )

  const ctx = React.useMemo<TabsContextValue>(
    () => ({ value, onValueChange, registerTrigger, focusSibling }),
    [value, onValueChange, registerTrigger, focusSibling]
  )

  return (
    <TabsContext.Provider value={ctx}>
      <div className={cn("flex flex-col", className)} {...props}>
        {children}
      </div>
    </TabsContext.Provider>
  )
}

const TabsList = React.forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement>>(
  ({ className, ...props }, ref) => (
    <div
      ref={ref}
      role="tablist"
      className={cn(
        "inline-flex h-9 items-center justify-center rounded-lg bg-muted p-1 text-muted-foreground",
        className
      )}
      {...props}
    />
  )
)
TabsList.displayName = 'TabsList'

interface TabsTriggerProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  value: string
}

const TabsTrigger = React.forwardRef<HTMLButtonElement, TabsTriggerProps>(
  ({ className, value, onKeyDown, ...props }, ref) => {
    const { value: selected, onValueChange, registerTrigger, focusSibling } = useTabs()
    const isSelected = selected === value
    const innerRef = React.useRef<HTMLButtonElement | null>(null)

    const setRefs = React.useCallback(
      (el: HTMLButtonElement | null) => {
        innerRef.current = el
        registerTrigger(value, el)
        if (typeof ref === 'function') ref(el)
        else if (ref) (ref as React.MutableRefObject<HTMLButtonElement | null>).current = el
      },
      [ref, registerTrigger, value]
    )

    React.useEffect(() => {
      // Cleanup on unmount.
      return () => registerTrigger(value, null)
      // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [])

    const handleKeyDown = (e: React.KeyboardEvent<HTMLButtonElement>) => {
      onKeyDown?.(e)
      if (e.defaultPrevented) return
      if (e.key === 'ArrowRight' || e.key === 'ArrowDown') {
        e.preventDefault()
        focusSibling(value, 'next')
      } else if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') {
        e.preventDefault()
        focusSibling(value, 'prev')
      } else if (e.key === 'Home') {
        e.preventDefault()
        focusSibling(value, 'first')
      } else if (e.key === 'End') {
        e.preventDefault()
        focusSibling(value, 'last')
      }
    }

    return (
      <button
        ref={setRefs}
        role="tab"
        type="button"
        id={`tab-${value}`}
        aria-selected={isSelected}
        aria-controls={`panel-${value}`}
        data-state={isSelected ? 'active' : 'inactive'}
        tabIndex={isSelected ? 0 : -1}
        className={cn(
          "inline-flex items-center justify-center whitespace-nowrap rounded-md px-3 py-1 text-sm font-medium ring-offset-background transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:pointer-events-none disabled:opacity-50 cursor-pointer",
          isSelected
            ? "bg-background text-foreground shadow"
            : "hover:bg-background/50 hover:text-foreground"
          , className
        )}
        onClick={() => onValueChange(value)}
        onKeyDown={handleKeyDown}
        {...props}
      />
    )
  }
)
TabsTrigger.displayName = 'TabsTrigger'

interface TabsContentProps extends React.HTMLAttributes<HTMLDivElement> {
  value: string
}

const TabsContent = React.forwardRef<HTMLDivElement, TabsContentProps>(
  ({ className, value, ...props }, ref) => {
    const { value: selected } = useTabs()
    const isActive = selected === value
    if (!isActive) return null
    return (
      <div
        ref={ref}
        role="tabpanel"
        id={`panel-${value}`}
        aria-labelledby={`tab-${value}`}
        data-state={isActive ? 'active' : 'inactive'}
        hidden={!isActive}
        tabIndex={0}
        className={cn("flex-1 min-h-0", className)}
        {...props}
      />
    )
  }
)
TabsContent.displayName = 'TabsContent'

export { Tabs, TabsList, TabsTrigger, TabsContent }
