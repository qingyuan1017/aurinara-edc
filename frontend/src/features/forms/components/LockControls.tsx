import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { usePermission, PERMISSIONS } from '@/lib/permissions'

interface LockControlsProps { formInstanceId: string; isFrozen: boolean; isLocked: boolean; onChanged: (state: { isFrozen: boolean; isLocked: boolean }) => void }

export function LockControls({ formInstanceId, isFrozen, isLocked, onChanged }: LockControlsProps) {
  const canManage = usePermission(PERMISSIONS.LOCK_MANAGE)
  const [reason, setReason] = useState('')
  const [unlocking, setUnlocking] = useState<'unfreeze' | 'unlock' | null>(null)
  const [error, setError] = useState('')
  const mutation = useMutation({
    mutationFn: ({ verb, body }: { verb: string; body?: object }) => api.post(`/form-instances/${formInstanceId}/${verb}`, body),
    onSuccess: (_response, variables) => { setReason(''); setUnlocking(null); setError(''); onChanged(variables.verb === 'freeze' ? { isFrozen: true, isLocked } : variables.verb === 'lock' ? { isFrozen, isLocked: true } : variables.verb === 'unfreeze' ? { isFrozen: false, isLocked } : { isFrozen, isLocked: false }) },
    onError: () => setError('The control change could not be completed.'),
  })
  if (!canManage) return null
  const submitUnlock = () => { if (!reason.trim()) { setError('A reason is required to remove a freeze or lock.'); return } mutation.mutate({ verb: unlocking!, body: { reason: reason.trim() } }) }
  const closeUnlock = () => { if (mutation.isPending) return; setUnlocking(null); setReason(''); setError('') }

  return <>
    <Card>
      <CardHeader className="pb-3"><CardTitle className="text-base">Freeze and lock controls</CardTitle><p className="text-xs text-muted-foreground">Controls are audited and disabled inputs remain protected while active.</p></CardHeader>
      <CardContent className="space-y-3">
        <div className="flex flex-wrap gap-2">{isFrozen ? <Button size="sm" variant="outline" onClick={() => setUnlocking('unfreeze')}>Unfreeze</Button> : <Button size="sm" variant="outline" onClick={() => mutation.mutate({ verb: 'freeze' })} disabled={mutation.isPending || isLocked}>Freeze</Button>}{isLocked ? <Button size="sm" variant="outline" onClick={() => setUnlocking('unlock')}>Unlock</Button> : <Button size="sm" variant="destructive" onClick={() => mutation.mutate({ verb: 'lock' })} disabled={mutation.isPending}>Lock</Button>}</div>
        {error && !unlocking ? <Alert variant="destructive"><AlertDescription>{error}</AlertDescription></Alert> : null}
      </CardContent>
    </Card>
    <Dialog open={Boolean(unlocking)} onOpenChange={(open) => { if (!open) closeUnlock() }}>
      <DialogContent>
        <DialogHeader><DialogTitle>Remove {unlocking}</DialogTitle><DialogDescription>Document why this freeze or lock is being removed. This change is audited.</DialogDescription></DialogHeader>
        <div className="space-y-1.5"><Label htmlFor="lock-control-reason">Reason for {unlocking}</Label><Textarea id="lock-control-reason" autoFocus value={reason} onChange={(event) => { setReason(event.target.value); if (error) setError('') }} placeholder="Document why this control is being removed." aria-invalid={Boolean(error)} />{error ? <p role="alert" className="text-sm text-destructive">{error}</p> : null}</div>
        <DialogFooter><Button size="sm" variant="ghost" onClick={closeUnlock}>Cancel</Button><Button size="sm" onClick={submitUnlock} pending={mutation.isPending} loadingText="Saving…">Confirm</Button></DialogFooter>
      </DialogContent>
    </Dialog>
  </>
}
