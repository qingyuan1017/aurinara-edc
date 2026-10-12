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
  FormDefinitionCreate,
  FormDefinitionUpdate,
  FormDependencyCreate,
  FormDependencyResponse,
  ReorderRequest,
  TextAlign,
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
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { Textarea } from '@/components/ui/textarea'
import { cn } from '@/lib/utils'
import { DesignerJsonImport } from './DesignerJsonImport'
import { DraftGate } from './shared'

interface Field { id: string; label: string; question?: string | null; caption?: string | null; text_align: string; variable_name: string; record_id?: string | null; crf_id?: string | null; odm_id?: string | null; control_type: string; data_type: string; is_required: boolean; display_order: number; codelist_id?: string | null; form_section_id?: string; help_text?: string | null; max_length?: number | null; unit?: string | null; min_value?: number | string | null; max_value?: number | string | null; decimal_precision?: number | null }
interface Section { id: string; name: string; label: string; display_order: number; is_label_only: boolean; output_to_dataset: boolean; help_text?: string | null; access_type: string; fields?: Field[] }
interface FormDefinition { id: string; name: string; form_code: string; display_order: number; is_repeating: boolean; form_type: string; access_type: string; domain?: string | null; label?: string | null; grid_rows?: number | null; grid_columns?: number | null; header_name?: string | null; detail_name?: string | null; detail_type?: string | null; show_variable_name?: boolean; show_crf_id?: boolean; show_odm_id?: boolean; sections?: Section[] }
interface Codelist { id: string; name: string; code: string; items?: Array<{ code: string; label: string }> }

interface FormDraft {
  name: string
  form_code: string
  display_order: number
  is_repeating: boolean
  form_type: string
  access_type: string
  domain: string
  label: string
  grid_rows: string
  grid_columns: string
  header_name: string
  detail_name: string
  detail_type: string
  show_variable_name: boolean
  show_crf_id: boolean
  show_odm_id: boolean
}

const emptyForm = (): FormDraft => ({
  name: '', form_code: '', display_order: 0, is_repeating: false,
  form_type: 'simple', access_type: 'open_access', domain: '', label: '',
  grid_rows: '', grid_columns: '', header_name: '', detail_name: '', detail_type: 'log',
  show_variable_name: false, show_crf_id: false, show_odm_id: false,
})

const draftFromForm = (form: FormDefinition): FormDraft => ({
  name: form.name,
  form_code: form.form_code,
  display_order: form.display_order,
  is_repeating: form.is_repeating,
  form_type: form.form_type ?? 'simple',
  access_type: form.access_type ?? 'open_access',
  domain: form.domain ?? '',
  label: form.label ?? '',
  grid_rows: form.grid_rows?.toString() ?? '',
  grid_columns: form.grid_columns?.toString() ?? '',
  header_name: form.header_name ?? '',
  detail_name: form.detail_name ?? '',
  detail_type: form.detail_type ?? 'log',
  show_variable_name: form.show_variable_name ?? false,
  show_crf_id: form.show_crf_id ?? false,
  show_odm_id: form.show_odm_id ?? false,
})

const formPayload = (form: FormDraft): FormDefinitionCreate => ({
  name: form.name.trim(),
  form_code: form.form_code.trim(),
  display_order: form.display_order,
  is_repeating: form.is_repeating,
  form_type: form.form_type as FormDefinitionCreate['form_type'],
  access_type: form.access_type as FormDefinitionCreate['access_type'],
  domain: form.domain.trim() || null,
  label: form.label.trim() || null,
  grid_rows: form.form_type === 'grid' && form.grid_rows ? Number(form.grid_rows) : null,
  grid_columns: form.form_type === 'grid' && form.grid_columns ? Number(form.grid_columns) : null,
  header_name: form.form_type === 'header_details' ? form.header_name.trim() || null : null,
  detail_name: form.form_type === 'header_details' ? form.detail_name.trim() || null : null,
  detail_type: form.form_type === 'header_details' ? form.detail_type as FormDefinitionCreate['detail_type'] : null,
  show_variable_name: form.show_variable_name,
  show_crf_id: form.show_crf_id,
  show_odm_id: form.show_odm_id,
})

const FORM_TYPES = ['simple', 'log', 'grid', 'header_details'] as const
const ACCESS_TYPES = ['open_access', 'restricted_edit', 'general_blind'] as const
const DATA_TYPES = ['string', 'integer', 'float', 'date', 'time', 'boolean'] as const
const TEXT_ALIGNS = ['left', 'center', 'right'] as const
const DETAIL_TYPES = ['log', 'grid'] as const

// Palette emits the real ControlType WIRE VALUES (not member names). Iterating
// Object.values keeps 'multi-select' (never 'multi_select') on the wire (NIT-5).
const CONTROL_TYPES = Object.values(ControlType)
// Control types whose allowed values come from a codelist (controlled vocabulary).
const CODELIST_CONTROL_TYPES = new Set<string>([
  ControlType.radio,
  ControlType.checkbox,
  ControlType.dropdown,
  ControlType.listbox,
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

function FieldWidgetPreview({ field, codelist }: { field: Field; codelist?: Codelist }) {
  const options = codelist?.items ?? []
  const optionElements = options.length ? options.slice(0, 4).map((item) => <option key={item.code}>{item.label}</option>) : <option>Example option</option>
  const common = { disabled: true, 'aria-label': `${field.label} preview` }
  switch (field.control_type) {
    case 'label': return <p className="rounded-md bg-muted px-3 py-2 text-sm font-medium">{field.caption || field.question || field.label}</p>
    case 'textarea': return <Textarea {...common} rows={2} placeholder="Long text response" />
    case 'integer': return <Input {...common} type="number" step={1} placeholder="0" />
    case 'decimal':
    case 'float': return <Input {...common} type="number" step="any" placeholder="0.0" />
    case 'slider': return <input {...common} type="range" min={field.min_value ?? 0} max={field.max_value ?? 100} className="w-full accent-primary" />
    case 'date': return <Input {...common} type="date" />
    case 'time': return <Input {...common} type="time" />
    case 'datetime': return <Input {...common} type="datetime-local" />
    case 'dropdown':
    case 'coded_term': return <select {...common} className="h-9 w-full rounded-md border bg-background px-2 text-sm"><option>— Select —</option>{optionElements}</select>
    case 'listbox': return <select {...common} size={3} className="w-full rounded-md border bg-background px-2 py-1 text-sm">{optionElements}</select>
    case 'multi-select': return <select {...common} multiple size={3} className="w-full rounded-md border bg-background px-2 py-1 text-sm">{optionElements}</select>
    case 'radio': return <div className="flex flex-wrap gap-3 text-xs">{(options.length ? options.slice(0, 3) : [{ code: '1', label: 'Option 1' }, { code: '2', label: 'Option 2' }]).map((item) => <label key={item.code} className="flex items-center gap-1"><input type="radio" disabled />{item.label}</label>)}</div>
    case 'checkbox': return <div className="flex flex-wrap gap-3 text-xs">{(options.length ? options.slice(0, 3) : [{ code: '1', label: 'Selected' }]).map((item) => <label key={item.code} className="flex items-center gap-1"><Checkbox disabled />{item.label}</label>)}</div>
    case 'boolean': return <label className="flex items-center gap-2 text-xs"><Checkbox disabled />Yes</label>
    case 'body_image': return <div className="flex items-center gap-3 rounded-md border p-2"><svg viewBox="0 0 100 180" role="img" aria-label="Body image preview" className="h-24 w-14 fill-muted stroke-muted-foreground"><circle cx="50" cy="18" r="13" /><path d="M35 35h30l8 55-13 5-2 70H45l-3-70-14-5z" /><path d="M35 42 15 90l10 5 20-42M65 42l20 48-10 5-20-42" fill="none" strokeWidth="8" /></svg><span className="text-xs text-muted-foreground">Interactive body-location selector</span></div>
    case 'unit': return <div className="flex"><Input {...common} className="rounded-r-none" placeholder="Value" /><span className="flex items-center rounded-r-md border border-l-0 bg-muted px-3 text-xs">{field.unit || 'unit'}</span></div>
    case 'file_upload': return <Input {...common} type="file" />
    case 'calculated': return <Input {...common} value="Calculated value" readOnly />
    case 'repeating_table': return <div className="overflow-hidden rounded-md border text-xs"><div className="grid grid-cols-[1fr_auto] bg-muted px-2 py-1 font-medium"><span>Row</span><span>Action</span></div><div className="grid grid-cols-[1fr_auto] items-center border-t px-2 py-1"><span className="text-muted-foreground">Repeating value</span><span>Remove</span></div></div>
    case 'text':
    default: return <Input {...common} type="text" placeholder="Text response" />
  }
}

function SortableField({ field, codelists, onSelect, selected, display, canReorder }: { field: Field; codelists: Codelist[]; onSelect: () => void; selected: boolean; display: Pick<FormDefinition, 'show_variable_name' | 'show_crf_id' | 'show_odm_id'>; canReorder: boolean }) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({ id: field.id, disabled: !canReorder })
  const linkedCodelist = field.codelist_id ? codelists.find((cl) => cl.id === field.codelist_id) : undefined
  return (
    <div
      ref={setNodeRef}
      style={{ transform: CSS.Translate.toString(transform), transition }}
      className={cn('flex flex-wrap items-center justify-between gap-2 rounded-md bg-muted/50 px-3 py-2 text-sm', selected && 'ring-2 ring-ring', isDragging && 'opacity-50')}
    >
      {canReorder ? (
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
      ) : null}
      <div className="min-w-0 flex-1 space-y-2">
        <button type="button" className="block w-full text-left" onClick={onSelect}>
          <span>{field.label}</span>
          <span className="mt-0.5 flex flex-wrap gap-x-3 text-xs text-muted-foreground">
            {display.show_variable_name ? <span>Variable: {field.variable_name}</span> : null}
            {display.show_crf_id ? <span>CRF ID: {field.crf_id || '—'}</span> : null}
            {display.show_odm_id ? <span>ODM ID: {field.odm_id || '—'}</span> : null}
          </span>
        </button>
        <div className="pointer-events-none"><FieldWidgetPreview field={field} codelist={linkedCodelist} /></div>
      </div>
      <span className="text-muted-foreground">{field.control_type}{linkedCodelist ? ` · ${linkedCodelist.code}` : ''}{field.is_required ? ' · required' : ''}</span>
    </div>
  )
}

function FormSettingsPanel({ draft, setDraft, mode, pending, error, onSubmit, readOnly }: { draft: FormDraft; setDraft: (value: FormDraft) => void; mode: 'create' | 'edit'; pending: boolean; error: string; onSubmit: () => void; readOnly: boolean }) {
  return (
    <form className="space-y-4" onSubmit={(event) => { event.preventDefault(); if (!readOnly) onSubmit() }}>
      {error ? <Alert variant="destructive"><AlertDescription>{error}</AlertDescription></Alert> : null}
      <fieldset disabled={readOnly} className="space-y-4">
      <div className="space-y-1.5"><Label htmlFor="form-name">Form name</Label><Input id="form-name" required value={draft.name} onChange={(event) => setDraft({ ...draft, name: event.target.value })} /></div>
      <div className="space-y-1.5"><Label htmlFor="form-code">Form code</Label><Input id="form-code" required value={draft.form_code} onChange={(event) => setDraft({ ...draft, form_code: event.target.value })} /></div>
      <div className="grid gap-3 sm:grid-cols-2">
        <div className="space-y-1.5"><Label htmlFor="form-type">Form type</Label><select id="form-type" value={draft.form_type} onChange={(event) => setDraft({ ...draft, form_type: event.target.value })} className="h-9 w-full rounded-md border bg-background px-2 text-sm">{FORM_TYPES.map((value) => <option key={value} value={value}>{value.replace('_', ' ')}</option>)}</select></div>
        <div className="space-y-1.5"><Label htmlFor="form-access">Access type</Label><select id="form-access" value={draft.access_type} onChange={(event) => setDraft({ ...draft, access_type: event.target.value })} className="h-9 w-full rounded-md border bg-background px-2 text-sm">{ACCESS_TYPES.map((value) => <option key={value} value={value}>{value.replace('_', ' ')}</option>)}</select></div>
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        <div className="space-y-1.5"><Label htmlFor="form-domain">Domain</Label><Input id="form-domain" value={draft.domain} onChange={(event) => setDraft({ ...draft, domain: event.target.value })} placeholder="AE" /></div>
        <div className="space-y-1.5"><Label htmlFor="form-label">Label</Label><Input id="form-label" value={draft.label} onChange={(event) => setDraft({ ...draft, label: event.target.value })} /></div>
      </div>
      {draft.form_type === 'grid' ? (
        <div className="rounded-md border p-3">
          <p className="mb-3 text-sm font-medium">Grid layout</p>
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="space-y-1.5"><Label htmlFor="grid-rows">Rows</Label><Input id="grid-rows" type="number" min={1} value={draft.grid_rows} onChange={(event) => setDraft({ ...draft, grid_rows: event.target.value })} /></div>
            <div className="space-y-1.5"><Label htmlFor="grid-columns">Columns</Label><Input id="grid-columns" type="number" min={1} value={draft.grid_columns} onChange={(event) => setDraft({ ...draft, grid_columns: event.target.value })} /></div>
          </div>
        </div>
      ) : null}
      {draft.form_type === 'header_details' ? (
        <div className="space-y-3 rounded-md border p-3">
          <p className="text-sm font-medium">Header-details layout</p>
          <div className="space-y-1.5"><Label htmlFor="header-name">Header name</Label><Input id="header-name" value={draft.header_name} onChange={(event) => setDraft({ ...draft, header_name: event.target.value })} /></div>
          <div className="space-y-1.5"><Label htmlFor="detail-name">Detail name</Label><Input id="detail-name" value={draft.detail_name} onChange={(event) => setDraft({ ...draft, detail_name: event.target.value })} /></div>
          <div className="space-y-1.5"><Label htmlFor="detail-type">Detail type</Label><select id="detail-type" value={draft.detail_type} onChange={(event) => setDraft({ ...draft, detail_type: event.target.value })} className="h-9 w-full rounded-md border bg-background px-2 text-sm">{DETAIL_TYPES.map((value) => <option key={value} value={value}>{value}</option>)}</select></div>
        </div>
      ) : null}
      <div className="space-y-2 rounded-md border p-3">
        <p className="text-sm font-medium">Field identifiers shown in the builder</p>
        <label className="flex items-center gap-2 text-sm"><Checkbox checked={draft.show_variable_name} onChange={(event) => setDraft({ ...draft, show_variable_name: event.target.checked })} />Variable name</label>
        <label className="flex items-center gap-2 text-sm"><Checkbox checked={draft.show_crf_id} onChange={(event) => setDraft({ ...draft, show_crf_id: event.target.checked })} />CRF ID</label>
        <label className="flex items-center gap-2 text-sm"><Checkbox checked={draft.show_odm_id} onChange={(event) => setDraft({ ...draft, show_odm_id: event.target.checked })} />ODM ID</label>
      </div>
      <label className="flex items-center gap-2 text-sm"><Checkbox checked={draft.is_repeating} onChange={(event) => setDraft({ ...draft, is_repeating: event.target.checked })} />Repeating form</label>
      </fieldset>
      {!readOnly ? <Button type="submit" className="w-full" pending={pending} loadingText="Saving…">{mode === 'create' ? 'Create form' : 'Save form settings'}</Button> : null}
    </form>
  )
}

function SortableSection({ section, children, canReorder }: { section: Section; children: ReactNode; canReorder: boolean }) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({ id: section.id, disabled: !canReorder })
  const { setNodeRef: setDropRef, isOver } = useDroppable({ id: `${SECTION_DROP_PREFIX}${section.id}`, disabled: !canReorder })
  return (
    <div ref={setNodeRef} style={{ transform: CSS.Translate.toString(transform), transition }} className={cn(isDragging && 'opacity-50')}>
      <Card className="shadow-none">
        <CardHeader className="pb-3">
          <div className="flex items-center gap-2">
            {canReorder ? <button type="button" className="cursor-grab text-muted-foreground" aria-label={`Reorder section ${section.name}`} {...listeners} {...attributes} aria-roledescription="Sortable section">⠿</button> : null}
            <div>
              <CardTitle className="text-base">{section.label || section.name}</CardTitle>
              <CardDescription>{(section.access_type ?? 'open_access').replace('_', ' ')} · {section.is_label_only ? 'label only' : section.output_to_dataset !== false ? 'dataset output' : 'not output'}{section.help_text ? ` · ${section.help_text}` : ''}</CardDescription>
            </div>
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

function FormDependencyEditor({ formId, forms, canConfigure }: { formId: string; forms: FormDefinition[]; canConfigure: boolean }) {
  const queryClient = useQueryClient()
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

function FieldConfigPanel({ field, studyId, versionId, readOnly, onDone }: { field: Field; studyId: string; versionId: string; readOnly: boolean; onDone: () => void }) {
  const queryClient = useQueryClient()
  const [label, setLabel] = useState(field.label)
  const [variableName, setVariableName] = useState(field.variable_name)
  const [question, setQuestion] = useState(field.question ?? '')
  const [caption, setCaption] = useState(field.caption ?? '')
  const [textAlign, setTextAlign] = useState(field.text_align ?? 'left')
  const [helpText, setHelpText] = useState(field.help_text ?? '')
  const [dataType, setDataType] = useState(field.data_type)
  const [controlType, setControlType] = useState(field.control_type)
  const [maxLength, setMaxLength] = useState(field.max_length?.toString() ?? '')
  const [recordId, setRecordId] = useState(field.record_id ?? '')
  const [crfId, setCrfId] = useState(field.crf_id ?? '')
  const [odmId, setOdmId] = useState(field.odm_id ?? '')
  const [unit, setUnit] = useState(field.unit ?? '')
  const [isRequired, setIsRequired] = useState(field.is_required)
  const [codelistId, setCodelistId] = useState(field.codelist_id ?? '')
  const [error, setError] = useState('')

  const codelistsQuery = useQuery({
    queryKey: ['designer-codelists', studyId, versionId],
    queryFn: async () => (await api.get<Codelist[]>(`/designer/studies/${studyId}/codelists`, { params: { study_version_id: versionId } })).data,
  })
  const codelists = codelistsQuery.data ?? []
  const needsCodelist = CODELIST_CONTROL_TYPES.has(controlType)

  const save = useMutation({
    mutationFn: async () => {
      if (!label.trim()) throw new Error('A field label is required.')
      if (!variableName.trim()) throw new Error('A variable name is required.')
      const payload: FieldDefinitionUpdate = {
        label: label.trim(),
        variable_name: variableName.trim(),
        question: question.trim() || null,
        caption: caption.trim() || null,
        text_align: textAlign as TextAlign,
        help_text: helpText.trim() || null,
        data_type: dataType,
        control_type: controlType as ControlType,
        max_length: maxLength.trim() ? Number(maxLength) : null,
        record_id: recordId.trim() || null,
        crf_id: crfId.trim() || null,
        odm_id: odmId.trim() || null,
        unit: unit.trim() || null,
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
        <form className="space-y-3" onSubmit={(event) => { event.preventDefault(); if (!readOnly) save.mutate() }}>
          {error ? <Alert variant="destructive"><AlertDescription>{error}</AlertDescription></Alert> : null}
          <fieldset disabled={readOnly} className="space-y-3">
          <div className="space-y-1.5"><Label htmlFor="field-label">Label</Label><Input id="field-label" value={label} onChange={(event) => setLabel(event.target.value)} /></div>
          <div className="space-y-1.5"><Label htmlFor="field-question">Question</Label><Input id="field-question" value={question} onChange={(event) => setQuestion(event.target.value)} /></div>
          <div className="space-y-1.5"><Label htmlFor="field-caption">Caption</Label><Input id="field-caption" value={caption} onChange={(event) => setCaption(event.target.value)} /></div>
          <div className="space-y-1.5"><Label htmlFor="field-variable">Variable name</Label><Input id="field-variable" value={variableName} onChange={(event) => setVariableName(event.target.value)} /></div>
          <div className="space-y-1.5"><Label htmlFor="field-record-id">Record ID</Label><Input id="field-record-id" value={recordId} onChange={(event) => setRecordId(event.target.value)} /></div>
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="space-y-1.5"><Label htmlFor="field-crf-id">CRF ID</Label><Input id="field-crf-id" value={crfId} onChange={(event) => setCrfId(event.target.value)} /></div>
            <div className="space-y-1.5"><Label htmlFor="field-odm-id">ODM ID</Label><Input id="field-odm-id" value={odmId} onChange={(event) => setOdmId(event.target.value)} /></div>
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="space-y-1.5"><Label htmlFor="field-control-type">Field type</Label><select id="field-control-type" value={controlType} onChange={(event) => setControlType(event.target.value)} className="h-9 w-full rounded-md border bg-background px-2 text-sm">{CONTROL_TYPES.map((value) => <option key={value} value={value}>{value.replaceAll('_', ' ')}</option>)}</select></div>
            <div className="space-y-1.5"><Label htmlFor="field-data-type">Data type</Label><select id="field-data-type" value={dataType} onChange={(event) => setDataType(event.target.value)} className="h-9 w-full rounded-md border bg-background px-2 text-sm">{DATA_TYPES.map((value) => <option key={value} value={value}>{value}</option>)}</select></div>
            <div className="space-y-1.5"><Label htmlFor="field-align">Text align</Label><select id="field-align" value={textAlign} onChange={(event) => setTextAlign(event.target.value)} className="h-9 w-full rounded-md border bg-background px-2 text-sm">{TEXT_ALIGNS.map((value) => <option key={value} value={value}>{value}</option>)}</select></div>
            <div className="space-y-1.5"><Label htmlFor="field-length">Length</Label><Input id="field-length" type="number" min={0} value={maxLength} onChange={(event) => setMaxLength(event.target.value)} /></div>
            <div className="space-y-1.5"><Label htmlFor="field-unit">Unit</Label><Input id="field-unit" value={unit} onChange={(event) => setUnit(event.target.value)} /></div>
          </div>
          <div className="space-y-1.5"><Label htmlFor="field-help">Help text</Label><Input id="field-help" value={helpText} onChange={(event) => setHelpText(event.target.value)} /></div>
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
          </fieldset>
          <div className="flex gap-2">
            {!readOnly ? <Button type="submit" pending={save.isPending} loadingText="Saving…">Save field</Button> : null}
            <Button type="button" variant="outline" onClick={onDone}>Close</Button>
          </div>
        </form>
  )
}

function FormBuilderInner({ studyId, versionId, readOnly }: { studyId: string; versionId: string; readOnly: boolean }) {
  const queryClient = useQueryClient()
  const canConfigure = usePermission(PERMISSIONS.DESIGNER_FORM_CONFIGURE) && !readOnly
  const canConfigureFields = usePermission(PERMISSIONS.DESIGNER_FIELD_CONFIGURE) && !readOnly
  const [selectedId, setSelectedId] = useState('')
  const [selectedFieldId, setSelectedFieldId] = useState('')
  const [form, setForm] = useState<FormDraft>(emptyForm)
  const [formDrawerMode, setFormDrawerMode] = useState<'create' | 'edit' | null>(null)
  const [formError, setFormError] = useState('')
  const [sectionName, setSectionName] = useState('')
  const [sectionLabelOnly, setSectionLabelOnly] = useState(false)
  const [sectionOutput, setSectionOutput] = useState(true)
  const [sectionHelp, setSectionHelp] = useState('')
  const [sectionAccess, setSectionAccess] = useState('open_access')
  const [paletteType, setPaletteType] = useState<Record<string, string>>({})
  const [error, setError] = useState('')

  const sensors = useSensors(
    useSensor(PointerSensor),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  )

  const formsQuery = useQuery({ queryKey: ['form-definitions', studyId, versionId], queryFn: async () => (await api.get<FormDefinition[]>(`/designer/studies/${studyId}/forms`, { params: { study_version_id: versionId } })).data })
  const codelistsQuery = useQuery({ queryKey: ['designer-codelists', studyId, versionId], queryFn: async () => (await api.get<Codelist[]>(`/designer/studies/${studyId}/codelists`, { params: { study_version_id: versionId } })).data })
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
    mutationFn: () => api.post<FormDefinition>(`/designer/studies/${studyId}/forms`, formPayload(form), { params: { study_version_id: versionId } }),
    onSuccess: ({ data }) => {
      queryClient.invalidateQueries({ queryKey: ['form-definitions', studyId] })
      setSelectedId(data.id)
      setForm(emptyForm())
      setFormDrawerMode(null)
      setFormError('')
    },
    onError: (err) => setFormError(describeError(err, 'Could not create form. A draft study version and form.configure permission are required.')),
  })
  const updateForm = useMutation({
    mutationFn: () => api.patch<FormDefinition>(`/designer/forms/${selectedId}`, formPayload(form) as FormDefinitionUpdate),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['form-definitions', studyId] })
      invalidateDetail()
      setFormDrawerMode(null)
      setFormError('')
    },
    onError: (err) => setFormError(describeError(err, 'Could not update the form settings.')),
  })
  const createSection = useMutation({
    mutationFn: () => api.post(`/designer/forms/${selectedId}/sections`, { name: sectionName, label: sectionName, display_order: sections.length, is_label_only: sectionLabelOnly, output_to_dataset: sectionOutput, help_text: sectionHelp.trim() || null, access_type: sectionAccess }),
    onSuccess: () => { invalidateDetail(); setSectionName(''); setSectionLabelOnly(false); setSectionOutput(true); setSectionHelp(''); setSectionAccess('open_access') },
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
        data_type: controlType === 'integer' ? 'integer' : controlType === 'float' || controlType === 'slider' ? 'float' : controlType === 'date' ? 'date' : controlType === 'time' ? 'time' : controlType === 'checkbox' ? 'boolean' : 'string',
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
    if (readOnly) return
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
      <PageHeader title="Form Builder" description={readOnly ? "Review forms, sections, fields, and settings from this published design version." : "Drag field types from the palette into sections, and reorder sections and fields. Configure eCRF definitions on the current draft study version."} ownership={<OwnershipBadge owner="Designer" />} actions={canConfigure ? <DesignerJsonImport studyId={studyId} /> : undefined} />
      {error ? <Alert variant="destructive" className="mb-6"><AlertDescription>{error}</AlertDescription></Alert> : null}

      <div className="grid gap-6 lg:grid-cols-[18rem_1fr]">
        <Card>
          <CardHeader className="pb-3"><div className="flex items-center justify-between"><CardTitle className="text-base">Forms</CardTitle><span className="text-xs text-muted-foreground">{formsQuery.data?.length ?? 0}</span></div></CardHeader>
          <CardContent className="space-y-3">
            {formsQuery.isLoading ? <LoadingState label="form definitions" className="border-0 p-0 shadow-none" />
              : formsQuery.error ? <ErrorState message="Form definitions could not be loaded." onRetry={() => void formsQuery.refetch()} />
              : formsQuery.data?.length ? <div className="space-y-1">{formsQuery.data.map((item) => <Button type="button" key={item.id} variant={item.id === selectedId ? 'secondary' : 'ghost'} className="h-auto w-full justify-start px-3 py-2 text-left" onClick={() => { setSelectedId(item.id); setSelectedFieldId('') }}><span><b>{item.form_code}</b> — {item.name}</span></Button>)}</div>
              : <EmptyState title="No forms yet" description="Create a form definition for this study version." />}
            {canConfigure ? <Button type="button" className="w-full" onClick={() => { setForm(emptyForm()); setFormError(''); setFormDrawerMode('create') }}>Add form</Button> : null}
          </CardContent>
        </Card>

        <div className="space-y-6">
          <Card>
            {!activeForm ? (
              <CardContent className="pt-6"><EmptyState title="Select a form to continue" description="Configure sections and fields for the selected form definition." /></CardContent>
            ) : (
              <>
                <CardHeader>
                  <div className="flex items-start justify-between gap-3">
                    <div><CardTitle>{activeForm.name}</CardTitle><CardDescription>{activeForm.form_code} · {(activeForm.form_type ?? 'simple').replace('_', ' ')} · {(activeForm.access_type ?? 'open_access').replace('_', ' ')}{activeForm.domain ? ` · ${activeForm.domain}` : ''} · {activeForm.is_repeating ? 'Repeating' : 'Non-repeating'}</CardDescription></div>
                    {(canConfigure || readOnly) ? <Button type="button" variant="outline" size="sm" onClick={() => { setForm(draftFromForm(activeForm)); setFormError(''); setFormDrawerMode('edit') }}>{readOnly ? 'View form settings' : 'Form settings'}</Button> : null}
                  </div>
                </CardHeader>
                <CardContent className="space-y-5">
                  {canConfigure ? (
                    <>
                      <form className="grid gap-2 rounded-md border p-3 sm:grid-cols-2" onSubmit={(event) => { event.preventDefault(); createSection.mutate() }}>
                        <Input required placeholder="New section label" aria-label="New section name" value={sectionName} onChange={(event) => setSectionName(event.target.value)} />
                        <select aria-label="Section access type" value={sectionAccess} onChange={(event) => setSectionAccess(event.target.value)} className="h-9 rounded-md border bg-background px-2 text-sm">{ACCESS_TYPES.map((value) => <option key={value} value={value}>{value.replace('_', ' ')}</option>)}</select>
                        <Input placeholder="Section help text" aria-label="Section help text" value={sectionHelp} onChange={(event) => setSectionHelp(event.target.value)} />
                        <div className="flex flex-wrap items-center gap-3 text-sm"><label className="flex items-center gap-2"><Checkbox checked={sectionLabelOnly} onChange={(event) => setSectionLabelOnly(event.target.checked)} />Label only</label><label className="flex items-center gap-2"><Checkbox checked={sectionOutput} onChange={(event) => setSectionOutput(event.target.checked)} />Output to dataset</label></div>
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
                                <SortableSection key={section.id} section={section} canReorder={canConfigure}>
                                  <SortableContext items={fields.map((f) => f.id)} strategy={verticalListSortingStrategy}>
                                    <div className="space-y-1">
                                      {fields.length ? fields.map((field) => (
                                        <SortableField
                                          key={field.id}
                                          field={field}
                                          codelists={codelists}
                                          selected={field.id === selectedFieldId}
                                          display={activeForm}
                                          canReorder={canConfigureFields}
                                          onSelect={() => setSelectedFieldId(field.id)}
                                        />
                                      )) : <p className="px-3 py-2 text-xs text-muted-foreground">{readOnly ? 'No fields defined.' : 'No fields yet. Drag a type here or use Add field.'}</p>}
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

                  <FormDependencyEditor formId={activeForm.id} forms={formsQuery.data ?? []} canConfigure={canConfigure} />
                </CardContent>
              </>
            )}
          </Card>

        </div>
      </div>
      <Sheet open={formDrawerMode !== null} onOpenChange={(open) => { if (!open) setFormDrawerMode(null) }}>
        <SheetContent side="right" className="w-full overflow-y-auto sm:max-w-xl">
          <SheetHeader>
            <SheetTitle>{formDrawerMode === 'create' ? 'Add form' : 'Form settings'}</SheetTitle>
            <SheetDescription>{readOnly ? 'Review form metadata, layout, and identifier display options.' : 'Configure form metadata, layout, and identifier display options.'}</SheetDescription>
          </SheetHeader>
          {formDrawerMode ? <FormSettingsPanel draft={form} setDraft={setForm} mode={formDrawerMode} pending={formDrawerMode === 'create' ? createForm.isPending : updateForm.isPending} error={formError} onSubmit={() => formDrawerMode === 'create' ? createForm.mutate() : updateForm.mutate()} readOnly={readOnly} /> : null}
        </SheetContent>
      </Sheet>
      <Sheet open={!!selectedField} onOpenChange={(open) => { if (!open) setSelectedFieldId('') }}>
        <SheetContent side="right" className="w-full overflow-y-auto sm:max-w-xl">
          <SheetHeader>
            <SheetTitle>Field settings</SheetTitle>
            <SheetDescription>{(readOnly || !canConfigureFields) ? "Review the selected field's question, identifiers, data type, and presentation." : "Configure the selected field's question, identifiers, data type, and presentation."}</SheetDescription>
          </SheetHeader>
          {selectedField ? <FieldConfigPanel key={selectedField.id} field={selectedField} studyId={studyId} versionId={versionId} readOnly={readOnly || !canConfigureFields} onDone={() => setSelectedFieldId('')} /> : null}
        </SheetContent>
      </Sheet>
    </PageContainer>
  )
}

export function FormBuilderPage({ studyId }: { studyId: string }) {
  return (
    <PermissionGuard permission={PERMISSIONS.DESIGNER_FORM_READ} studyId={studyId}>
      <DraftGate studyId={studyId}>
        {(versionId, selection) => <FormBuilderInner studyId={studyId} versionId={versionId} readOnly={selection.isReadOnly} />}
      </DraftGate>
    </PermissionGuard>
  )
}
