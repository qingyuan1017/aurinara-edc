import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { usePermission, PERMISSIONS } from '@/lib/permissions'

interface StudyDetail {
  id: string
  code: string
  title: string
  phase: string
  status: string
  description?: string
  created_at: string
  updated_at: string
}

interface StudyVersion {
  id: string
  version_number: number
  status: string
  created_at: string
}

const STATUS_TRANSITIONS: Record<string, string[]> = {
  draft: ['active'],
  active: ['paused', 'closed'],
  paused: ['active', 'closed'],
  closed: [],
}

export function StudyDetailPage({ studyId }: { studyId: string }) {
  const queryClient = useQueryClient()
  const canConfigure = usePermission(PERMISSIONS.STUDY_CONFIGURE)

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
      const { data } = await api.get<{ items: StudyVersion[] }>(`/studies/${studyId}/versions`)
      return data.items
    },
  })

  const transitionMutation = useMutation({
    mutationFn: async (newStatus: string) => {
      await api.patch(`/studies/${studyId}`, { status: newStatus })
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['study', studyId] })
      queryClient.invalidateQueries({ queryKey: ['studies'] })
    },
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
            {study.code} · Phase {study.phase}
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
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="text-sm text-gray-500">No versions created yet.</p>
        )}
      </div>
    </div>
  )
}
