import { useCallback, useEffect, useState } from 'react'
import { Download, File, Folder, RefreshCw, Search, Share2 } from 'lucide-react'
import { api } from '@/lib/api'

type Node = {
  id: string
  parent_id: string | null
  kind: 'folder' | 'file'
  display_name: string
  source_product: string
  source_status: string
  classification: string
}

type Version = {
  id: string
  version_number: number
  sha256: string
  size_bytes: number
  created_at: string
}

const platformBase = (import.meta.env.VITE_PLATFORM_API_BASE_URL ?? '').replace(/\/$/, '')

async function platform<T>(path: string, init?: RequestInit): Promise<T> {
  const token = localStorage.getItem('access_token')?.trim()
  const response = await fetch(`${platformBase}${path}`, {
    ...init,
    headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json', ...init?.headers },
  })
  if (!response.ok) throw new Error(`Repository request failed (${response.status})`)
  return response.json() as Promise<T>
}

export function RepositoryPage({ studyId }: { studyId: string }) {
  const [query, setQuery] = useState('')
  const [view, setView] = useState('folder')
  const [path, setPath] = useState<Node[]>([])
  const [items, setItems] = useState<Node[]>([])
  const [selected, setSelected] = useState<Node | null>(null)
  const [versions, setVersions] = useState<Version[]>([])
  const [loading, setLoading] = useState(false)
  const [notice, setNotice] = useState('')
  const currentFolder = path.at(-1) ?? null

  const load = useCallback(async () => {
    setLoading(true)
    setNotice('')
    try {
      const params = new URLSearchParams({ view, limit: '100' })
      if (query.trim()) params.set('q', query.trim())
      if (view === 'folder' && currentFolder) params.set('parent_id', currentFolder.id)
      const result = await platform<{ items: Node[] }>(`/v1/studies/${studyId}/repository?${params}`)
      setItems(result.items)
      setSelected((value) => result.items.find((item) => item.id === value?.id) ?? null)
    } catch (error) { setNotice(error instanceof Error ? error.message : 'Repository unavailable') }
    finally { setLoading(false) }
  }, [studyId, query, view, currentFolder])

  useEffect(() => { void load() }, [load])
  useEffect(() => { setPath([]); setSelected(null) }, [studyId])
  useEffect(() => {
    if (!selected || selected.kind !== 'file') { setVersions([]); return }
    void platform<Version[]>(`/v1/repository/nodes/${selected.id}/versions`).then(setVersions).catch(() => setVersions([]))
  }, [selected])

  const download = async () => {
    if (!versions[0]) return
    const result = await platform<{ url: string }>(`/v1/repository/versions/${versions[0].id}/download`, { method: 'POST' })
    window.open(result.url, '_blank', 'noopener,noreferrer')
  }
  const attach = async () => {
    if (!versions[0]) return
    try {
      await api.post(`/studies/${studyId}/repository/attachments:bind`, { version_id: versions[0].id, expected_sha256: versions[0].sha256 })
      setNotice('Repository version attached to this study.')
    } catch { setNotice('Could not attach this Repository version.') }
  }

  return <div className="space-y-4">
    <div><h1 className="text-2xl font-bold text-foreground">Repository</h1><p className="text-sm text-muted-foreground">Authorized Platform, Aurinara, EDC, CTMS, PV, and neutral files.</p></div>
    <div className="flex flex-wrap gap-2"><label className="relative min-w-64 flex-1"><Search className="absolute left-3 top-2.5 size-4 text-muted-foreground"/><input className="h-9 w-full rounded-md border bg-background pl-9 text-sm" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search files" /></label><select className="h-9 rounded-md border bg-background px-3 text-sm" value={view} onChange={(event) => { setView(event.target.value); setPath([]); setSelected(null) }}><option value="folder">Folders</option><option value="all">All files</option><option value="recent">Recent</option><option value="aurinara">Aurinara</option><option value="aurinara-edc">EDC / CTMS / PV</option><option value="platform">Neutral</option><option value="archived">Archived</option></select><button className="rounded-md border px-3" onClick={() => void load()} aria-label="Refresh"><RefreshCw className={`size-4 ${loading ? 'animate-spin' : ''}`}/></button></div>
    {view === 'folder' && <nav className="flex flex-wrap items-center gap-1 text-sm" aria-label="Repository folders"><button className="rounded px-2 py-1 text-primary hover:bg-muted" onClick={() => { setPath([]); setSelected(null) }}>Repository</button>{path.map((folder, index) => <span key={folder.id} className="flex items-center gap-1"><span className="text-muted-foreground">/</span><button className="rounded px-2 py-1 text-primary hover:bg-muted" onClick={() => { setPath(path.slice(0, index + 1)); setSelected(null) }}>{folder.display_name}</button></span>)}</nav>}
    {notice && <p className="rounded-md border bg-muted p-3 text-sm">{notice}</p>}
    <div className="grid gap-4 lg:grid-cols-[1fr_340px]">
      <section className="overflow-hidden rounded-xl border bg-card"><div className="grid grid-cols-[1fr_110px_100px] border-b px-4 py-3 text-[11px] font-semibold uppercase text-muted-foreground"><span>Name</span><span>Source</span><span>Status</span></div>{items.map((item) => <button key={item.id} className={`grid w-full grid-cols-[1fr_110px_100px] items-center border-b px-4 py-3 text-left text-sm hover:bg-muted/50 ${selected?.id === item.id ? 'bg-muted' : ''}`} onClick={() => { if (item.kind === 'folder') { setPath([...path, item]); setSelected(null) } else { setSelected(item) } }}><span className="flex min-w-0 items-center gap-2">{item.kind === 'folder' ? <Folder className="size-4 text-amber-500"/> : <File className="size-4 text-primary"/>}<span className="truncate">{item.display_name}</span></span><span className="truncate text-xs text-muted-foreground">{item.source_product === 'platform' ? (item.kind === 'folder' ? 'Structure' : 'Neutral') : item.source_product}</span><span className="text-xs text-muted-foreground">{item.kind === 'folder' ? 'Folder' : item.source_status}</span></button>)}{!loading && items.length === 0 && <p className="p-12 text-center text-sm text-muted-foreground">No authorized files found.</p>}</section>
      <aside className="space-y-4 rounded-xl border bg-card p-5"><div><h2 className="font-semibold">{selected?.display_name ?? 'File details'}</h2><p className="text-xs text-muted-foreground">{selected ? `${selected.source_product} · ${selected.classification}` : 'Select a file'}</p></div>{selected?.kind === 'file' && <><div className="flex gap-2"><button className="inline-flex h-9 items-center gap-2 rounded-md border px-3 text-sm" onClick={() => void download()}><Download className="size-4"/>Download</button><button className="inline-flex h-9 items-center gap-2 rounded-md bg-primary px-3 text-sm text-primary-foreground" onClick={() => void attach()}><Share2 className="size-4"/>Attach to study</button></div><div className="space-y-2">{versions.map((version) => <div key={version.id} className="rounded-md bg-muted p-3 text-xs"><strong>v{version.version_number}</strong><p className="mt-1 text-muted-foreground">{(version.size_bytes / 1024).toFixed(1)} KB · {new Date(version.created_at).toLocaleString()}</p></div>)}</div></>}</aside>
    </div>
  </div>
}
