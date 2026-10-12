import { createElement, type ReactNode, useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { ErrorState, LoadingState, PageContainer } from '@/components/patterns'

export interface StudyVersionSummary {
  id: string
  study_id: string
  version_number: string
  status: 'draft' | 'published' | string
  created_at: string
}

export interface DesignVersionSelection {
  version: StudyVersionSummary
  isReadOnly: boolean
}

export function getApiErrorMessage(error: unknown, fallback: string): string {
  if (error instanceof Error && error.message) return error.message
  const response = (error as { response?: { data?: { detail?: string; error?: { message?: string } } } })?.response
  return response?.data?.error?.message ?? response?.data?.detail ?? fallback
}

export function useDraftVersion(studyId: string) {
  const query = useQuery({
    queryKey: ['study-versions', studyId],
    queryFn: async () => (await api.get<StudyVersionSummary[]>(`/studies/${studyId}/versions`)).data,
  })
  const versions = Array.isArray(query.data) ? query.data : []
  const draft = versions.find((version) => version.status === 'draft')
  return { query, versions, draftVersionId: draft?.id ?? null, draftVersionNumber: draft?.version_number ?? null }
}

/** Selects the active Designer version; published selections are read-only. */
export function DraftGate({
  studyId,
  children,
}: {
  studyId: string
  children: (versionId: string, selection: DesignVersionSelection) => ReactNode
}) {
  const { query, versions, draftVersionId } = useDraftVersion(studyId)
  const storageKey = `designer:selected-version:${studyId}`
  const [selectedId, setSelectedId] = useState(() => {
    try {
      return new URLSearchParams(window.location.search).get('design_version_id')
        ?? localStorage.getItem(storageKey)
        ?? ''
    } catch { return '' }
  })
  const defaultVersion = versions.find((version) => version.id === draftVersionId)
    ?? [...versions].sort((a, b) => b.created_at.localeCompare(a.created_at))[0]
  const selectedVersion = versions.find((version) => version.id === selectedId) ?? defaultVersion

  useEffect(() => {
    if (selectedVersion) {
      try { localStorage.setItem(storageKey, selectedVersion.id) } catch { /* optional browser storage */ }
    }
  }, [selectedVersion, storageKey])

  if (query.isLoading) return createElement(PageContainer, null, createElement(LoadingState, { label: 'design version' }))
  if (query.isError) return createElement(PageContainer, null, createElement(ErrorState, { message: 'Unable to resolve the study design versions.', onRetry: () => void query.refetch() }))
  if (!selectedVersion) return createElement(PageContainer, null, createElement(Alert, null, createElement(AlertDescription, null, 'This study has no design versions. Create an initial draft on the Study versioning page.')))

  const isReadOnly = selectedVersion.status !== 'draft'
  const changeVersion = (versionId: string) => {
    setSelectedId(versionId)
    try { localStorage.setItem(storageKey, versionId) } catch { /* optional browser storage */ }
    try {
      const url = new URL(window.location.href)
      url.searchParams.set('design_version_id', versionId)
      window.history.replaceState(window.history.state, '', url)
    } catch { /* optional browser history */ }
  }

  return createElement(
    'div',
    null,
    createElement(
      'div',
      { className: 'mb-4 flex flex-wrap items-center justify-between gap-3 rounded-lg border bg-card px-4 py-3' },
      createElement('div', null,
        createElement('p', { className: 'text-sm font-medium' }, 'Design version'),
        createElement('p', { className: 'text-xs text-muted-foreground' }, isReadOnly ? 'Published versions are read-only.' : 'Current editable draft.'),
      ),
      createElement(
        'select',
        { 'aria-label': 'Design version', className: 'h-9 min-w-48 rounded-md border bg-background px-3 text-sm', value: selectedVersion.id, onChange: (event: { target: { value: string } }) => changeVersion(event.target.value) },
        versions.map((version) => createElement('option', { key: version.id, value: version.id }, `v${version.version_number} · ${version.status}${version.id === draftVersionId ? ' (current)' : ''}`)),
      ),
    ),
    isReadOnly ? createElement(Alert, { className: 'mb-4' }, createElement(AlertDescription, null, `Viewing published version ${selectedVersion.version_number}. This design is read-only.`)) : null,
    createElement('div', { key: selectedVersion.id }, children(selectedVersion.id, { version: selectedVersion, isReadOnly })),
  )
}
