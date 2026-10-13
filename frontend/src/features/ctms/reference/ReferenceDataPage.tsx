import { useState, type FormEvent } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { DataTableShell, DetailCard, PageContainer, PageHeader } from '@/components/patterns'
import { PERMISSIONS, usePermission } from '@/lib/permissions'
import { ctmsApi, ctmsKeys, useCTMSReferenceValues, type CTMSReferenceCategory, type CTMSReferenceValue } from '../api'

const CATEGORIES: readonly { value: CTMSReferenceCategory; label: string; usage: string }[] = [
  { value: 'country', label: 'Country', usage: 'Used by Site, Depot, and Staff country fields.' },
  { value: 'participating_organization_type', label: 'Participating Organization Type', usage: 'Used by the Participating Organization type field.' },
  { value: 'therapeutic_area', label: 'Therapeutic Area', usage: 'Used by the operational study therapeutic area field.' },
  { value: 'indication', label: 'Indication', usage: 'Used by the operational study indication field.' },
  { value: 'milestone_type', label: 'Milestone Type', usage: 'Used by project milestones so users select a controlled type.' },
  { value: 'project_status', label: 'Project Status', usage: 'Defines the ordered columns and status dropdown for project activities.' },
]

function normalizeCode(value: string) {
  return value.trim().toUpperCase().replace(/[^A-Z0-9]+/g, '_').replace(/^_|_$/g, '').slice(0, 100)
}

export function ReferenceDataPage() {
  const canManage = usePermission(PERMISSIONS.CTMS_OPERATIONAL_STUDY_MANAGEMENT)
  const query = useCTMSReferenceValues(undefined, null)
  const client = useQueryClient()
  const [category, setCategory] = useState<CTMSReferenceCategory>('country')
  const [label, setLabel] = useState('')
  const [code, setCode] = useState('')
  const [sortOrder, setSortOrder] = useState('0')
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [editing, setEditing] = useState<CTMSReferenceValue | null>(null)
  const values = (query.data?.items ?? []).filter((item) => item.category === category)
  const selectedCategory = CATEGORIES.find((item) => item.value === category) ?? CATEGORIES[0]

  const create = useMutation({
    mutationFn: () => ctmsApi.createReferenceValue({ category, code: normalizeCode(code || label), label: label.trim(), sort_order: Number(sortOrder) }),
    onSuccess: async () => {
      setLabel('')
      setCode('')
      setSortOrder('0')
      setEditing(null)
      setDrawerOpen(false)
      await client.invalidateQueries({ queryKey: ctmsKeys.all })
    },
  })
  const update = useMutation({
    mutationFn: () => ctmsApi.updateReferenceValue(editing!.id, { label: label.trim(), sort_order: Number(sortOrder) }),
    onSuccess: async () => {
      setLabel('')
      setCode('')
      setSortOrder('0')
      setEditing(null)
      setDrawerOpen(false)
      await client.invalidateQueries({ queryKey: ctmsKeys.all })
    },
  })
  const toggle = useMutation({
    mutationFn: (value: CTMSReferenceValue) => ctmsApi.updateReferenceValue(value.id, { active: !value.active }),
    onSuccess: () => client.invalidateQueries({ queryKey: ctmsKeys.all }),
  })

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (editing) update.mutate()
    else create.mutate()
  }

  const openCreate = () => {
    setEditing(null)
    setLabel('')
    setCode('')
    setSortOrder('0')
    setDrawerOpen(true)
  }

  const openEdit = (value: CTMSReferenceValue) => {
    setEditing(value)
    setLabel(value.label)
    setCode(value.code)
    setSortOrder(String(value.sort_order))
    setDrawerOpen(true)
  }

  return <PageContainer wide>
    <PageHeader title="Reference data" description="Configure reusable values that populate CTMS dropdown fields and project workflow columns." actions={canManage ? <Button type="button" onClick={openCreate}>Add value</Button> : undefined} />
    {toggle.error ? <p role="alert" className="mb-4 text-sm text-destructive">Unable to change this value. Project Status must always keep at least one active column.</p> : null}
    <Tabs value={category} onValueChange={(value) => { setCategory(value as CTMSReferenceCategory); setDrawerOpen(false); setEditing(null); create.reset(); update.reset() }}>
      <div className="overflow-x-auto pb-1">
        <TabsList className="h-auto min-w-max" aria-label="Reference data categories">
          {CATEGORIES.map((item) => <TabsTrigger key={item.value} value={item.value}>{item.label}</TabsTrigger>)}
        </TabsList>
      </div>
      {CATEGORIES.map((item) => <TabsContent key={item.value} value={item.value} className="space-y-6">
        <DataTableShell label={`${item.label} reference values`} loading={query.isLoading} error={Boolean(query.error)} errorMessage="Reference values could not be loaded." empty={values.length === 0} emptyTitle={`No ${item.label.toLowerCase()} values configured.`}>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {values.map((value) => <DetailCard key={value.id} title={value.label} description={value.code} status={<span className="text-xs text-muted-foreground">{value.active ? 'Active' : 'Inactive'}</span>} footer={canManage ? <div className="flex gap-2"><Button type="button" size="sm" variant="outline" onClick={() => openEdit(value)}>Edit</Button><Button type="button" size="sm" variant="outline" onClick={() => toggle.mutate(value)} disabled={toggle.isPending}>{value.active ? 'Deactivate' : 'Activate'}</Button></div> : undefined}>
              <p className="text-xs text-muted-foreground">Sort order: {value.sort_order}</p>
            </DetailCard>)}
          </div>
        </DataTableShell>
      </TabsContent>)}
    </Tabs>
    <Sheet open={drawerOpen} onOpenChange={(open) => { setDrawerOpen(open); if (!open) { setEditing(null); create.reset(); update.reset() } }}><SheetContent side="right" className="w-full overflow-y-auto sm:max-w-2xl"><SheetHeader className="pr-8"><SheetTitle>{`${editing ? 'Edit' : 'Add'} ${selectedCategory.label}`}</SheetTitle><SheetDescription>{selectedCategory.usage}</SheetDescription></SheetHeader><form className="mt-2 grid gap-4 pt-4" onSubmit={submit}>
      <div className="space-y-1.5"><Label htmlFor={`${category}-label`}>Display value *</Label><Input id={`${category}-label`} value={label} onChange={(event) => setLabel(event.target.value)} required /></div>
      <div className="space-y-1.5"><Label htmlFor={`${category}-code`}>Code</Label><Input id={`${category}-code`} value={code} onChange={(event) => setCode(event.target.value)} placeholder="Generated from display value" disabled={Boolean(editing)} />{editing ? <p className="text-xs text-muted-foreground">Codes remain stable so existing project records are not orphaned.</p> : null}</div>
      <div className="space-y-1.5"><Label htmlFor={`${category}-order`}>Sort order</Label><Input id={`${category}-order`} type="number" min="0" value={sortOrder} onChange={(event) => setSortOrder(event.target.value)} /></div>
      <div><Button type="submit" pending={create.isPending || update.isPending}>{editing ? 'Save changes' : 'Add value'}</Button>{create.error || update.error ? <p role="alert" className="mt-2 text-sm text-destructive">Unable to save this value. Use a unique code within the category.</p> : null}</div>
    </form></SheetContent></Sheet>
  </PageContainer>
}
