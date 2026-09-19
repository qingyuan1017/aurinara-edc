import { readFileSync, readdirSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

type PackageManifest = {
  dependencies?: Record<string, string>
  devDependencies?: Record<string, string>
}

type LockRoot = PackageManifest

const frontendRoot = process.cwd()
const sourceRoot = resolve(frontendRoot, 'src')
const read = (path: string) => readFileSync(path, 'utf8')

function sourceFiles(directory: string): string[] {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const path = resolve(directory, entry.name)
    if (entry.isDirectory()) {
      return entry.name === '__tests__' ? [] : sourceFiles(path)
    }
    return /\.(?:ts|tsx)$/.test(entry.name) ? [path] : []
  })
}

const applicationFiles = sourceFiles(sourceRoot)
const applicationText = applicationFiles.map((path) => ({ path, text: read(path) }))
const routerPath = resolve(sourceRoot, 'lib/router.ts')
const appShellPath = resolve(sourceRoot, 'components/layout/AppShell.tsx')
const authGuardPath = resolve(sourceRoot, 'components/guards/AuthGuard.tsx')

const approvedDependencies = new Set([
  '@hookform/resolvers',
  '@tanstack/react-query',
  '@tanstack/react-router',
  '@tanstack/react-table',
  'axios',
  'class-variance-authority',
  'clsx',
  'lucide-react',
  'react',
  'react-dom',
  'react-hook-form',
  'tailwind-merge',
  'zod',
  'zustand',
  '@eslint/js',
  '@playwright/test',
  '@tailwindcss/vite',
  '@testing-library/jest-dom',
  '@testing-library/react',
  '@testing-library/user-event',
  '@types/node',
  '@types/react',
  '@types/react-dom',
  '@vitejs/plugin-react',
  'eslint',
  'eslint-plugin-react-hooks',
  'eslint-plugin-react-refresh',
  'globals',
  'jsdom',
  'tailwindcss',
  'typescript',
  'typescript-eslint',
  'vite',
  'vitest',
])

const primitiveNames = new Set([
  'Alert', 'AlertDescription', 'AlertTitle', 'Badge', 'Breadcrumb', 'BreadcrumbItem',
  'BreadcrumbLink', 'BreadcrumbList', 'BreadcrumbPage', 'BreadcrumbSeparator', 'Button',
  'Card', 'CardContent', 'CardDescription', 'CardFooter', 'CardHeader', 'CardTitle',
  'Checkbox', 'Dialog', 'DialogContent', 'DialogDescription', 'DialogFooter', 'DialogHeader',
  'DialogTitle', 'DialogTrigger', 'DropdownMenu', 'DropdownMenuContent', 'DropdownMenuItem',
  'DropdownMenuLabel', 'DropdownMenuSeparator', 'DropdownMenuTrigger', 'EmptyState', 'Input',
  'Label', 'ScrollArea', 'Select', 'SelectContent', 'SelectItem', 'SelectTrigger', 'SelectValue',
  'Separator', 'Sheet', 'SheetContent', 'SheetDescription', 'SheetFooter', 'SheetHeader',
  'SheetTitle', 'SheetTrigger', 'Skeleton', 'Switch', 'Table', 'TableBody', 'TableCaption',
  'TableCell', 'TableHead', 'TableHeader', 'TableRow', 'Tabs', 'TabsContent', 'TabsList',
  'TabsTrigger', 'Textarea', 'Tooltip', 'TooltipContent', 'TooltipProvider', 'TooltipTrigger',
])

const approvedPrimitiveImportPrefixes = ['@/components/ui/', '@/components/patterns']

function packageNames(manifest: PackageManifest): string[] {
  return [...Object.keys(manifest.dependencies ?? {}), ...Object.keys(manifest.devDependencies ?? {})]
}

function forbiddenCTMSPaths(text: string): string[] {
  const endpointPattern = /['"`]([^'"`]*\/ctms\/[^'"`]*)['"`]/g
  const forbiddenSegment = /\/(?:clinical|edc)(?:[/_-]|$)|\/(?:visit[_-]?instances|form[_-]?instances|field[_-]?values|clinical[_-]?attachments|clinical[_-]?exports)(?:[/?$}]|$)/i
  return [...text.matchAll(endpointPattern)]
    .map((match) => match[1])
    .filter((endpoint) => forbiddenSegment.test(endpoint))
}

describe('frontend source migration checks', () => {
  it('keeps one router and one authenticated shell wired through AuthGuard, AppShell, and Outlet', () => {
    const routerText = read(routerPath)
    const shellText = read(appShellPath)
    const authGuardText = read(authGuardPath)
    const routerFactoryFiles = applicationText.filter(({ text }) => /\bcreateRouter\s*\(/.test(text))
    const shellDefinitions = applicationText.filter(({ text }) => /\b(?:export\s+)?function\s+AppShell\s*\(/.test(text))
    const authGuardDefinitions = applicationText.filter(({ text }) => /\b(?:export\s+)?function\s+AuthGuard\s*\(/.test(text))

    expect(routerFactoryFiles.map(({ path }) => path)).toEqual([routerPath])
    expect(shellDefinitions.map(({ path }) => path)).toEqual([appShellPath])
    expect(authGuardDefinitions.map(({ path }) => path)).toEqual([authGuardPath])
    expect(read(resolve(sourceRoot, 'App.tsx'))).toMatch(/<RouterProvider\s+router=\{router\}/)
    expect(routerText).toMatch(/component:\s*\(\)\s*=>\s*createElement\(AuthGuard\)/)
    expect(routerText).toMatch(/getParentRoute:\s*\(\)\s*=>\s*authenticatedLayout[\s\S]*?component:\s*\(\)\s*=>\s*createElement\(AppShell\)/)
    expect(routerText).toMatch(/authenticatedLayout\.addChildren\(\[\s*appShellLayout\.addChildren\(\[/)
    expect(routerText).toMatch(/import\s*\{[^}]*\bOutlet\b[^}]*\}\s*from\s*['"]@tanstack\/react-router['"]|import\s*\{[^}]*\bOutlet\b[^}]*\}\s*from\s*['"]@tanstack\/react-router['"]/) 
    expect(shellText).toMatch(/<Outlet\s*\/>/)
    expect(authGuardText).toContain('useAuthStore')
  })

  it('keeps every protected route connected to AppShell and leaves public routes at the root', () => {
    const routerText = read(routerPath)
    const routeDeclarations = [...routerText.matchAll(/const\s+(\w+)\s*=\s*createRoute\(\{\s*getParentRoute:\s*\(\)\s*=>\s*(\w+)/g)]
    const publicRoutes = new Set(['loginRoute', 'forgotPasswordRoute', 'resetPasswordRoute', 'acceptInvitationRoute', 'accessDeniedRoute'])
    const parentMismatches = routeDeclarations
      .filter(([, name]) => name !== 'authenticatedLayout' && name !== 'appShellLayout')
      .filter(([, name, parent]) => parent !== (publicRoutes.has(name) || name === 'authenticatedLayout' ? 'rootRoute' : 'appShellLayout'))
      .map(([, name, parent]) => `${name} -> ${parent}`)

    expect(routeDeclarations.length).toBeGreaterThan(5)
    expect(parentMismatches).toEqual([])
    expect(routeDeclarations.find(([, name]) => name === 'authenticatedLayout')?.[2]).toBe('rootRoute')
    expect(routeDeclarations.find(([, name]) => name === 'appShellLayout')?.[2]).toBe('authenticatedLayout')
  })

  it('does not reference forbidden CTMS clinical mutation paths', () => {
    const violations = applicationText.flatMap(({ path, text }) => forbiddenCTMSPaths(text).map((endpoint) => ({ path, endpoint })))
    expect(violations).toEqual([])
  })

  it('keeps the redesign dependency-free and package metadata locked exactly', () => {
    const packageJson = JSON.parse(read(resolve(frontendRoot, 'package.json'))) as PackageManifest
    const packageLock = JSON.parse(read(resolve(frontendRoot, 'package-lock.json'))) as { packages?: Record<string, LockRoot> }
    const unapproved = packageNames(packageJson).filter((name) => !approvedDependencies.has(name))
    const lockRoot = packageLock.packages?.['']

    expect(unapproved).toEqual([])
    expect(lockRoot).toBeDefined()
    expect(lockRoot?.dependencies).toEqual(packageJson.dependencies)
    expect(lockRoot?.devDependencies).toEqual(packageJson.devDependencies)
  })

  it('imports shared primitives only from UI primitives or approved presentation patterns', () => {
    const violations: string[] = []
    const importPattern = /import\s+(?:type\s+)?\{([\s\S]*?)\}\s+from\s+['"]([^'"]+)['"]/g

    for (const { path, text } of applicationText) {
      for (const match of text.matchAll(importPattern)) {
        const importedNames = match[1]
          .split(',')
          .map((part) => {
            const trimmed = part.trim()
            return trimmed.startsWith('type ') ? '' : trimmed.replace(/\s+as\s+.*$/, '')
          })
          .filter((name) => primitiveNames.has(name))
        if (!importedNames.length) continue
        const importSource = match[2]
        const importerIsPattern = path.includes('/components/patterns/') && importSource.startsWith('.')
        const approvedImport = importerIsPattern || approvedPrimitiveImportPrefixes.some((prefix) => importSource.startsWith(prefix))
        if (!approvedImport) {
          violations.push(`${path}: ${importedNames.join(', ')} from ${importSource}`)
        }
      }
    }

    expect(violations).toEqual([])
  })
})
