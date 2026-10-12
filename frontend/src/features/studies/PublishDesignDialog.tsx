import { useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { api } from '@/lib/api'

interface DesignValidationCounts {
  forms: number
  sections: number
  fields: number
  visits: number
  scheduled_form_mappings: number
  codelists: number
  codelist_items: number
  edit_checks: number
  subject_phases: number
}

interface DesignValidationIssue {
  code: string
  severity: 'error' | 'warning'
  message: string
}

interface DesignValidationResponse {
  version_id: string
  valid: boolean
  counts: DesignValidationCounts
  issues: DesignValidationIssue[]
}

function errorMessage(error: unknown, fallback: string): string {
  const response = (error as { response?: { data?: { detail?: string; error?: { message?: string } } } })?.response
  return response?.data?.error?.message ?? response?.data?.detail ?? (error instanceof Error ? error.message : fallback)
}

/** Review publication readiness and require explicit confirmation before publish. */
export function PublishDesignDialog({
  versionId,
  versionNumber,
  onPublished,
}: {
  versionId: string
  versionNumber: string
  onPublished: () => void
}) {
  const [open, setOpen] = useState(false)

  const validation = useQuery({
    queryKey: ['design-publication-readiness', versionId],
    queryFn: async () => (await api.get<DesignValidationResponse>(`/designer/versions/${versionId}/validation`)).data,
    enabled: open,
    retry: false,
  })

  const publish = useMutation({
    mutationFn: () => api.post(`/designer/versions/${versionId}/publish`),
    onSuccess: () => {
      setOpen(false)
      onPublished()
    },
  })

  const report = validation.data
  const errors = report?.issues.filter((issue) => issue.severity === 'error') ?? []
  const warnings = report?.issues.filter((issue) => issue.severity === 'warning') ?? []
  const counts = report?.counts

  return (
    <>
      <Button type="button" variant="link" size="sm" onClick={() => setOpen(true)}>Publish</Button>
      <Dialog open={open} onOpenChange={(next) => { if (!publish.isPending) setOpen(next) }}>
        <DialogContent className="max-w-xl">
          <DialogHeader>
            <DialogTitle>Review and publish version {versionNumber}</DialogTitle>
            <DialogDescription>
              Publication makes this design and its definitions immutable. The server validates readiness again when you confirm.
            </DialogDescription>
          </DialogHeader>

          {validation.isLoading ? <p className="text-sm text-muted-foreground" role="status">Validating the complete design…</p> : null}
          {validation.isError ? (
            <Alert variant="destructive"><AlertDescription>{errorMessage(validation.error, 'Could not validate this design.')}</AlertDescription></Alert>
          ) : null}

          {counts ? (
            <div className="grid grid-cols-2 gap-2 rounded-md border bg-muted/30 p-3 text-sm sm:grid-cols-4" aria-label="Design definition counts">
              <span><strong>{counts.forms}</strong> forms</span>
              <span><strong>{counts.fields}</strong> fields</span>
              <span><strong>{counts.visits}</strong> visits</span>
              <span><strong>{counts.scheduled_form_mappings}</strong> mappings</span>
              <span><strong>{counts.codelists}</strong> codelists</span>
              <span><strong>{counts.edit_checks}</strong> edit checks</span>
              <span><strong>{counts.subject_phases}</strong> phases</span>
            </div>
          ) : null}

          {errors.length ? (
            <Alert variant="destructive">
              <AlertDescription>
                <p className="font-medium">Resolve these blocking issues before publishing:</p>
                <ul className="mt-2 list-disc space-y-1 pl-5">{errors.map((issue) => <li key={`${issue.code}-${issue.message}`}>{issue.message}</li>)}</ul>
              </AlertDescription>
            </Alert>
          ) : null}
          {warnings.length ? (
            <Alert variant="warning">
              <AlertDescription>
                <p className="font-medium">Review these warnings:</p>
                <ul className="mt-2 list-disc space-y-1 pl-5">{warnings.map((issue) => <li key={`${issue.code}-${issue.message}`}>{issue.message}</li>)}</ul>
              </AlertDescription>
            </Alert>
          ) : null}
          {report?.valid ? (
            <Alert variant="success"><AlertDescription>This design passed all blocking publication checks.</AlertDescription></Alert>
          ) : null}
          {publish.isError ? (
            <Alert variant="destructive"><AlertDescription>{errorMessage(publish.error, 'Could not publish this design.')}</AlertDescription></Alert>
          ) : null}

          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => setOpen(false)} disabled={publish.isPending}>Cancel</Button>
            <Button
              type="button"
              onClick={() => publish.mutate()}
              disabled={!report?.valid || publish.isPending}
              pending={publish.isPending}
              loadingText="Publishing…"
            >
              Publish version
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  )
}
