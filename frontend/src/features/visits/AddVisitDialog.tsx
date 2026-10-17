import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'

interface AddableVisitDefinition {
  id: string
  name: string
  visit_type: string
  definition_kind: 'visit' | 'cycle_visit'
}

interface CreatedVisit {
  id: string
}

export function AddVisitDialog({ subjectId, onCreated }: { subjectId: string; onCreated?: (visit: CreatedVisit) => void }) {
  const client = useQueryClient()
  const [open, setOpen] = useState(false)
  const [definitionId, setDefinitionId] = useState('')
  const [visitDate, setVisitDate] = useState('')
  const [error, setError] = useState('')
  const definitions = useQuery({
    queryKey: ['addable-visits', subjectId],
    enabled: Boolean(subjectId),
    queryFn: async () => (await api.get<AddableVisitDefinition[]>(`/subjects/${subjectId}/visits/addable`)).data,
  })
  const choices = definitions.data ?? []
  const create = useMutation({
    mutationFn: async () => {
      if (!definitionId) throw new Error('Select a visit to add.')
      return (await api.post<CreatedVisit>(`/subjects/${subjectId}/visits/addable`, {
        visit_definition_id: definitionId,
        visit_date: visitDate || null,
      })).data
    },
    onSuccess: (visit) => {
      setError(''); setOpen(false); setDefinitionId(''); setVisitDate('')
      client.invalidateQueries({ queryKey: ['visits', subjectId] })
      client.invalidateQueries({ queryKey: ['casebook', subjectId] })
      client.invalidateQueries({ queryKey: ['data-entry-casebook', subjectId] })
      onCreated?.(visit)
    },
    onError: () => setError('Could not add the visit.'),
  })

  if (!choices.length) return null

  return (
    <>
      <Button type="button" onClick={() => { setError(''); setOpen(true) }}>Add visit</Button>
      <Dialog open={open} onOpenChange={(next) => { setOpen(next); if (!next) setError('') }}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Add visit</DialogTitle>
            <DialogDescription>Choose a visit that the published design allows users to add.</DialogDescription>
          </DialogHeader>
          <form className="space-y-4" onSubmit={(event) => { event.preventDefault(); create.mutate() }}>
            {error ? <Alert variant="destructive"><AlertDescription>{error}</AlertDescription></Alert> : null}
            <div className="space-y-1.5">
              <Label htmlFor="addable-visit-definition">Visit</Label>
              <select id="addable-visit-definition" required value={definitionId} onChange={(event) => setDefinitionId(event.target.value)} className="h-10 w-full rounded-md border border-input bg-background px-3">
                <option value="">Select visit</option>
                {choices.map((visit) => <option key={visit.id} value={visit.id}>{visit.name} · {visit.visit_type}</option>)}
              </select>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="addable-visit-date">Visit date</Label>
              <Input id="addable-visit-date" type="date" value={visitDate} onChange={(event) => setVisitDate(event.target.value)} />
            </div>
            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => setOpen(false)}>Cancel</Button>
              <Button type="submit" pending={create.isPending} loadingText="Adding…">Add visit</Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </>
  )
}
