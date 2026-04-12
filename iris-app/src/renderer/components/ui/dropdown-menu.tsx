import * as React from 'react'
import { cn } from '../../lib/utils'

interface DropdownMenuProps {
  children: React.ReactNode
}

interface DropdownContextValue {
  open: boolean
  setOpen: (open: boolean) => void
}

const DropdownContext = React.createContext<DropdownContextValue>({ open: false, setOpen: () => {} })

function DropdownMenu({ children }: DropdownMenuProps) {
  const [open, setOpen] = React.useState(false)
  return (
    <DropdownContext.Provider value={{ open, setOpen }}>
      <div className="relative inline-block">{children}</div>
    </DropdownContext.Provider>
  )
}

function DropdownMenuTrigger({ children, className, ...props }: React.ButtonHTMLAttributes<HTMLButtonElement>) {
  const { open, setOpen } = React.useContext(DropdownContext)
  return (
    <button
      className={className}
      onClick={(e) => { e.stopPropagation(); setOpen(!open) }}
      {...props}
    >
      {children}
    </button>
  )
}

function DropdownMenuContent({ children, className, align = 'end' }: { children: React.ReactNode; className?: string; align?: 'start' | 'end' }) {
  const { open, setOpen } = React.useContext(DropdownContext)
  if (!open) return null
  return (
    <>
      <div className="fixed inset-0 z-40" onClick={() => setOpen(false)} />
      <div className={cn(
        "absolute z-50 min-w-[8rem] rounded-lg border bg-popover p-1 text-popover-foreground shadow-lg animate-scale-in",
        align === 'end' ? 'right-0' : 'left-0',
        "top-full mt-1",
        className
      )}>
        {children}
      </div>
    </>
  )
}

function DropdownMenuItem({ children, className, onClick, destructive, ...props }: React.ButtonHTMLAttributes<HTMLButtonElement> & { destructive?: boolean }) {
  const { setOpen } = React.useContext(DropdownContext)
  return (
    <button
      className={cn(
        "relative flex w-full cursor-pointer select-none items-center rounded-sm px-2 py-1.5 text-sm outline-none transition-colors",
        destructive
          ? "text-destructive hover:bg-destructive/10 focus:bg-destructive/10"
          : "hover:bg-accent focus:bg-accent",
        className
      )}
      onClick={(e) => { e.stopPropagation(); setOpen(false); onClick?.(e) }}
      {...props}
    >
      {children}
    </button>
  )
}

function DropdownMenuSeparator({ className }: { className?: string }) {
  return <div className={cn("-mx-1 my-1 h-px bg-border", className)} />
}

export { DropdownMenu, DropdownMenuTrigger, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator }
