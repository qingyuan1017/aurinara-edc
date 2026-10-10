import { useQuery } from '@tanstack/react-query'
import { api } from '@/lib/api'

/**
 * A Designer draft version resolved from the operational study-version list.
 *
 * Several designer definition surfaces (subject phases, visits, arms, CRF
 * access, raw-data variables, coding settings, schedule of assessment) are
 * authored against a specific Design_Version and are only mutable while that
 * version is a draft. The frontend resolves the open draft from the version
 * list the operational EDC surface still exposes at
 * `GET /studies/{studyId}/versions`.
 */
export interface StudyVersionSummary {
  id: string
  study_id: string
  version_number: string
  status: 'draft' | 'published' | string
  created_at: string
}

/** Extract a user-facing message from an Axios/API error envelope. */
export function getApiErrorMessage(error: unknown, fallback: string): string {
  if (error instanceof Error && error.message) return error.message
  const response = (error as { response?: { data?: { detail?: string; error?: { message?: string } } } })?.response
  return response?.data?.error?.message ?? response?.data?.detail ?? fallback
}

/**
 * Resolve the open draft version for a study.
 *
 * Returns the query (for loading/error states) plus the resolved draft id.
 * When no draft exists, `draftVersionId` is `null` and the caller should
 * prompt the user to create an amendment before authoring definitions.
 */
export function useDraftVersion(studyId: string) {
  const query = useQuery({
    queryKey: ['study-versions', studyId],
    queryFn: async () => (await api.get<StudyVersionSummary[]>(`/studies/${studyId}/versions`)).data,
  })

  const versions = query.data ?? []
  const draft = versions.find((version) => version.status === 'draft')

  return {
    query,
    versions,
    draftVersionId: draft?.id ?? null,
    draftVersionNumber: draft?.version_number ?? null,
  }
}

import { createElement, type ReactNode } from 'react'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { ErrorState, LoadingState, PageContainer } from '@/components/patterns'

/**
 * Render guard for version-scoped designer pages.
 *
 * Resolves the open draft version and renders `children(draftVersionId)` only
 * when a draft exists. Loading, error, and "no open draft" states are handled
 * uniformly so each resource page can focus on its own form.
 */
export function DraftGate({
  studyId,
  children,
}: {
  studyId: string
  children: (draftVersionId: string) => ReactNode
}) {
  const { query, draftVersionId } = useDraftVersion(studyId)

  if (query.isLoading) return createElement(PageContainer, null, createElement(LoadingState, { label: 'draft version' }))
  if (query.isError) {
    return createElement(
      PageContainer,
      null,
      createElement(ErrorState, { message: 'Unable to resolve the study draft version.', onRetry: () => void query.refetch() }),
    )
  }
  if (!draftVersionId) {
    return createElement(
      PageContainer,
      null,
      createElement(
        Alert,
        null,
        createElement(
          AlertDescription,
          null,
          'This study has no open draft version. Create an amendment on the Study versioning page before authoring definitions.',
        ),
      ),
    )
  }

  return createElement('div', null, children(draftVersionId))
}
