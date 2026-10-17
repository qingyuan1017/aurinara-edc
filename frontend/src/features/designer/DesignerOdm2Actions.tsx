import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useRef, useState } from 'react'

import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { api, getApiErrorMessage } from '@/lib/api'
import { setActiveDesignerVersion } from './shared'

interface ValidationIssue { code: string; message: string; path?: string | null }
interface ValidationReport {
  valid: boolean
  counts: Record<string, number>
  errors: ValidationIssue[]
  warnings: ValidationIssue[]
  extensionsUsed: string[]
}

interface ImportResult {
  studyVersionId: string
}

type ImportDestination = 'new' | 'current'

function metadataVersionName(document: Record<string, unknown>): string {
  const study = document.study
  if (!study || typeof study !== 'object' || Array.isArray(study)) return ''
  const metadata = (study as Record<string, unknown>).metaDataVersion
  if (!metadata || typeof metadata !== 'object' || Array.isArray(metadata)) return ''
  const name = (metadata as Record<string, unknown>).name
  return typeof name === 'string' ? name.slice(0, 20) : ''
}

export function DesignerOdm2Actions({ studyId, versionId, allowImport }: { studyId: string; versionId: string; allowImport: boolean }) {
  const client = useQueryClient()
  const inputRef = useRef<HTMLInputElement>(null)
  const [open, setOpen] = useState(false)
  const [filename, setFilename] = useState('')
  const [payload, setPayload] = useState<Record<string, unknown> | null>(null)
  const [report, setReport] = useState<ValidationReport | null>(null)
  const [error, setError] = useState('')
  const [destination, setDestination] = useState<ImportDestination>('new')
  const [versionNumber, setVersionNumber] = useState('')

  const reset = () => {
    setFilename('')
    setPayload(null)
    setReport(null)
    setError('')
    setDestination('new')
    setVersionNumber('')
    if (inputRef.current) inputRef.current.value = ''
  }

  const validate = useMutation({
    mutationFn: async (document: Record<string, unknown>) =>
      (await api.post<ValidationReport>(`/designer/studies/${studyId}/odm2/validate`, document)).data,
    onSuccess: setReport,
    onError: (reason) => setError(getApiErrorMessage(reason, 'The ODM document could not be validated.')),
  })

  const importDocument = useMutation({
    mutationFn: async () => {
      if (!payload) throw new Error('Select and validate an ODM document first.')
      const params = destination === 'new'
        ? { version_number: versionNumber.trim() }
        : { target_version_id: versionId }
      return (await api.post<ImportResult>(`/designer/studies/${studyId}/odm2/import`, payload, { params })).data
    },
    onSuccess: async (result) => {
      if (destination === 'new') setActiveDesignerVersion(studyId, result.studyVersionId)
      await Promise.all([
        client.invalidateQueries({ queryKey: ['designer'] }),
        client.invalidateQueries({ queryKey: ['study-versions', studyId] }),
      ])
      setOpen(false)
    },
    onError: (reason) => setError(getApiErrorMessage(reason, 'The ODM import failed. No design metadata was committed.')),
  })

  async function selectFile(file?: File) {
    setError('')
    setReport(null)
    setPayload(null)
    setFilename(file?.name ?? '')
    setVersionNumber('')
    if (!file) return
    if (file.size > 10 * 1024 * 1024) {
      setError('The ODM JSON file must be 10 MB or smaller.')
      return
    }
    try {
      const parsed = JSON.parse(await file.text()) as unknown
      if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) throw new Error('root')
      const document = parsed as Record<string, unknown>
      setPayload(document)
      setVersionNumber(metadataVersionName(document))
      validate.mutate(document)
    } catch {
      setError('The selected file is not a valid ODM JSON object.')
    }
  }

  async function exportDocument() {
    setError('')
    try {
      const response = await api.get(`/designer/studies/${studyId}/versions/${versionId}/odm2`)
      const blob = new Blob([JSON.stringify(response.data, null, 2)], { type: 'application/json' })
      const url = URL.createObjectURL(blob)
      const anchor = document.createElement('a')
      anchor.href = url
      anchor.download = `odm-2.0-${versionId}.json`
      anchor.click()
      URL.revokeObjectURL(url)
    } catch (reason) {
      setError(getApiErrorMessage(reason, 'The ODM export could not be generated.'))
    }
  }

  const canImport = Boolean(
    payload
    && report?.valid
    && (destination === 'current' || versionNumber.trim()),
  )

  return <>
    <div className="flex gap-2">
      <Button type="button" variant="outline" onClick={() => void exportDocument()}>Export ODM 2.0</Button>
      {allowImport ? <Button type="button" variant="outline" onClick={() => { reset(); setOpen(true) }}>Import ODM 2.0</Button> : null}
    </div>
    {error && !open ? <span className="sr-only" role="alert">{error}</span> : null}
    <Dialog open={allowImport && open} onOpenChange={(next) => { setOpen(next); if (!next) reset() }}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Import ODM 2.0 JSON</DialogTitle>
          <DialogDescription>Validate the complete document, then import it atomically into a new or empty draft.</DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="odm2-file">ODM JSON file</Label>
            <Input ref={inputRef} id="odm2-file" type="file" accept="application/json,.json" onChange={(event) => void selectFile(event.target.files?.[0])} />
          </div>
          {filename ? <p className="text-sm">{filename}</p> : null}
          {error ? <Alert variant="destructive"><AlertDescription>{error}</AlertDescription></Alert> : null}
          {validate.isPending ? <p className="text-sm text-muted-foreground">Validating ODM references…</p> : null}
          {report ? <Alert variant={report.valid ? 'default' : 'destructive'}><AlertDescription>
            {report.valid ? `Valid document: ${Object.entries(report.counts).map(([name, count]) => `${count} ${name.replaceAll('_', ' ')}`).join(' · ')}` : report.errors.map((item) => `${item.path ? `${item.path}: ` : ''}${item.message}`).join(' ')}
          </AlertDescription></Alert> : null}
          <fieldset className="space-y-3" disabled={importDocument.isPending}>
            <legend className="text-sm font-medium">Import destination</legend>
            <label className="flex items-start gap-3 rounded-md border p-3">
              <input type="radio" name="odm-import-destination" value="new" checked={destination === 'new'} onChange={() => setDestination('new')} />
              <span><span className="block text-sm font-medium">Create a new draft</span><span className="block text-xs text-muted-foreground">Recommended. Existing design versions remain unchanged.</span></span>
            </label>
            <label className="flex items-start gap-3 rounded-md border p-3">
              <input type="radio" name="odm-import-destination" value="current" checked={destination === 'current'} onChange={() => setDestination('current')} />
              <span><span className="block text-sm font-medium">Populate the selected draft</span><span className="block text-xs text-muted-foreground">The selected draft must contain no forms, visits, codelists, rules, units, schedules, coding settings, or access definitions.</span></span>
            </label>
          </fieldset>
          {destination === 'new' ? <div className="space-y-2">
            <Label htmlFor="odm-version-number">New draft version number</Label>
            <Input id="odm-version-number" value={versionNumber} maxLength={20} onChange={(event) => setVersionNumber(event.target.value)} placeholder="For example, 2.0-ALS" disabled={importDocument.isPending} />
            <p className="text-xs text-muted-foreground">Must be unique for this study. The ODM metadata version name is used by default.</p>
          </div> : null}
        </div>
        <DialogFooter>
          <Button type="button" variant="outline" onClick={() => setOpen(false)}>Cancel</Button>
          <Button type="button" disabled={!canImport || importDocument.isPending} onClick={() => importDocument.mutate()}>
            {destination === 'new' ? 'Import as new draft' : 'Import into selected draft'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  </>
}
