import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { usePermission, PERMISSIONS } from '@/lib/permissions'

interface StudyDetail {
  id: string
  study_code: string
  title: string
  phase: string
  status: string
  description?: string
  created_at: string
  updated_at: string
}

interface StudyVersion {
  id: string
  version_number: string
  status: string
  amendment_reason?: string | null
  created_at: string
}

const STATUS_TRANSITIONS: Record<string, string[]> = {
  Draft: ['UAT'],
  UAT: ['Active'],
  Active: ['Enrollment Closed'],
  'Enrollment Closed': ['Locked'],
  Locked: ['Archived'],
  Archived: [],
}

export function StudyDetailPage({ studyId }: { studyId: string }) {
  const queryClient = useQueryClient()
  const canConfigure = usePermission(PERMISSIONS.STUDY_CONFIGURE)
  const canPublish = usePermission(PERMISSIONS.VERSION_PUBLISH)
  const [showVersionModal, setShowVersionModal] = useState(false)
  const [versionNumber, setVersionNumber] = useState('')
  const [amendmentReason, setAmendmentReason] = useState('')

  const { data: study, isLoading } = useQuery({
    queryKey: ['study', studyId],
    queryFn: async () => {
      const { data } = await api.get<StudyDetail>(`/studies/${studyId}`)
      return data
    },
  })

  const { data: versions } = useQuery({
    queryKey: ['study-versions', studyId],
    queryFn: async () => {
      const { data } = await api.get<StudyVersion[]>(`/studies/${studyId}/versions`)
      return data
    },
  })

  const transitionMutation = useMutation({
    mutationFn: async (newStatus: string) => {
      await api.post(`/studies/${studyId}/transition`, { target_status: newStatus })
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['study', studyId] })
      queryClient.invalidateQueries({ queryKey: ['studies'] })
    },
  })

  const createVersionMutation = useMutation({
    mutationFn: () => api.post(`/studies/${studyId}/versions`, { version_number: versionNumber, amendment_reason: amendmentReason || null }),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ['study-versions', studyId] }); setShowVersionModal(false); setVersionNumber(''); setAmendmentReason('') },
  })
  const publishMutation = useMutation({
    mutationFn: (versionId: string) => api.post(`/versions/${versionId}/publish`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['study-versions', studyId] }),
  })

  if (isLoading) {
    return <p className="p-6 text-gray-500">Loading study…</p>
  }

  if (!study) {
    return <p className="p-6 text-red-600">Study not found.</p>
  }

  const allowedTransitions = STATUS_TRANSITIONS[study.status] ?? []

  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">{study.title}</h1>
          <p className="text-sm text-gray-500 mt-1">
            {study.study_code} · Phase {study.phase ?? '—'}
          </p>
        </div>
        <span className="inline-flex items-center px-3 py-1 rounded-full text-sm font-medium bg-blue-100 text-blue-800">
          {study.status}
        </span>
      </div>

      {/* Status Transitions */}
      {canConfigure && allowedTransitions.length > 0 && (
        <div className="flex items-center space-x-2">
          <span className="text-sm text-gray-600">Transition to:</span>
          {allowedTransitions.map((status) => (
            <button
              key={status}
              onClick={() => transitionMutation.mutate(status)}
              disabled={transitionMutation.isPending}
              className="px-3 py-1 text-sm border border-blue-300 text-blue-700 rounded-md hover:bg-blue-50 disabled:opacity-50"
            >
              {status.charAt(0).toUpperCase() + status.slice(1)}
            </button>
          ))}
        </div>
      )}

      {/* Study Info */}
      <div className="grid grid-cols-2 gap-4 bg-white border rounded-lg p-4">
        <div>
          <p className="text-xs text-gray-500 uppercase">Created</p>
          <p className="text-sm text-gray-900">{new Date(study.created_at).toLocaleString()}</p>
        </div>
        <div>
          <p className="text-xs text-gray-500 uppercase">Last Updated</p>
          <p className="text-sm text-gray-900">{new Date(study.updated_at).toLocaleString()}</p>
        </div>
        {study.description && (
          <div className="col-span-2">
            <p className="text-xs text-gray-500 uppercase">Description</p>
            <p className="text-sm text-gray-900">{study.description}</p>
          </div>
        )}
      </div>

      {/* Dashboard Link */}
      <div>
        <a
          href={`/studies/${studyId}/dashboard`}
          className="inline-flex items-center px-4 py-2 text-sm bg-gray-100 text-gray-700 rounded-md hover:bg-gray-200 transition"
        >
          View Dashboard →
        </a>
        <a
          href={`/studies/${studyId}/forms`}
          className="ml-2 inline-flex items-center px-4 py-2 text-sm bg-blue-50 text-blue-700 rounded-md hover:bg-blue-100 transition"
        >
          Configure Forms →
        </a>
      </div>

      {/* Versions */}
      <div className="space-y-2">
        <h2 className="text-lg font-semibold text-gray-900">Versions</h2>
        {versions && versions.length > 0 ? (
          <div className="border rounded-lg overflow-hidden">
            <table className="min-w-full divide-y divide-gray-200">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                    Version
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                    Status
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                    Created
                  </th>
                </tr>
              </thead>
              <tbody className="bg-white divide-y divide-gray-200">
          {versions.map((v) => (
                  <tr key={v.id} className="hover:bg-gray-50">
                    <td className="px-4 py-3 text-sm text-gray-900">v{v.version_number}</td>
                    <td className="px-4 py-3 text-sm">
                      <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-green-100 text-green-800">
                        {v.status}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-sm text-gray-600">
                      {new Date(v.created_at).toLocaleDateString()}
                    </td>
                    <td className="px-4 py-3 text-sm">
                      {canPublish && v.status === 'draft' && <button onClick={() => publishMutation.mutate(v.id)} className="text-blue-700">Publish</button>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="text-sm text-gray-500">No versions created yet.</p>
        )}
      </div>

      {canConfigure && <button onClick={() => setShowVersionModal(true)} className="rounded bg-blue-600 px-4 py-2 text-sm text-white">Create draft version</button>}
      {showVersionModal && <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40"><form onSubmit={(e) => { e.preventDefault(); createVersionMutation.mutate() }} className="w-full max-w-md space-y-4 rounded-lg bg-white p-6"><h2 className="text-lg font-semibold">Create draft version</h2><input required placeholder="Version number (e.g. 1.1)" value={versionNumber} onChange={(e) => setVersionNumber(e.target.value)} className="w-full rounded border px-3 py-2 text-sm" /><textarea placeholder="Amendment reason" value={amendmentReason} onChange={(e) => setAmendmentReason(e.target.value)} className="h-24 w-full rounded border px-3 py-2 text-sm" /><div className="flex justify-end gap-2"><button type="button" onClick={() => setShowVersionModal(false)} className="rounded border px-3 py-2 text-sm">Cancel</button><button className="rounded bg-blue-600 px-3 py-2 text-sm text-white">Create</button></div></form></div>}
    </div>
  )
}
