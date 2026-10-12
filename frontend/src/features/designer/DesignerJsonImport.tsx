import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { isAxiosError } from 'axios'
import { api } from '@/lib/api'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'

const MAX_FILE_SIZE = 5 * 1024 * 1024
const COLLECTIONS = ['forms', 'edit_checks', 'codelists', 'visits'] as const

type CollectionName = (typeof COLLECTIONS)[number]
type DesignerImportPayload = Record<CollectionName, unknown[]>

interface DesignerImportResult {
  forms_created: number
  sections_created: number
  fields_created: number
  edit_checks_created: number
  codelists_created: number
  codelist_items_created: number
  visits_created: number
}

const EXAMPLE = `{
  "codelists": [{
    "name": "Yes / No", "code": "YES_NO",
    "items": [
      {"code": "Y", "label": "Yes", "display_order": 1},
      {"code": "N", "label": "No", "display_order": 2}
    ]
  }],
  "forms": [{
    "name": "Demographics", "form_code": "DM", "display_order": 1,
    "is_repeating": false,
    "sections": [{
      "name": "Main", "display_order": 1,
      "fields": [{
        "label": "Completed?", "variable_name": "DMCOMP",
        "control_type": "radio", "data_type": "string",
        "display_order": 1, "codelist_code": "YES_NO"
      }]
    }]
  }],
  "edit_checks": [{
    "name": "Completion required", "severity": "error",
    "rule_json": {"field": "DMCOMP", "operator": "not_null"},
    "is_active": true
  }],
  "visits": [{
    "name": "Baseline", "visit_number": 1, "visit_type": "scheduled",
    "target_day": 0, "display_order": 1, "is_required": true
  }]
}`

function parsePayload(text: string): DesignerImportPayload {
  let value: unknown
  try {
    value = JSON.parse(text)
  } catch {
    throw new Error('The selected file is not valid JSON.')
  }
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw new Error('The JSON root must be an object.')
  }
  const record = value as Record<string, unknown>
  const unexpected = Object.keys(record).filter((key) => !COLLECTIONS.includes(key as CollectionName))
  if (unexpected.length) {
    throw new Error(`Unknown top-level key${unexpected.length === 1 ? '' : 's'}: ${unexpected.join(', ')}.`)
  }
  const payload = {} as DesignerImportPayload
  let count = 0
  for (const name of COLLECTIONS) {
    const collection = record[name] ?? []
    if (!Array.isArray(collection)) throw new Error(`"${name}" must be an array.`)
    payload[name] = collection
    count += collection.length
  }
  if (count === 0) {
    throw new Error('The file must contain at least one form, edit check, codelist, or visit.')
  }
  return payload
}

function importError(error: unknown): string {
  if (isAxiosError(error)) {
    const data = error.response?.data as { error?: { message?: string }; detail?: unknown } | undefined
    if (data?.error?.message) return data.error.message
    if (typeof data?.detail === 'string') return data.detail
    if (Array.isArray(data?.detail) && data.detail.length) {
      const first = data.detail[0] as { msg?: unknown; loc?: unknown[] }
      if (typeof first.msg === 'string') {
        const path = Array.isArray(first.loc) ? first.loc.slice(1).join('.') : ''
        return path ? `${path}: ${first.msg}` : first.msg
      }
    }
  }
  return error instanceof Error ? error.message : 'The definitions could not be imported.'
}

export function DesignerJsonImport({ studyId }: { studyId: string }) {
  const client = useQueryClient()
  const [open, setOpen] = useState(false)
  const [filename, setFilename] = useState('')
  const [jsonText, setJsonText] = useState('')
  const [payload, setPayload] = useState<DesignerImportPayload | null>(null)
  const [error, setError] = useState('')
  const [result, setResult] = useState<DesignerImportResult | null>(null)

  const reset = () => {
    setFilename('')
    setJsonText('')
    setPayload(null)
    setError('')
    setResult(null)
  }

  const importMutation = useMutation({
    mutationFn: async () => {
      if (!payload) throw new Error('Select a JSON file first.')
      return (await api.post<DesignerImportResult>(`/designer/studies/${studyId}/bulk-import`, payload)).data
    },
    onSuccess: (data) => {
      setResult(data)
      setError('')
      client.invalidateQueries({ queryKey: ['form-definitions', studyId] })
      client.invalidateQueries({ queryKey: ['designer-codelists', studyId] })
      client.invalidateQueries({ queryKey: ['edit-checks', studyId] })
      client.invalidateQueries({ queryKey: ['designer-visits'] })
    },
    onError: (reason) => setError(importError(reason)),
  })

  const selectFile = async (file?: File) => {
    reset()
    if (!file) return
    setFilename(file.name)
    if (file.size > MAX_FILE_SIZE) {
      setError('The JSON file must be 5 MB or smaller.')
      return
    }
    try {
      const text = await file.text()
      setJsonText(text)
      setPayload(parsePayload(text))
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'The selected file could not be read.')
    }
  }

  const validatePastedJson = () => {
    setFilename('')
    setPayload(null)
    setResult(null)
    setError('')
    try {
      setPayload(parsePayload(jsonText))
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'The pasted JSON could not be read.')
    }
  }

  const counts = payload
    ? COLLECTIONS.map((name) => `${payload[name].length} ${name.replace('_', ' ')}`).join(' · ')
    : ''

  return (
    <>
      <Button type="button" variant="outline" onClick={() => { reset(); setOpen(true) }}>Import JSON</Button>
      <Dialog open={open} onOpenChange={(next) => { setOpen(next); if (!next) reset() }}>
        <DialogContent className="max-h-[90vh] max-w-2xl overflow-y-auto">
          <DialogHeader>
            <DialogTitle>Import Designer definitions</DialogTitle>
            <DialogDescription>
              Upload forms, edit checks, codelists, and visits to the current draft. The entire file is rejected if any item is invalid.
            </DialogDescription>
          </DialogHeader>

          {error ? <Alert variant="destructive"><AlertDescription>{error}</AlertDescription></Alert> : null}
          {result ? (
            <Alert variant="success">
              <AlertDescription>
                Imported {result.forms_created} forms ({result.sections_created} sections, {result.fields_created} fields), {result.codelists_created} codelists ({result.codelist_items_created} items), {result.edit_checks_created} edit checks, and {result.visits_created} visits.
              </AlertDescription>
            </Alert>
          ) : null}

          {!result ? (
            <>
              <div className="space-y-2">
                <Label htmlFor="designer-json-file">JSON file</Label>
                <Input
                  id="designer-json-file"
                  type="file"
                  accept="application/json,.json"
                  onChange={(event) => void selectFile(event.target.files?.[0])}
                  disabled={importMutation.isPending}
                />
                <p className="text-xs text-muted-foreground">Maximum size 5 MB. Existing definitions are preserved; imported definitions are added.</p>
              </div>
              <div className="flex items-center gap-3 text-xs uppercase tracking-wide text-muted-foreground" aria-hidden="true">
                <span className="h-px flex-1 bg-border" />
                or paste JSON
                <span className="h-px flex-1 bg-border" />
              </div>
              <div className="space-y-2">
                <Label htmlFor="designer-json-text">JSON text</Label>
                <Textarea
                  id="designer-json-text"
                  value={jsonText}
                  onChange={(event) => {
                    setJsonText(event.target.value)
                    setFilename('')
                    setPayload(null)
                    setResult(null)
                    setError('')
                  }}
                  placeholder='{"forms": [], "edit_checks": [], "codelists": [], "visits": []}'
                  className="min-h-40 font-mono text-xs"
                  disabled={importMutation.isPending}
                />
                <Button type="button" variant="outline" size="sm" onClick={validatePastedJson} disabled={!jsonText.trim() || importMutation.isPending}>
                  Validate JSON text
                </Button>
              </div>
              {payload ? (
                <div className="rounded-md border bg-muted/30 p-3 text-sm" role="status">
                  <span className="font-medium">{filename || 'Pasted JSON'}</span>
                  <span className="ml-2 text-muted-foreground">{counts}</span>
                </div>
              ) : null}
              <details className="rounded-md border p-3 text-sm">
                <summary className="cursor-pointer font-medium">JSON format example</summary>
                <pre className="mt-3 overflow-x-auto whitespace-pre-wrap rounded bg-muted p-3 text-xs">{EXAMPLE}</pre>
                <p className="mt-2 text-xs text-muted-foreground">Use codelist_code on a field to reference a codelist in the same file or one already in the draft.</p>
              </details>
            </>
          ) : null}

          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => setOpen(false)}>{result ? 'Done' : 'Cancel'}</Button>
            {!result ? (
              <Button type="button" onClick={() => importMutation.mutate()} disabled={!payload || importMutation.isPending} pending={importMutation.isPending} loadingText="Importing…">
                Import definitions
              </Button>
            ) : null}
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  )
}
