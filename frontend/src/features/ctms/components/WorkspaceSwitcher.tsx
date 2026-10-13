import { useEffect, useMemo, useRef, useState } from 'react'
import { useLocation, useNavigate } from '@tanstack/react-router'
import { Check, ChevronsUpDown, LayoutDashboard, Loader2, Search, Star } from 'lucide-react'
import { useStudyContext } from '@/lib/study-context'
import { cn } from '@/lib/utils'
import { getCTMSWorkspaceFromPath } from '../navigation'
import {
  readCTMSWorkspacePreferences,
  recordRecentStudy,
  rememberCTMSWorkspacePath,
  saveCTMSWorkspacePreferences,
  type CTMSWorkspacePreferences,
} from '../workspace-state'
import { useWorkspaceStudies, type WorkspaceStudy } from '../workspace-studies'

function StudyOption({ study, selected, favorite, onSelect, onFavorite }: {
  study: WorkspaceStudy
  selected: boolean
  favorite: boolean
  onSelect: () => void
  onFavorite: () => void
}) {
  return <div className="group flex items-center gap-1 rounded-md px-1 hover:bg-sidebar-accent">
    <button type="button" role="option" aria-selected={selected} className="flex min-w-0 flex-1 items-center gap-2 rounded px-2 py-2 text-left" onClick={onSelect}>
      <span className="flex size-7 shrink-0 items-center justify-center rounded-md bg-sidebar-primary/10 text-[0.625rem] font-bold text-sidebar-primary">{study.study_code.slice(0, 2).toUpperCase()}</span>
      <span className="min-w-0 flex-1">
        <span className="block truncate text-xs font-semibold text-sidebar-foreground">{study.study_code}</span>
        <span className="block truncate text-[0.6875rem] text-sidebar-foreground/60">{study.title}</span>
      </span>
      {selected ? <Check className="size-3.5 shrink-0 text-sidebar-primary" aria-hidden="true" /> : null}
    </button>
    <button type="button" className="rounded p-1.5 text-sidebar-foreground/50 hover:bg-sidebar-border hover:text-sidebar-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sidebar-ring" onClick={onFavorite} aria-label={`${favorite ? 'Remove' : 'Add'} ${study.study_code} ${favorite ? 'from' : 'to'} favorites`}>
      <Star className={cn('size-3.5', favorite && 'fill-current text-sidebar-primary')} aria-hidden="true" />
    </button>
  </div>
}

export function WorkspaceSwitcher({ collapsed = false, mobile = false, onNavigate }: { collapsed?: boolean; mobile?: boolean; onNavigate?: () => void }) {
  const navigate = useNavigate()
  const pathname = useLocation().pathname
  const workspace = getCTMSWorkspaceFromPath(pathname)
  const workspaceKind = workspace?.kind
  const workspaceStudyId = workspace?.studyId
  const { data, isLoading } = useWorkspaceStudies()
  const setStudy = useStudyContext((state) => state.setStudy)
  const [open, setOpen] = useState(false)
  const [search, setSearch] = useState('')
  const [preferences, setPreferences] = useState<CTMSWorkspacePreferences>(readCTMSWorkspacePreferences)
  const containerRef = useRef<HTMLDivElement>(null)
  const selectedStudy = data?.items.find((study) => study.id === workspace?.studyId)

  useEffect(() => {
    if (!workspaceKind) return
    rememberCTMSWorkspacePath(workspaceKind === 'global' ? '/ctms' : `/studies/${encodeURIComponent(workspaceStudyId ?? '')}/ctms`)
    if (workspaceStudyId) {
      const study = data?.items.find((item) => item.id === workspaceStudyId)
      setStudy(workspaceStudyId, study ? `${study.study_code} — ${study.title}` : undefined)
      saveCTMSWorkspacePreferences(recordRecentStudy(readCTMSWorkspacePreferences(), workspaceStudyId))
    }
  }, [data?.items, setStudy, workspaceKind, workspaceStudyId])

  useEffect(() => {
    if (!open) return
    const close = (event: MouseEvent) => {
      if (!containerRef.current?.contains(event.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', close)
    return () => document.removeEventListener('mousedown', close)
  }, [open])

  const matchingStudies = useMemo(() => {
    const needle = search.trim().toLowerCase()
    return (data?.items ?? []).filter((study) => !needle || `${study.study_code} ${study.title}`.toLowerCase().includes(needle))
  }, [data?.items, search])
  const favoriteStudies = matchingStudies.filter((study) => preferences.favorites.includes(study.id))
  const recentStudies = preferences.recents.flatMap((id) => {
    const study = matchingStudies.find((item) => item.id === id)
    return study && !preferences.favorites.includes(id) ? [study] : []
  })
  const remainingStudies = matchingStudies.filter((study) => !preferences.favorites.includes(study.id) && !preferences.recents.includes(study.id))

  const selectPortfolio = () => {
    setOpen(false); setSearch(''); rememberCTMSWorkspacePath('/ctms'); onNavigate?.()
    void navigate({ to: '/ctms' })
  }
  const selectStudy = (study: WorkspaceStudy) => {
    setStudy(study.id, `${study.study_code} — ${study.title}`)
    const next = recordRecentStudy(preferences, study.id)
    setPreferences(next); saveCTMSWorkspacePreferences(next); setOpen(false); setSearch(''); onNavigate?.()
    void navigate({ to: '/studies/$studyId/ctms', params: { studyId: study.id } })
  }
  const toggleFavorite = (studyId: string) => {
    const next = { ...preferences, favorites: preferences.favorites.includes(studyId) ? preferences.favorites.filter((id) => id !== studyId) : [...preferences.favorites, studyId] }
    setPreferences(next); saveCTMSWorkspacePreferences(next)
  }

  const title = workspace?.kind === 'study' ? (selectedStudy?.study_code ?? 'Study workspace') : 'Portfolio'
  const subtitle = workspace?.kind === 'study' ? (selectedStudy?.title ?? 'Loading study…') : 'Global Workspace'

  return <div ref={containerRef} className={cn('relative border-b border-sidebar-border p-2', mobile && 'px-0')} data-testid="workspace-switcher">
    {!collapsed || mobile ? <span className="mb-1 block px-1 text-[0.625rem] font-semibold uppercase tracking-[0.14em] text-sidebar-foreground/50">Workspace</span> : null}
    <button type="button" aria-haspopup="listbox" aria-expanded={open} onClick={() => setOpen((value) => !value)} title={collapsed && !mobile ? `${title} — ${subtitle}` : undefined} className={cn('flex w-full items-center gap-2 rounded-lg border border-sidebar-border bg-sidebar-accent/60 p-2 text-left transition-colors hover:bg-sidebar-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sidebar-ring', collapsed && !mobile && 'justify-center border-0 bg-transparent px-1')}>
      <span className="flex size-8 shrink-0 items-center justify-center rounded-md bg-sidebar-primary text-sidebar-primary-foreground"><LayoutDashboard className="size-4" aria-hidden="true" /></span>
      <span className={cn('min-w-0 flex-1', collapsed && !mobile && 'sr-only')}><span className="block truncate text-xs font-semibold text-sidebar-foreground">{title}</span><span className="block truncate text-[0.6875rem] text-sidebar-foreground/60">{subtitle}</span></span>
      {(!collapsed || mobile) ? <ChevronsUpDown className="size-3.5 shrink-0 text-sidebar-foreground/50" aria-hidden="true" /> : null}
    </button>

    {open ? <div className={cn('absolute z-50 mt-2 w-[19rem] rounded-xl border border-sidebar-border bg-sidebar p-2 shadow-xl', collapsed && !mobile ? 'left-[calc(100%+0.5rem)] top-0 mt-0' : 'left-2', mobile && 'left-0')} role="listbox" aria-label="Select CTMS workspace">
      <div className="relative mb-2"><Search className="absolute left-2.5 top-2.5 size-3.5 text-sidebar-foreground/40" aria-hidden="true" /><input autoFocus aria-label="Search studies" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search study ID or title" className="h-9 w-full rounded-md border border-sidebar-border bg-sidebar-accent pl-8 pr-3 text-xs text-sidebar-foreground outline-none placeholder:text-sidebar-foreground/40 focus:ring-2 focus:ring-sidebar-ring" /></div>
      <button type="button" role="option" aria-selected={workspace?.kind === 'global'} className="flex w-full items-center gap-2 rounded-md px-3 py-2 text-left hover:bg-sidebar-accent" onClick={selectPortfolio}><span className="flex size-7 items-center justify-center rounded-md bg-sidebar-primary/10"><LayoutDashboard className="size-3.5 text-sidebar-primary" /></span><span className="min-w-0 flex-1"><span className="block text-xs font-semibold">Portfolio</span><span className="block text-[0.6875rem] text-sidebar-foreground/60">Global Workspace</span></span>{workspace?.kind === 'global' ? <Check className="size-3.5 text-sidebar-primary" /> : null}</button>
      <div className="my-2 h-px bg-sidebar-border" />
      <div className="max-h-[min(25rem,55vh)] overflow-y-auto pr-1">
        {isLoading ? <div className="flex items-center gap-2 px-3 py-4 text-xs text-sidebar-foreground/60"><Loader2 className="size-3.5 animate-spin" /> Loading accessible studies…</div> : null}
        {[['Favorites', favoriteStudies], ['Recent', recentStudies], ['All studies', remainingStudies]] .map(([label, studies]) => {
          const values = studies as WorkspaceStudy[]
          return values.length ? <section key={label as string} className="mb-2"><h3 className="px-2 py-1 text-[0.625rem] font-semibold uppercase tracking-wide text-sidebar-foreground/45">{label as string}</h3>{values.map((study) => <StudyOption key={study.id} study={study} selected={workspace?.studyId === study.id} favorite={preferences.favorites.includes(study.id)} onSelect={() => selectStudy(study)} onFavorite={() => toggleFavorite(study.id)} />)}</section> : null
        })}
        {!isLoading && matchingStudies.length === 0 ? <p className="px-3 py-6 text-center text-xs text-sidebar-foreground/60">No accessible studies match your search.</p> : null}
      </div>
    </div> : null}
  </div>
}
