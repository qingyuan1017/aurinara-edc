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
import { ConfirmDialog, FormActions, FormField, LoadingState, ErrorState, EmptyState, PageContainer, PageHeader, StatusBadge } from '@/components/patterns'
import { DesignerJsonImport } from '@/features/designer/DesignerJsonImport'
import { DraftGate } from '@/features/designer/shared'

interface EditCheck {
  id: string
  name: string
  description?: string | null
  rule_json: Record<string, unknown>
  severity: 'info' | 'warning' | 'error' | 'query'
  is_active: boolean
  needs_retesting: boolean
  retesting_reason?: string | null
  created_at: string
}

const EMPTY_RULE = '{\n  "schemaVersion": 2,\n  "scope": {},\n  "condition": {\n    "operator": "not_null",\n    "field": { "itemOID": "ITEM.FIELD", "repeat": "current" },\n    "children": []\n  },\n  "actions": [],\n  "execution": { "trigger": "form_save", "priority": 100, "stopOnFailure": true }\n}'
const SEVERITIES = ['info', 'warning', 'error', 'query'] as const
const OPERATORS = ['not_null', 'is_null', '==', '!=', '>', '>=', '<', '<=', 'matches', 'changed', 'exists'] as const
const ACTIONS = ['none', 'open_query', 'close_query', 'set_value', 'clear_value', 'show', 'hide', 'enable', 'disable', 'require', 'make_optional'] as const

function EditCheckBuilderInner({ studyId, versionId, readOnly }: { studyId: string; versionId: string; readOnly: boolean }) {
  const client = useQueryClient()
  const [selectedId, setSelectedId] = useState('')
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [severity, setSeverity] = useState<EditCheck['severity']>('warning')
  const [ruleText, setRuleText] = useState(EMPTY_RULE)
  const [editorMode, setEditorMode] = useState<'visual' | 'json'>('visual')
  const [itemOid, setItemOid] = useState('ITEM.FIELD')
  const [operator, setOperator] = useState<(typeof OPERATORS)[number]>('not_null')
  const [comparisonValue, setComparisonValue] = useState('')
  const [actionType, setActionType] = useState<(typeof ACTIONS)[number]>('none')
  const [actionMessage, setActionMessage] = useState('')
  const [sampleText, setSampleText] = useState('{}')
  const [retestNote, setRetestNote] = useState('')
  const [lastTestMatched, setLastTestMatched] = useState<boolean | null>(null)
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')
  const [deleteOpen, setDeleteOpen] = useState(false)
  const [bulkRetestOpen, setBulkRetestOpen] = useState(false)

  const checksQuery = useQuery({
    queryKey: ['edit-checks', studyId, versionId],
    queryFn: async () => (await api.get<EditCheck[]>(`/designer/studies/${studyId}/edit-checks`, { params: { study_version_id: versionId } })).data,
  })
  const selected = useMemo(() => checksQuery.data?.find((item) => item.id === selectedId), [checksQuery.data, selectedId])
  const pendingRetestCount = useMemo(
    () => checksQuery.data?.filter((item) => item.needs_retesting).length ?? 0,
    [checksQuery.data],
  )

  const resetEditor = (check?: EditCheck) => {
    setName(check?.name ?? '')
    setDescription(check?.description ?? '')
    setSeverity(check?.severity ?? 'warning')
    setRuleText(check ? JSON.stringify(check.rule_json, null, 2) : EMPTY_RULE)
    const rule = check?.rule_json
    const condition = rule?.schemaVersion === 2 ? rule.condition as Record<string, unknown> | undefined : undefined
    const field = condition?.field as Record<string, unknown> | undefined
    const actions = Array.isArray(rule?.actions) ? rule.actions as Record<string, unknown>[] : []
    const firstAction = actions[0]
    const children = condition?.children
    const visualCompatible = rule?.schemaVersion === 2
      && Boolean(field?.itemOID)
      && (!Array.isArray(children) || children.length === 0)
    setEditorMode(!check || visualCompatible ? 'visual' : 'json')
    setItemOid(typeof field?.itemOID === 'string' ? field.itemOID : 'ITEM.FIELD')
    setOperator(OPERATORS.includes(condition?.operator as (typeof OPERATORS)[number]) ? condition?.operator as (typeof OPERATORS)[number] : 'not_null')
    setComparisonValue(condition?.value == null ? '' : String(condition.value))
    setActionType(ACTIONS.includes(firstAction?.type as (typeof ACTIONS)[number]) ? firstAction?.type as (typeof ACTIONS)[number] : 'none')
    setActionMessage(typeof firstAction?.message === 'string' ? firstAction.message : '')
    setSampleText('{}')
    setRetestNote('')
    setLastTestMatched(null)
    setSelectedId(check?.id ?? '')
    setError('')
    setMessage('')
  }

  const save = useMutation({
    mutationFn: async () => {
      let rule: Record<string, unknown>
      if (editorMode === 'visual') {
        if (!itemOid.trim()) throw new Error('An ODM Item OID is required.')
        const value = comparisonValue === '' ? undefined : /^-?\d+(\.\d+)?$/.test(comparisonValue) ? Number(comparisonValue) : comparisonValue
        rule = {
          schemaVersion: 2,
          scope: {},
          condition: { operator, field: { itemOID: itemOid.trim(), repeat: 'current' }, ...(value === undefined ? {} : { value }), children: [] },
          actions: actionType === 'none' ? [] : [{ type: actionType, target: { itemOID: itemOid.trim(), repeat: 'current' }, ...(actionMessage.trim() ? { message: actionMessage.trim() } : {}) }],
          execution: { trigger: 'form_save', priority: 100, stopOnFailure: true },
        }
      } else {
        try {
          rule = JSON.parse(ruleText) as Record<string, unknown>
        } catch {
          throw new Error('Rule JSON must be valid JSON.')
        }
      }
      if (!name.trim()) throw new Error('A check name is required.')
      const payload = { name: name.trim(), description: description.trim() || null, severity, rule_json: rule, is_active: true }
      return selectedId
        ? api.patch<EditCheck>(`/designer/edit-checks/${selectedId}`, payload)
        : api.post<EditCheck>(`/designer/studies/${studyId}/edit-checks`, payload, { params: { study_version_id: versionId } })
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
      return api.post<{ passed: boolean; matched: boolean }>(`/designer/edit-checks/${selectedId}/test`, { sample_data: sampleData })
    },
    onSuccess: ({ data }) => {
      setError('')
      setLastTestMatched(data.matched)
      setMessage(data.passed ? 'Sample data passed this check.' : 'Sample data matched this check.')
    },
    onError: (err: Error) => setError(err.message || 'Could not test this edit check.'),
  })

  const retest = useMutation({
    mutationFn: async () => {
      if (!selectedId || !selected?.needs_retesting) throw new Error('Select a check that requires retesting.')
      if (lastTestMatched === null) throw new Error('Run the sample test before marking this check retested.')
      if (!retestNote.trim()) throw new Error('A review note is required.')
      let sampleData: Record<string, unknown>
      try {
        sampleData = JSON.parse(sampleText) as Record<string, unknown>
      } catch {
        throw new Error('Sample data must be valid JSON.')
      }
      return api.post(`/designer/edit-checks/${selectedId}/retest`, {
        sample_data: sampleData,
        expected_matched: lastTestMatched,
        review_note: retestNote.trim(),
      })
    },
    onSuccess: async () => {
      setError('')
      setRetestNote('')
      setLastTestMatched(null)
      setMessage('Edit check marked as retested. The review was recorded in the audit trail.')
      await client.invalidateQueries({ queryKey: ['edit-checks', studyId] })
    },
    onError: (err: Error) => setError(err.message || 'Could not mark this edit check retested.'),
  })

  const bulkRetest = useMutation({
    mutationFn: (reviewNote: string) => api.post<{ reviewed_count: number; remaining_count: number }>(
      `/designer/studies/${studyId}/edit-checks/retest-all`,
      {
        review_note: reviewNote,
        acknowledge_without_individual_samples: true,
      },
      { params: { study_version_id: versionId } },
    ),
    onSuccess: async ({ data }) => {
      setBulkRetestOpen(false)
      setError('')
      setMessage(`${data.reviewed_count} edit checks marked as retested. Each change was recorded in the audit trail.`)
      await client.invalidateQueries({ queryKey: ['edit-checks', studyId] })
    },
    onError: (err: Error) => setError(err.message || 'Could not complete the bulk retest review.'),
  })

  const remove = useMutation({
    mutationFn: async () => {
      if (!selectedId) throw new Error('Select an edit check to delete.')
      await api.delete(`/designer/edit-checks/${selectedId}`)
    },
    onSuccess: () => {
      client.invalidateQueries({ queryKey: ['edit-checks', studyId] })
      resetEditor()
      setDeleteOpen(false)
      setMessage('Edit check deleted.')
    },
    onError: (err: unknown) => {
      const responseMessage = (err as { response?: { data?: { error?: { message?: string } } } })
        ?.response?.data?.error?.message
      setDeleteOpen(false)
      setError(responseMessage ?? (err instanceof Error ? err.message : 'Could not delete the edit check.'))
    },
  })

  const run = useMutation({
    mutationFn: () => api.post(`/designer/studies/${studyId}/edit-checks/run`),
    onSuccess: ({ data }) => setMessage(`Validation run complete: ${data.evaluated_form_instances} forms evaluated, ${data.failed_checks} failed checks.`),
    onError: () => setError('Could not run edit checks for this study.'),
  })

  return (
      <PageContainer wide>
        <PageHeader
          title="Edit-check builder"
          description={readOnly ? 'Review declarative validation rules retained in this published design version.' : 'Create safe, declarative validation rules for the current draft version.'}
          actions={!readOnly ? (
            <>
              <DesignerJsonImport studyId={studyId} />
              <Button type="button" variant="outline" onClick={() => resetEditor()}>New check</Button>
              <Button type="button" pending={run.isPending} loadingText="Running…" onClick={() => run.mutate()}>
                Run active checks
              </Button>
              {pendingRetestCount > 0 ? (
                <Button type="button" variant="outline" onClick={() => setBulkRetestOpen(true)}>
                  Retest all ({pendingRetestCount})
                </Button>
              ) : null}
            </>
          ) : undefined}
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
                <EmptyState title="No checks configured" description={readOnly ? 'No edit checks were retained in this version.' : 'Create a check to validate study data.'} className="min-h-32 p-4" />
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
                  <span className="mt-1 flex flex-wrap gap-1">
                    <StatusBadge label="Check severity" status={check.severity} />
                    {check.needs_retesting ? <StatusBadge label="Retest status" status="Retest required" /> : null}
                  </span>
                </button>
              ))}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-base">{selectedId ? (readOnly ? 'Check detail' : 'Edit check') : (readOnly ? 'Select a check' : 'New check')}</CardTitle>
            </CardHeader>
            <CardContent>
              {selected?.needs_retesting ? (
                <Alert className="mb-4">
                  <AlertDescription>
                    <strong>Retest required before publication.</strong>
                    {selected.retesting_reason ? <span className="mt-1 block">{selected.retesting_reason}</span> : null}
                  </AlertDescription>
                </Alert>
              ) : null}
              <form className="space-y-4" onSubmit={(event) => { event.preventDefault(); save.mutate() }}>
                <div className="grid gap-4 md:grid-cols-2">
                  <FormField label="Name" id="edit-check-name" name="name" required>
                    <Input value={name} onChange={(event) => setName(event.target.value)} placeholder="AE start before end" required readOnly={readOnly} />
                  </FormField>
                  <div className="relative space-y-1.5">
                    <Label htmlFor="edit-check-severity">Severity</Label>
                    <Select value={severity} onValueChange={(value) => setSeverity(value as EditCheck['severity'])} disabled={readOnly}>
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
                  <Textarea value={description} onChange={(event) => setDescription(event.target.value)} placeholder="Explain the clinical data-quality rule." readOnly={readOnly} />
                </FormField>
                <div className="flex gap-2" role="group" aria-label="Rule editor mode">
                  <Button type="button" variant={editorMode === 'visual' ? 'default' : 'outline'} onClick={() => setEditorMode('visual')} disabled={readOnly && editorMode !== 'visual'}>Visual builder</Button>
                  <Button type="button" variant={editorMode === 'json' ? 'default' : 'outline'} onClick={() => setEditorMode('json')}>Advanced JSON</Button>
                </div>
                {editorMode === 'visual' ? <div className="space-y-4 rounded-md border p-4">
                  <div className="grid gap-4 md:grid-cols-3">
                    <FormField label="ODM Item OID" id="rule-item-oid" name="itemOid"><Input value={itemOid} onChange={(event) => setItemOid(event.target.value)} readOnly={readOnly} /></FormField>
                    <div className="space-y-1.5"><Label htmlFor="rule-operator">Condition</Label><Select value={operator} onValueChange={(value) => setOperator(value as (typeof OPERATORS)[number])} disabled={readOnly}><SelectTrigger id="rule-operator"><SelectValue /></SelectTrigger><SelectContent>{OPERATORS.map((item) => <SelectItem key={item} value={item}>{item}</SelectItem>)}</SelectContent></Select></div>
                    <FormField label="Comparison value" id="rule-value" name="value"><Input value={comparisonValue} onChange={(event) => setComparisonValue(event.target.value)} readOnly={readOnly} disabled={operator === 'is_null' || operator === 'not_null' || operator === 'changed' || operator === 'exists'} /></FormField>
                  </div>
                  <div className="grid gap-4 md:grid-cols-2">
                    <div className="space-y-1.5"><Label htmlFor="rule-action">Matched action</Label><Select value={actionType} onValueChange={(value) => setActionType(value as (typeof ACTIONS)[number])} disabled={readOnly}><SelectTrigger id="rule-action"><SelectValue /></SelectTrigger><SelectContent>{ACTIONS.map((item) => <SelectItem key={item} value={item}>{item}</SelectItem>)}</SelectContent></Select></div>
                    <FormField label="Action message" id="rule-message" name="message"><Input value={actionMessage} onChange={(event) => setActionMessage(event.target.value)} readOnly={readOnly} disabled={actionType === 'none'} /></FormField>
                  </div>
                </div> : <FormField label="Rule definition (JSON DSL)" id="rule-definition" name="rule" description="Advanced editor for nested scopes, conditions, and actions.">
                  <Textarea aria-label="Rule definition" value={ruleText} onChange={(event) => setRuleText(event.target.value)} className="min-h-48 font-mono text-sm" readOnly={readOnly} />
                </FormField>}
                {!readOnly ? <FormActions pending={save.isPending} submitLabel={selectedId ? 'Update check' : 'Save check'} pendingLabel="Saving…" /> : null}
                {selected && !readOnly ? (
                  <Button type="button" variant="destructive" disabled={remove.isPending} onClick={() => setDeleteOpen(true)}>
                    Delete check
                  </Button>
                ) : null}
              </form>

              {!readOnly ? <div className="mt-6 border-t pt-5">
                <h3 className="font-semibold">Test sample data</h3>
                <p className="mt-1 text-sm text-muted-foreground">Testing evaluates the rule without persisting clinical data.</p>
                <Textarea aria-label="Sample data" value={sampleText} onChange={(event) => { setSampleText(event.target.value); setLastTestMatched(null) }} className="mt-3 min-h-24 font-mono text-sm" />
                <Button type="button" className="mt-2" variant="outline" onClick={() => test.mutate()} pending={test.isPending} loadingText="Testing…" disabled={!selected}>
                  Test rule
                </Button>
                {selected?.needs_retesting ? <div className="mt-4 space-y-3 rounded-md border p-4">
                  <FormField label="Retest review note" id="retest-review-note" name="retestReviewNote" description="Explain what was verified. The note and a hash of the sample data are written to the audit trail.">
                    <Textarea value={retestNote} onChange={(event) => setRetestNote(event.target.value)} placeholder="Verified the converted condition and query action against the approved Rave specification." />
                  </FormField>
                  <Button type="button" onClick={() => retest.mutate()} pending={retest.isPending} loadingText="Recording retest…" disabled={lastTestMatched === null || !retestNote.trim()}>
                    Mark as retested
                  </Button>
                  {lastTestMatched === null ? <p className="text-xs text-muted-foreground">Run the sample test after the latest sample-data change to enable this action.</p> : null}
                </div> : null}
              </div> : null}
            </CardContent>
          </Card>
        </div>
        {!readOnly ? <ConfirmDialog
          open={deleteOpen && Boolean(selected)}
          title="Delete edit check?"
          description={<>Delete <strong>{selected?.name}</strong> from this draft design? This action cannot be undone.</>}
          confirmLabel="Confirm delete"
          pending={remove.isPending}
          onConfirm={() => remove.mutate()}
          onCancel={() => setDeleteOpen(false)}
          onOpenChange={setDeleteOpen}
        /> : null}
        {!readOnly ? <ConfirmDialog
          open={bulkRetestOpen}
          title="Mark all edit checks as retested?"
          description={`This will revalidate and clear the retesting hold on ${pendingRetestCount} edit checks. It records a bulk review attestation but does not execute an individual sample case for every rule.`}
          confirmLabel={`Mark all ${pendingRetestCount} retested`}
          pending={bulkRetest.isPending}
          reason={{
            label: 'Bulk review note',
            description: 'Describe the review basis. This note and each rule hash will be retained in the audit trail.',
            placeholder: 'Reviewed the imported rules against the approved Rave specification and conversion report.',
            required: true,
            minLength: 10,
            maxLength: 4000,
          }}
          onConfirm={(reason) => bulkRetest.mutate(reason ?? '')}
          onCancel={() => setBulkRetestOpen(false)}
          onOpenChange={setBulkRetestOpen}
        /> : null}
      </PageContainer>
  )
}

export function EditCheckBuilderPage({ studyId }: { studyId: string }) {
  return (
    <PermissionGuard permission={PERMISSIONS.DESIGNER_EDITCHECK_CONFIGURE} studyId={studyId}>
      <DraftGate studyId={studyId}>
        {(versionId, selection) => <EditCheckBuilderInner studyId={studyId} versionId={versionId} readOnly={selection.isReadOnly} />}
      </DraftGate>
    </PermissionGuard>
  )
}
