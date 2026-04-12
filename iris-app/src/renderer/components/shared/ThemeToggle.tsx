import { Moon, Sun, Monitor } from 'lucide-react'
import { useTheme } from './ThemeProvider'
import { Button } from '../ui/button'

export function ThemeToggle() {
  const { theme, setTheme } = useTheme()

  function cycle() {
    const next = theme === 'light' ? 'dark' : theme === 'dark' ? 'system' : 'light'
    setTheme(next)
  }

  return (
    <Button variant="ghost" size="icon" onClick={cycle} title={`Theme: ${theme}`}>
      {theme === 'light' && <Sun className="h-4 w-4" />}
      {theme === 'dark' && <Moon className="h-4 w-4" />}
      {theme === 'system' && <Monitor className="h-4 w-4" />}
    </Button>
  )
}
