import * as React from 'react'
import { api } from '@/lib/api'
import { usePermission, PERMISSIONS } from '@/lib/permissions'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'

export interface SignatureRecord { id: string; object_type: 'form' | 'subject' | string; object_id: string; signed_by: string; signed_at: string; signature_meaning: string; data_hash: string; status: 'valid' | 'stale' | string; stale_reason?: string | null }
interface SignatureDialogProps { objectType: 'form' | 'subject'; objectId: string; buttonLabel?: string; onSigned?: (signature: SignatureRecord) => void }

/** Re-authenticated signature trigger and accessible shared dialog. */
export function SignatureDialog({ objectType, objectId, buttonLabel, onSigned }: SignatureDialogProps) {
  const canSign = usePermission(PERMISSIONS.SIGNATURE_SIGN)
  const [open, setOpen] = React.useState(false)
  const [meaning, setMeaning] = React.useState('')
  const [password, setPassword] = React.useState('')
  const [error, setError] = React.useState('')
  const [saving, setSaving] = React.useState(false)

  if (!canSign) return null
  const reset = () => { if (saving) return; setOpen(false); setMeaning(''); setPassword(''); setError('') }
  const submit = async () => {
    if (!meaning.trim()) { setError('Signature meaning is required.'); return }
    if (!password) { setError('Enter your password to re-authenticate.'); return }
    setSaving(true); setError('')
    try {
      const path = objectType === 'form' ? `/form-instances/${objectId}/sign` : `/subjects/${objectId}/sign`
      const { data } = await api.post<SignatureRecord>(path, { meaning: meaning.trim(), password })
      onSigned?.(data); setSaving(false); reset()
    } catch (cause: unknown) {
      const response = cause as { response?: { data?: { error?: { message?: string }; detail?: string } } }
      setError(response.response?.data?.error?.message ?? response.response?.data?.detail ?? 'Signature could not be recorded.')
    } finally { setSaving(false) }
  }

  return <>
    <Button type="button" variant="outline" onClick={() => setOpen(true)}>{buttonLabel ?? `Sign ${objectType}`}</Button>
    <Dialog open={open} onOpenChange={(nextOpen) => { if (!nextOpen) reset() }}>
      <DialogContent>
        <DialogHeader><DialogTitle>Electronic signature</DialogTitle><DialogDescription>Re-authenticate with your password to attest that this {objectType} data is accurate and complete.</DialogDescription></DialogHeader>
        <div className="space-y-4">
          <div className="space-y-1.5"><Label htmlFor="signature-meaning">Signature meaning</Label><Textarea id="signature-meaning" value={meaning} onChange={(event) => setMeaning(event.target.value)} placeholder="I attest this data is accurate and complete." autoFocus /></div>
          <div className="space-y-1.5"><Label htmlFor="signature-password">Password</Label><Input id="signature-password" type="password" value={password} onChange={(event) => setPassword(event.target.value)} autoComplete="current-password" /></div>
          {error ? <Alert variant="destructive"><AlertDescription>{error}</AlertDescription></Alert> : null}
        </div>
        <DialogFooter><Button type="button" variant="ghost" onClick={reset} disabled={saving}>Cancel</Button><Button type="button" pending={saving} loadingText="Signing…" onClick={submit}>Confirm signature</Button></DialogFooter>
      </DialogContent>
    </Dialog>
  </>
}
