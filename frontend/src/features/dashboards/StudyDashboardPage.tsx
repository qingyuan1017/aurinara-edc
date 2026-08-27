import { useQuery } from '@tanstack/react-query'
import { api } from '@/lib/api'

interface DashboardMetrics {
  subject_counts: {
    enrolled: number
    screening: number
    completed: number
    withdrawn: number
    total: number
  }
  open_query_count: number
  form_completion_percentage: number
}

function StatCard({ label, value, color }: { label: string; value: string | number; color: string }) {
  return (
    <div className={`p-4 bg-white border rounded-lg ${color}`}>
      <p className="text-xs text-gray-500 uppercase tracking-wider">{label}</p>
      <p className="mt-1 text-2xl font-bold text-gray-900">{value}</p>
    </div>
  )
}

export function StudyDashboardPage({ studyId }: { studyId: string }) {
  const { data, isLoading, error } = useQuery({
    queryKey: ['study-dashboard', studyId],
    queryFn: async () => {
      const { data } = await api.get<DashboardMetrics>(`/studies/${studyId}/dashboard`)
      return data
    },
  })

  if (isLoading) {
    return <p className="p-6 text-gray-500">Loading dashboard…</p>
  }

  if (error) {
    return <p className="p-6 text-red-600">Failed to load dashboard metrics.</p>
  }

  if (!data) {
    return null
  }

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-gray-900">Study Dashboard</h1>
        <a
          href={`/studies/${studyId}`}
          className="text-sm text-blue-600 hover:underline"
        >
          ← Back to Study
        </a>
      </div>

      {/* Subject Counts */}
      <section className="space-y-2">
        <h2 className="text-lg font-semibold text-gray-800">Subjects</h2>
        <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
          <StatCard label="Total" value={data.subject_counts.total} color="border-l-4 border-l-gray-400" />
          <StatCard label="Enrolled" value={data.subject_counts.enrolled} color="border-l-4 border-l-blue-500" />
          <StatCard label="Screening" value={data.subject_counts.screening} color="border-l-4 border-l-yellow-500" />
          <StatCard label="Completed" value={data.subject_counts.completed} color="border-l-4 border-l-green-500" />
          <StatCard label="Withdrawn" value={data.subject_counts.withdrawn} color="border-l-4 border-l-red-500" />
        </div>
      </section>

      {/* Query & Form Metrics */}
      <section className="space-y-2">
        <h2 className="text-lg font-semibold text-gray-800">Data Quality</h2>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <StatCard
            label="Open Queries"
            value={data.open_query_count}
            color="border-l-4 border-l-orange-500"
          />
          <div className="p-4 bg-white border rounded-lg border-l-4 border-l-purple-500">
            <p className="text-xs text-gray-500 uppercase tracking-wider">Form Completion</p>
            <p className="mt-1 text-2xl font-bold text-gray-900">
              {data.form_completion_percentage.toFixed(1)}%
            </p>
            <div className="mt-2 w-full bg-gray-200 rounded-full h-2">
              <div
                className="bg-purple-500 h-2 rounded-full transition-all"
                style={{ width: `${Math.min(data.form_completion_percentage, 100)}%` }}
              />
            </div>
          </div>
        </div>
      </section>
    </div>
  )
}
