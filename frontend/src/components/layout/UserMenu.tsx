import { useRef } from 'react'
import { LogOut, UserRound } from 'lucide-react'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'

export interface UserMenuProps {
  displayName: string
  onSignOut: () => void | Promise<void>
}

/** Account controls retain the authenticated shell's existing logout callback. */
export function UserMenu({ displayName, onSignOut }: UserMenuProps) {
  const triggerRef = useRef<HTMLButtonElement>(null)

  return (
    <DropdownMenu
      onOpenChange={(open) => {
        if (!open) {
          triggerRef.current?.focus()
        }
      }}
    >
      <DropdownMenuTrigger
        ref={triggerRef}
        aria-label={`Open user menu for ${displayName}`}
        className="inline-flex min-h-10 items-center gap-2 rounded-md px-2 text-sm font-medium text-foreground transition-colors hover:bg-accent hover:text-accent-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
      >
        <UserRound className="size-4" aria-hidden="true" />
        <span className="max-w-36 truncate">{displayName}</span>
      </DropdownMenuTrigger>
      <DropdownMenuContent className="relative right-0 mt-1">
        <DropdownMenuLabel>Signed in as {displayName}</DropdownMenuLabel>
        <DropdownMenuSeparator />
        <DropdownMenuItem onClick={() => void onSignOut()}>
          <LogOut className="mr-2 size-4" aria-hidden="true" />
          Sign out
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
