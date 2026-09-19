import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { PermissionGuard } from '@/components/guards/PermissionGuard'
import { PERMISSIONS } from '@/lib/permissions'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Textarea } from '@/components/ui/textarea'
import { FormActions, FormField, LoadingState, ErrorState, EmptyState, PageContainer, PageHeader, StatusBadge } from '@/components/patterns'

interface EditCheck {
  id: string
  name: string
  description?: string | null
  rule_json: Record<string, unknown>
  severity: 'info' | 'warning' | 'error' | 'query'
  is_active: boolean
  created_at: string
}

const EMPTY_RULE = '{\n  "field": "field_name",\n  "operator": "not_null"\n}'
const SEVERITIES = ['info', 'warning', 'error', 'query'] as const

export function EditCheckBuilderPage({ studyId }: { studyId: string }) {
  const client = useQueryClient()
  const [selectedId, setSelectedId] = useState('')
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [severity, setSeverity] = useState<EditCheck['severity']>('warning')
  const [ruleText, setRuleText] = useState(EMPTY_RULE)
  const [sampleText, setSampleText] = useState('{}')
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')

  const checksQuery = useQuery({
    queryKey: ['edit-checks', studyId],
    queryFn: async () => (await api.get<EditCheck[]>(`/studies/${studyId}/edit-checks`)).data,
  })
  const selected = useMemo(() => checksQuery.data?.find((item) => item.id === selectedId), [checksQuery.data, selectedId])

  const resetEditor = (check?: EditCheck) => {
    setName(check?.name ?? '')
    setDescription(check?.description ?? '')
    setSeverity(check?.severity ?? 'warning')
    setRuleText(check ? JSON.stringify(check.rule_json, null, 2) : EMPTY_RULE)
    setSampleText('{}')
    setSelectedId(check?.id ?? '')
    setError('')
    setMessage('')
  }

  const save = useMutation({
    mutationFn: async () => {
      let rule: Record<string, unknown>
      try {
        rule = JSON.parse(ruleText) as Record<string, unknown>
      } catch {
        throw new Error('Rule JSON must be valid JSON.')
      }
      if (!name.trim()) throw new Error('A check name is required.')
      const payload = { name: name.trim(), description: description.trim() || null, severity, rule_json: rule, is_active: true }
      return selectedId
        ? api.patch<EditCheck>(`/edit-checks/${selectedId}`, payload)
        : api.post<EditCheck>(`/studies/${studyId}/edit-checks`, payload)
    },
    onSuccess: ({ data }) => {
      client.invalidateQueries({ queryKey: ['edit-checks', studyId] })
      resetEditor(data)
      setMessage('Edit check saved.')
    },
    onError: (err: Error) => {
      setError(err.message || 'Could not save edit check.')
    },
  })

  const test = useMutation({
    mutationFn: async () => {
      if (!selectedId) throw new Error('Save the edit check before testing it.')
      let sampleData: Record<string, unknown>
      try {
        sampleData = JSON.parse(sampleText) as Record<string, unknown>
      } catch {
        throw new Error('Sample data must be valid JSON.')
      }
      return api.post<{ passed: boolean; matched: boolean }>(`/edit-checks/${selectedId}/test`, { sample_data: sampleData })
    },
    onSuccess: ({ data }) => {
      setError('')
      setMessage(data.passed ? 'Sample data passed this check.' : 'Sample data matched this check.')
    },
    onError: (err: Error) => setError(err.message || 'Could not test this edit check.'),
  })

  const run = useMutation({
    mutationFn: () => api.post(`/studies/${studyId}/edit-checks/run`),
    onSuccess: ({ data }) => setMessage(`Validation run complete: ${data.evaluated_form_instances} forms evaluated, ${data.failed_checks} failed checks.`),
    onError: () => setError('Could not run edit checks for this study.'),
  })

  return (
    <PermissionGuard permission={PERMISSIONS.EDITCHECK_CONFIGURE} studyId={studyId}>
      <PageContainer wide>
        <PageHeader
          title="Edit-check builder"
          description="Create safe, declarative validation rules for the current draft version."
          actions={
            <>
              <Button type="button" variant="outline" onClick={() => resetEditor()}>New check</Button>
              <Button type="button" pending={run.isPending} loadingText="Running…" onClick={() => run.mutate()}>
                Run active checks
              </Button>
            </>
          }
        />

        {error ? <Alert variant="destructive"><AlertDescription>{error}</AlertDescription></Alert> : null}
        {message ? <Alert variant="success"><AlertDescription>{message}</AlertDescription></Alert> : null}

        <div className="mt-6 grid gap-6 lg:grid-cols-[19rem_1fr]">
          <Card>
            <CardHeader className="flex-row items-center justify-between space-y-0">
              <CardTitle className="text-base">Checks</CardTitle>
              <span className="text-xs text-muted-foreground">{checksQuery.data?.length ?? 0}</span>
            </CardHeader>
            <CardContent className="space-y-2">
              {checksQuery.isLoading ? <LoadingState label="edit checks" className="border-0 p-0 shadow-none" /> : null}
              {checksQuery.isError ? <ErrorState message="Unable to load edit checks." onRetry={() => void checksQuery.refetch()} /> : null}
              {!checksQuery.isLoading && !checksQuery.isError && !checksQuery.data?.length ? (
                <EmptyState title="No checks configured" description="Create a check to validate study data." className="min-h-32 p-4" />
              ) : null}
              {checksQuery.data?.map((check) => (
                <button
                  type="button"
                  key={check.id}
                  onClick={() => resetEditor(check)}
                  aria-pressed={check.id === selectedId}
                  className={`w-full rounded-md border px-3 py-2 text-left text-sm transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring ${check.id === selectedId ? 'border-primary bg-primary/10 text-primary' : 'border-transparent hover:bg-muted'}`}
                >
                  <span className="block font-medium">{check.name}</span>
                  <StatusBadge label="Check severity" status={check.severity} />
                </button>
              ))}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-base">{selectedId ? 'Edit check' : 'New check'}</CardTitle>
            </CardHeader>
            <CardContent>
              <form className="space-y-4" onSubmit={(event) => { event.preventDefault(); save.mutate() }}>
                <div className="grid gap-4 md:grid-cols-2">
                  <FormField label="Name" id="edit-check-name" name="name" required>
                    <Input value={name} onChange={(event) => setName(event.target.value)} placeholder="AE start before end" required />
                  </FormField>
                  <div className="relative space-y-1.5">
                    <Label htmlFor="edit-check-severity">Severity</Label>
                    <Select value={severity} onValueChange={(value) => setSeverity(value as EditCheck['severity'])}>
                      <SelectTrigger id="edit-check-severity" aria-label="Severity">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {SEVERITIES.map((item) => <SelectItem key={item} value={item}>{item}</SelectItem>)}
                      </SelectContent>
                    </Select>
                  </div>
                </div>
                <FormField label="Description" id="edit-check-description" name="description">
                  <Textarea value={description} onChange={(event) => setDescription(event.target.value)} placeholder="Explain the clinical data-quality rule." />
                </FormField>
                <FormField label="Rule definition (JSON DSL)" id="rule-definition" name="rule" description="Provide a valid JSON object describing the declarative rule.">
                  <Textarea aria-label="Rule definition" value={ruleText} onChange={(event) => setRuleText(event.target.value)} className="min-h-48 font-mono text-sm" />
                </FormField>
                <FormActions pending={save.isPending} submitLabel={selectedId ? 'Update check' : 'Save check'} pendingLabel="Saving…" />
              </form>

              <div className="mt-6 border-t pt-5">
                <h3 className="font-semibold">Test sample data</h3>
                <p className="mt-1 text-sm text-muted-foreground">Testing evaluates the rule without persisting clinical data.</p>
                <Textarea aria-label="Sample data" value={sampleText} onChange={(event) => setSampleText(event.target.value)} className="mt-3 min-h-24 font-mono text-sm" />
                <Button type="button" className="mt-2" variant="outline" onClick={() => test.mutate()} pending={test.isPending} loadingText="Testing…" disabled={!selected}>
                  Test rule
                </Button>
              </div>
            </CardContent>
          </Card>
        </div>
      </PageContainer>
    </PermissionGuard>
  )
}
