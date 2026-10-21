import { useRef } from 'react'
import { Check, Moon, Sun, SunMoon } from 'lucide-react'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { useTheme, type ThemeMode } from '@/lib/theme'

const THEME_OPTIONS: readonly { mode: ThemeMode; label: string; icon: typeof Sun }[] = [
  { mode: 'light', label: 'Light', icon: Sun },
  { mode: 'dark', label: 'Dark', icon: Moon },
  { mode: 'system', label: 'System', icon: SunMoon },
]

/** Theme presentation control; it never navigates or changes application state. */
export function ThemeToggle() {
  const { mode, setTheme } = useTheme()
  const triggerRef = useRef<HTMLButtonElement>(null)

  return (
    <div className="relative shrink-0">
      <DropdownMenu
      onOpenChange={(open) => {
        if (!open) {
          triggerRef.current?.focus()
        }
      }}
    >
      <DropdownMenuTrigger
        ref={triggerRef}
        aria-label={`Theme: ${mode}`}
        title="Change theme"
        className="inline-flex size-9 items-center justify-center rounded-md text-foreground transition-all hover:bg-accent hover:text-accent-foreground focus-visible:border-ring focus-visible:outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50"
      >
        <SunMoon className="size-4" aria-hidden="true" />
      </DropdownMenuTrigger>
      <DropdownMenuContent className="right-0 top-[calc(100%+8px)]">
        <DropdownMenuLabel>Theme</DropdownMenuLabel>
        {THEME_OPTIONS.map(({ mode: optionMode, label, icon: Icon }) => (
          <DropdownMenuItem
            key={optionMode}
            onClick={() => setTheme(optionMode)}
            aria-current={mode === optionMode ? 'true' : undefined}
          >
            <Icon className="mr-2 size-4" aria-hidden="true" />
            <span>{label}</span>
            {mode === optionMode && <Check className="ml-auto size-4" aria-label="Selected" />}
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
      </DropdownMenu>
    </div>
  )
}
