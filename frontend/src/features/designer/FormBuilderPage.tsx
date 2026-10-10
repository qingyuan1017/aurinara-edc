import { useMemo, useState, type ReactNode } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { isAxiosError } from 'axios'
import {
  DndContext,
  KeyboardSensor,
  PointerSensor,
  closestCenter,
  useDraggable,
  useDroppable,
  useSensor,
  useSensors,
  type DragEndEvent,
} from '@dnd-kit/core'
import {
  SortableContext,
  sortableKeyboardCoordinates,
  useSortable,
  verticalListSortingStrategy,
} from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { ControlType } from '@/api/model'
import type {
  FieldDefinitionCreate,
  FieldDefinitionUpdate,
  FormDependencyCreate,
  FormDependencyResponse,
  ReorderRequest,
} from '@/api/model'
import { api } from '@/lib/api'
import { PermissionGuard } from '@/components/guards/PermissionGuard'
import { usePermission, PERMISSIONS } from '@/lib/permissions'
import { EmptyState, ErrorState, LoadingState, OwnershipBadge, PageContainer, PageHeader } from '@/components/patterns'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { cn } from '@/lib/utils'

interface Field { id: string; label: string; variable_name: string; control_type: string; data_type: string; is_required: boolean; display_order: number; codelist_id?: string | null; form_section_id?: string }
interface Section { id: string; name: string; display_order: number; fields?: Field[] }
interface FormDefinition { id: string; name: string; form_code: string; display_order: number; is_repeating: boolean; sections?: Section[] }
interface Codelist { id: string; name: string; code: string }

// Palette emits the real ControlType WIRE VALUES (not member names). Iterating
// Object.values keeps 'multi-select' (never 'multi_select') on the wire (NIT-5).
const CONTROL_TYPES = Object.values(ControlType)
// Control types whose allowed values come from a codelist (controlled vocabulary).
const CODELIST_CONTROL_TYPES = new Set<string>([
  ControlType.radio,
  ControlType.checkbox,
  ControlType.dropdown,
  ControlType['multi-select'],
  ControlType.coded_term,
])

const PALETTE_PREFIX = 'palette:'
const SECTION_DROP_PREFIX = 'section-drop:'

/**
 * Surface the real backend failure instead of a fixed guess. Reads the shared
 * EDC error envelope ({ error: { message } }), FastAPI's validation shape
 * ({ detail }), then any Error message, and finally the provided fallback.
 */
function describeError(err: unknown, fallback: string): string {
  if (isAxiosError(err)) {
    const data = err.response?.data as { error?: { message?: string }; detail?: unknown } | undefined
    const enveloped = data?.error?.message
    if (typeof enveloped === 'string' && enveloped.trim()) return enveloped
    const detail = data?.detail
    if (typeof detail === 'string' && detail.trim()) return detail
    if (Array.isArray(detail) && detail.length > 0) {
      const first = detail[0] as { msg?: unknown; loc?: unknown }
      const field = Array.isArray(first.loc) ? first.loc[first.loc.length - 1] : undefined
      if (typeof first.msg === 'string') return field ? `${field}: ${first.msg}` : first.msg
    }
    if (err.message) return err.message
  }
  if (err instanceof Error && err.message) return err.message
  return fallback
}

function PaletteItem({ type }: { type: string }) {
  const { attributes, listeners, setNodeRef, transform, isDragging } = useDraggable({ id: `${PALETTE_PREFIX}${type}` })
  return (
    <button
      ref={setNodeRef}
      type="button"
      className={cn('cursor-grab rounded-md border bg-background px-2 py-1 text-left text-xs hover:bg-accent', isDragging && 'opacity-50')}
      style={transform ? { transform: CSS.Translate.toString(transform) } : undefined}
      {...listeners}
      {...attributes}
      aria-roledescription="Draggable field type"
    >
      {type}
    </button>
  )
}

function SortableField({ field, codelists, onSelect, selected }: { field: Field; codelists: Codelist[]; onSelect: () => void; selected: boolean }) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({ id: field.id })
  const linkedCodelist = field.codelist_id ? codelists.find((cl) => cl.id === field.codelist_id) : undefined
  return (
    <div
      ref={setNodeRef}
      style={{ transform: CSS.Translate.toString(transform), transition }}
      className={cn('flex flex-wrap items-center justify-between gap-2 rounded-md bg-muted/50 px-3 py-2 text-sm', selected && 'ring-2 ring-ring', isDragging && 'opacity-50')}
    >
      <button
        type="button"
        className="cursor-grab text-muted-foreground"
        aria-label={`Reorder ${field.label}`}
        {...listeners}
        {...attributes}
        aria-roledescription="Sortable field"
      >
        ⠿
      </button>
      <button type="button" className="flex-1 text-left" onClick={onSelect}>
        {field.label} <span className="text-muted-foreground">({field.variable_name})</span>
      </button>
      <span className="text-muted-foreground">{field.control_type}{linkedCodelist ? ` · ${linkedCodelist.code}` : ''}{field.is_required ? ' · required' : ''}</span>
    </div>
  )
}

function SortableSection({ section, children }: { section: Section; children: ReactNode }) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({ id: section.id })
  const { setNodeRef: setDropRef, isOver } = useDroppable({ id: `${SECTION_DROP_PREFIX}${section.id}` })
  return (
    <div ref={setNodeRef} style={{ transform: CSS.Translate.toString(transform), transition }} className={cn(isDragging && 'opacity-50')}>
      <Card className="shadow-none">
        <CardHeader className="pb-3">
          <div className="flex items-center gap-2">
            <button type="button" className="cursor-grab text-muted-foreground" aria-label={`Reorder section ${section.name}`} {...listeners} {...attributes} aria-roledescription="Sortable section">⠿</button>
            <CardTitle className="text-base">{section.name}</CardTitle>
          </div>
        </CardHeader>
        <CardContent>
          <div ref={setDropRef} className={cn('rounded-md', isOver && 'ring-2 ring-primary ring-offset-2')}>
            {children}
          </div>
        </CardContent>
      </Card>
    </div>
  )
}

function FormDependencyEditor({ formId, forms }: { formId: string; forms: FormDefinition[] }) {
  const queryClient = useQueryClient()
  const canConfigure = usePermission(PERMISSIONS.DESIGNER_FORM_CONFIGURE)
  const [dependsOn, setDependsOn] = useState('')
  const [condition, setCondition] = useState('')
  const [error, setError] = useState('')

  const depsQuery = useQuery({
    queryKey: ['form-dependencies', formId],
    queryFn: async () => (await api.get<FormDependencyResponse[]>(`/designer/forms/${formId}/dependencies`)).data,
  })

  const createDep = useMutation({
    mutationFn: async () => {
      if (!dependsOn) throw new Error('Pick a prerequisite form.')
      const payload: FormDependencyCreate = {
        depends_on_form_definition_id: dependsOn,
        dependency_type: 'prerequisite',
        condition_expression: condition.trim() || null,
      }
      return (await api.post<FormDependencyResponse>(`/designer/forms/${formId}/dependencies`, payload)).data
    },
    onSuccess: () => {
      setError(''); setDependsOn(''); setCondition('')
      queryClient.invalidateQueries({ queryKey: ['form-dependencies', formId] })
    },
    onError: (err) => setError(describeError(err, 'Could not create the dependency.')),
  })

  const nameFor = (id: string) => forms.find((f) => f.id === id)?.form_code ?? id
  const deps = depsQuery.data ?? []

  return (
    <div className="space-y-3 border-t pt-4">
      <h3 className="text-sm font-medium">Depends on</h3>
      {error ? <Alert variant="destructive"><AlertDescription>{error}</AlertDescription></Alert> : null}
      {deps.length ? (
        <ul className="space-y-1 text-sm">
          {deps.map((dep) => (
            <li key={dep.id} className="rounded-md bg-muted/50 px-3 py-1.5">
              {nameFor(dep.depends_on_form_definition_id)}
              {dep.condition_expression ? <span className="text-muted-foreground"> · {dep.condition_expression}</span> : null}
            </li>
          ))}
        </ul>
      ) : <p className="text-xs text-muted-foreground">No prerequisites yet.</p>}
      {canConfigure ? (
        <form className="space-y-2" onSubmit={(event) => { event.preventDefault(); createDep.mutate() }}>
          <select aria-label="Prerequisite form" value={dependsOn} onChange={(event) => setDependsOn(event.target.value)} className="h-9 w-full rounded-md border bg-background px-2 text-sm">
            <option value="">— select prerequisite form —</option>
            {forms.filter((f) => f.id !== formId).map((f) => <option key={f.id} value={f.id}>{f.form_code} · {f.name}</option>)}
          </select>
          <Input aria-label="Condition expression" value={condition} onChange={(event) => setCondition(event.target.value)} placeholder="Optional condition expression" />
          <Button type="submit" variant="outline" pending={createDep.isPending} loadingText="Adding…">Add prerequisite</Button>
        </form>
      ) : null}
    </div>
  )
}

function FieldConfigPanel({ field, studyId, onDone }: { field: Field; studyId: string; onDone: () => void }) {
  const queryClient = useQueryClient()
  const [label, setLabel] = useState(field.label)
  const [variableName, setVariableName] = useState(field.variable_name)
  const [isRequired, setIsRequired] = useState(field.is_required)
  const [codelistId, setCodelistId] = useState(field.codelist_id ?? '')
  const [error, setError] = useState('')

  const codelistsQuery = useQuery({
    queryKey: ['designer-codelists', studyId],
    queryFn: async () => (await api.get<Codelist[]>(`/designer/studies/${studyId}/codelists`)).data,
  })
  const codelists = codelistsQuery.data ?? []
  const needsCodelist = CODELIST_CONTROL_TYPES.has(field.control_type)

  const save = useMutation({
    mutationFn: async () => {
      if (!label.trim()) throw new Error('A field label is required.')
      if (!variableName.trim()) throw new Error('A variable name is required.')
      const payload: FieldDefinitionUpdate = {
        label: label.trim(),
        variable_name: variableName.trim(),
        is_required: isRequired,
        codelist_id: needsCodelist && codelistId ? codelistId : null,
      }
      return (await api.patch(`/designer/fields/${field.id}`, payload)).data
    },
    onSuccess: () => {
      setError('')
      queryClient.invalidateQueries()
      onDone()
    },
    onError: (err) => setError(describeError(err, 'Could not update the field.')),
  })

  return (
    <Card className="shadow-none">
      <CardHeader className="pb-3"><CardTitle className="text-base">Field settings</CardTitle></CardHeader>
      <CardContent>
        <form className="space-y-3" onSubmit={(event) => { event.preventDefault(); save.mutate() }}>
          {error ? <Alert variant="destructive"><AlertDescription>{error}</AlertDescription></Alert> : null}
          <div className="space-y-1.5"><Label htmlFor="field-label">Label</Label><Input id="field-label" value={label} onChange={(event) => setLabel(event.target.value)} /></div>
          <div className="space-y-1.5"><Label htmlFor="field-variable">Variable name</Label><Input id="field-variable" value={variableName} onChange={(event) => setVariableName(event.target.value)} /></div>
          <label className="flex items-center gap-2 text-sm"><Checkbox checked={isRequired} onChange={(event) => setIsRequired(event.target.checked)} />Required field</label>
          {needsCodelist ? (
            <div className="space-y-1.5">
              <Label htmlFor="field-codelist">Codelist</Label>
              <select id="field-codelist" aria-label="Codelist" value={codelistId} onChange={(event) => setCodelistId(event.target.value)} disabled={codelistsQuery.isLoading || !codelists.length} className="h-9 w-full rounded-md border bg-background px-2 text-sm">
                <option value="">— no codelist —</option>
                {codelists.map((cl) => <option key={cl.id} value={cl.id}>{cl.code} · {cl.name}</option>)}
              </select>
            </div>
          ) : null}
          <div className="flex gap-2">
            <Button type="submit" pending={save.isPending} loadingText="Saving…">Save field</Button>
            <Button type="button" variant="outline" onClick={onDone}>Close</Button>
          </div>
        </form>
      </CardContent>
    </Card>
  )
}

function FormBuilderInner({ studyId }: { studyId: string }) {
  const queryClient = useQueryClient()
  const canConfigure = usePermission(PERMISSIONS.DESIGNER_FORM_CONFIGURE)
  const canConfigureFields = usePermission(PERMISSIONS.DESIGNER_FIELD_CONFIGURE)
  const [selectedId, setSelectedId] = useState('')
  const [selectedFieldId, setSelectedFieldId] = useState('')
  const [form, setForm] = useState({ name: '', form_code: '', display_order: 0, is_repeating: false })
  const [sectionName, setSectionName] = useState('')
  const [paletteType, setPaletteType] = useState<Record<string, string>>({})
  const [error, setError] = useState('')

  const sensors = useSensors(
    useSensor(PointerSensor),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  )

  const formsQuery = useQuery({ queryKey: ['form-definitions', studyId], queryFn: async () => (await api.get<FormDefinition[]>(`/designer/studies/${studyId}/forms`)).data })
  const codelistsQuery = useQuery({ queryKey: ['designer-codelists', studyId], queryFn: async () => (await api.get<Codelist[]>(`/designer/studies/${studyId}/codelists`)).data })
  const codelists = codelistsQuery.data ?? []
  const selected = formsQuery.data?.find((item) => item.id === selectedId)
  const detailQuery = useQuery({ queryKey: ['form-definition', selectedId], enabled: !!selectedId, queryFn: async () => (await api.get<FormDefinition>(`/designer/forms/${selectedId}`)).data })
  const activeForm = detailQuery.data ?? selected
  const sections = useMemo(
    () => [...(activeForm?.sections ?? [])].sort((a, b) => a.display_order - b.display_order || a.id.localeCompare(b.id)),
    [activeForm],
  )
  const allFields = useMemo(() => sections.flatMap((s) => s.fields ?? []), [sections])
  const selectedField = allFields.find((f) => f.id === selectedFieldId)

  const invalidateDetail = () => queryClient.invalidateQueries({ queryKey: ['form-definition', selectedId] })

  const createForm = useMutation({
    mutationFn: () => api.post(`/designer/studies/${studyId}/forms`, form),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ['form-definitions', studyId] }); setForm({ name: '', form_code: '', display_order: 0, is_repeating: false }) },
    onError: (err) => setError(describeError(err, 'Could not create form. A draft study version and form.configure permission are required.')),
  })
  const createSection = useMutation({
    mutationFn: () => api.post(`/designer/forms/${selectedId}/sections`, { name: sectionName, display_order: sections.length }),
    onSuccess: () => { invalidateDetail(); setSectionName('') },
    onError: (err) => setError(describeError(err, 'Could not create section.')),
  })
  const addField = useMutation({
    mutationFn: ({ sectionId, controlType }: { sectionId: string; controlType: string }) => {
      const section = sections.find((s) => s.id === sectionId)
      const nextOrder = (section?.fields?.length ?? 0) + 1
      const payload: FieldDefinitionCreate = {
        label: 'New field',
        variable_name: `field_${Date.now()}`,
        control_type: controlType as ControlType,
        data_type: 'string',
        display_order: nextOrder,
        is_required: false,
      }
      return api.post(`/designer/forms/${selectedId}/fields`, payload, { params: { section_id: sectionId } })
    },
    onSuccess: () => { invalidateDetail(); setError('') },
    onError: (err) => setError(describeError(err, 'Could not add field.')),
  })
  const moveField = useMutation({
    mutationFn: ({ fieldId, body }: { fieldId: string; body: FieldDefinitionUpdate }) => api.patch(`/designer/fields/${fieldId}`, body),
    onSuccess: () => invalidateDetail(),
    onError: (err) => setError(describeError(err, 'Could not move field.')),
  })
  const reorderSections = useMutation({
    mutationFn: (orderedIds: string[]) => { const body: ReorderRequest = { ordered_ids: orderedIds }; return api.post(`/designer/forms/${selectedId}/sections/reorder`, body) },
    onSuccess: () => invalidateDetail(),
    onError: (err) => setError(describeError(err, 'Could not reorder sections.')),
  })

  const findSectionOfField = (fieldId: string) => sections.find((s) => (s.fields ?? []).some((f) => f.id === fieldId))

  const handleDragEnd = (event: DragEndEvent) => {
    const { active, over } = event
    if (!over) return
    const activeId = String(active.id)
    const overId = String(over.id)

    // Palette drop onto a section droppable -> create a field.
    if (activeId.startsWith(PALETTE_PREFIX)) {
      const controlType = activeId.slice(PALETTE_PREFIX.length)
      let sectionId = ''
      if (overId.startsWith(SECTION_DROP_PREFIX)) sectionId = overId.slice(SECTION_DROP_PREFIX.length)
      else if (sections.some((s) => s.id === overId)) sectionId = overId
      else { const sec = findSectionOfField(overId); if (sec) sectionId = sec.id }
      if (sectionId) addField.mutate({ sectionId, controlType })
      return
    }

    if (activeId === overId) return

    // Section reorder: both active and over are section ids.
    const activeSectionIndex = sections.findIndex((s) => s.id === activeId)
    const overSectionIndex = sections.findIndex((s) => s.id === overId)
    if (activeSectionIndex !== -1 && overSectionIndex !== -1) {
      const ordered = sections.map((s) => s.id)
      ordered.splice(activeSectionIndex, 1)
      ordered.splice(overSectionIndex, 0, activeId)
      reorderSections.mutate(ordered)
      return
    }

    // Field drag: active is a field.
    const fromSection = findSectionOfField(activeId)
    if (!fromSection) return
    // Determine target section: dropped on a field or a section droppable.
    let targetSection: Section | undefined
    if (overId.startsWith(SECTION_DROP_PREFIX)) targetSection = sections.find((s) => s.id === overId.slice(SECTION_DROP_PREFIX.length))
    else if (sections.some((s) => s.id === overId)) targetSection = sections.find((s) => s.id === overId)
    else targetSection = findSectionOfField(overId)
    if (!targetSection) return

    if (targetSection.id === fromSection.id) {
      // Reorder within the section: PATCH new display_order.
      const fields = [...(fromSection.fields ?? [])].sort((a, b) => a.display_order - b.display_order)
      const fromIdx = fields.findIndex((f) => f.id === activeId)
      const overIdx = fields.findIndex((f) => f.id === overId)
      if (fromIdx === -1 || overIdx === -1) return
      moveField.mutate({ fieldId: activeId, body: { display_order: overIdx + 1 } })
    } else {
      // Move across sections: PATCH new form_section_id + end display_order.
      const nextOrder = (targetSection.fields?.length ?? 0) + 1
      moveField.mutate({ fieldId: activeId, body: { form_section_id: targetSection.id, display_order: nextOrder } })
    }
  }

  return (
    <PageContainer wide>
      <PageHeader title="Form Builder" description="Drag field types from the palette into sections, and reorder sections and fields. Configure eCRF definitions on the current draft study version." ownership={<OwnershipBadge owner="Designer" />} />
      {error ? <Alert variant="destructive" className="mb-6"><AlertDescription>{error}</AlertDescription></Alert> : null}

      <div className="grid gap-6 lg:grid-cols-[18rem_1fr]">
        <Card>
          <CardHeader className="pb-3"><div className="flex items-center justify-between"><CardTitle className="text-base">Forms</CardTitle><span className="text-xs text-muted-foreground">{formsQuery.data?.length ?? 0}</span></div></CardHeader>
          <CardContent className="space-y-3">
            {formsQuery.isLoading ? <LoadingState label="form definitions" className="border-0 p-0 shadow-none" />
              : formsQuery.error ? <ErrorState message="Form definitions could not be loaded." onRetry={() => void formsQuery.refetch()} />
              : formsQuery.data?.length ? <div className="space-y-1">{formsQuery.data.map((item) => <Button type="button" key={item.id} variant={item.id === selectedId ? 'secondary' : 'ghost'} className="h-auto w-full justify-start px-3 py-2 text-left" onClick={() => { setSelectedId(item.id); setSelectedFieldId('') }}><span><b>{item.form_code}</b> — {item.name}</span></Button>)}</div>
              : <EmptyState title="No forms yet" description="Create a form definition for this study version." />}
            {canConfigure ? (
              <form className="space-y-3 border-t pt-4" onSubmit={(event) => { event.preventDefault(); createForm.mutate() }}>
                <h3 className="text-sm font-medium">Add form</h3>
                <div className="space-y-1.5"><Label htmlFor="form-name">Form name</Label><Input id="form-name" required value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} /></div>
                <div className="space-y-1.5"><Label htmlFor="form-code">Form code</Label><Input id="form-code" required value={form.form_code} onChange={(event) => setForm({ ...form, form_code: event.target.value })} /></div>
                <label className="flex items-center gap-2 text-sm"><Checkbox checked={form.is_repeating} onChange={(event) => setForm({ ...form, is_repeating: event.target.checked })} />Repeating form</label>
                <Button type="submit" className="w-full" pending={createForm.isPending} loadingText="Creating…">Create form</Button>
              </form>
            ) : null}
          </CardContent>
        </Card>

        <div className="space-y-6">
          <Card>
            {!activeForm ? (
              <CardContent className="pt-6"><EmptyState title="Select a form to continue" description="Configure sections and fields for the selected form definition." /></CardContent>
            ) : (
              <>
                <CardHeader><CardTitle>{activeForm.name}</CardTitle><CardDescription>{activeForm.form_code} · {activeForm.is_repeating ? 'Repeating' : 'Non-repeating'}</CardDescription></CardHeader>
                <CardContent className="space-y-5">
                  {canConfigure ? (
                    <>
                      <form className="flex flex-col gap-2 sm:flex-row" onSubmit={(event) => { event.preventDefault(); createSection.mutate() }}>
                        <Input required placeholder="New section name" aria-label="New section name" value={sectionName} onChange={(event) => setSectionName(event.target.value)} />
                        <Button type="submit" variant="outline" pending={createSection.isPending} loadingText="Adding…">Add section</Button>
                      </form>
                      <div>
                        <h3 className="mb-2 text-sm font-medium">Field palette</h3>
                        <div className="flex flex-wrap gap-1.5">{CONTROL_TYPES.map((type) => <PaletteItem key={type} type={type} />)}</div>
                        <p className="mt-1 text-xs text-muted-foreground">Drag a type onto a section, or use the keyboard "Add field" control per section.</p>
                      </div>
                    </>
                  ) : null}

                  {detailQuery.isLoading ? <LoadingState label="form definition" />
                    : detailQuery.error ? <ErrorState message="Form definition could not be loaded." onRetry={() => void detailQuery.refetch()} />
                    : (
                      <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={handleDragEnd}>
                        <SortableContext items={sections.map((s) => s.id)} strategy={verticalListSortingStrategy}>
                          <div className="space-y-4">
                            {sections.map((section) => {
                              const fields = [...(section.fields ?? [])].sort((a, b) => a.display_order - b.display_order)
                              return (
                                <SortableSection key={section.id} section={section}>
                                  <SortableContext items={fields.map((f) => f.id)} strategy={verticalListSortingStrategy}>
                                    <div className="space-y-1">
                                      {fields.length ? fields.map((field) => (
                                        <SortableField
                                          key={field.id}
                                          field={field}
                                          codelists={codelists}
                                          selected={field.id === selectedFieldId}
                                          onSelect={() => canConfigureFields && setSelectedFieldId(field.id)}
                                        />
                                      )) : <p className="px-3 py-2 text-xs text-muted-foreground">No fields yet. Drag a type here or use Add field.</p>}
                                    </div>
                                  </SortableContext>
                                  {canConfigureFields ? (
                                    <div className="mt-3 flex items-center gap-2">
                                      <select
                                        aria-label={`Add field type to ${section.name}`}
                                        value={paletteType[section.id] ?? ControlType.text}
                                        onChange={(event) => setPaletteType((prev) => ({ ...prev, [section.id]: event.target.value }))}
                                        className="h-9 rounded-md border bg-background px-2 text-sm"
                                      >
                                        {CONTROL_TYPES.map((type) => <option key={type} value={type}>{type}</option>)}
                                      </select>
                                      <Button type="button" variant="outline" size="sm" onClick={() => addField.mutate({ sectionId: section.id, controlType: paletteType[section.id] ?? ControlType.text })}>Add field</Button>
                                    </div>
                                  ) : null}
                                </SortableSection>
                              )
                            })}
                            {!sections.length ? <EmptyState title="No sections yet" description="Add a section to start building the form." /> : null}
                          </div>
                        </SortableContext>
                      </DndContext>
                    )}

                  <FormDependencyEditor formId={activeForm.id} forms={formsQuery.data ?? []} />
                </CardContent>
              </>
            )}
          </Card>

          {selectedField ? (
            <FieldConfigPanel field={selectedField} studyId={studyId} onDone={() => setSelectedFieldId('')} />
          ) : null}
        </div>
      </div>
    </PageContainer>
  )
}

export function FormBuilderPage({ studyId }: { studyId: string }) {
  return (
    <PermissionGuard permission={PERMISSIONS.DESIGNER_FORM_READ} studyId={studyId}>
      <FormBuilderInner studyId={studyId} />
    </PermissionGuard>
  )
}
