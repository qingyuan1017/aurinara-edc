import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { PermissionGuard } from '@/components/guards/PermissionGuard'
import { PERMISSIONS } from '@/lib/permissions'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { EmptyState, ErrorState, LoadingState, PageContainer, PageHeader } from '@/components/patterns'
import { DraftGate, getApiErrorMessage } from './shared'

interface RawSetting {
  id: string
  field_definition_id?: string | null
  suffix?: string | null
  year_suffix?: string | null
  month_suffix?: string | null
  day_suffix?: string | null
}

interface DesignerField {
  id: string
  label: string
  variable_name: string
  control_type: string
  data_type: string
  codelist_id?: string | null
}

interface DesignerForm {
  id: string
  form_code: string
  name: string
  sections?: Array<{
    is_label_only: boolean
    output_to_dataset: boolean
    fields?: DesignerField[]
  }>
}

interface DatasetVariable {
  name: string
  data_type: string
  label: string
  source: string
  field_definition_id?: string | null
}

interface RawDataset {
  form_definition_id: string
  form_code: string
  dataset_name: string
  variables: DatasetVariable[]
}

type GenerationKind = 'codelist' | 'numeric' | 'date'

const CODELIST_CONTROLS = new Set(['dropdown', 'listbox', 'radio', 'checkbox', 'multi-select', 'coded_term'])
const NUMERIC_CONTROLS = new Set(['integer', 'decimal', 'float', 'slider'])
const NUMERIC_TYPES = new Set(['integer', 'decimal', 'float', 'number', 'numeric'])

function generationKind(field: DesignerField): GenerationKind | null {
  if (field.codelist_id || CODELIST_CONTROLS.has(field.control_type)) return 'codelist'
  if (field.control_type === 'date' || field.data_type.toLowerCase() === 'date') return 'date'
  if (NUMERIC_CONTROLS.has(field.control_type) || NUMERIC_TYPES.has(field.data_type.toLowerCase())) return 'numeric'
  return null
}

function FieldSuffixEditor({ versionId, field, setting, readOnly }: { versionId: string; field: DesignerField; setting?: RawSetting; readOnly: boolean }) {
  const kind = generationKind(field)
  const queryClient = useQueryClient()
  const [suffix, setSuffix] = useState(setting?.suffix ?? (kind === 'codelist' ? 'LABEL' : 'NUM'))
  const [yearSuffix, setYearSuffix] = useState(setting?.year_suffix ?? 'YEAR')
  const [monthSuffix, setMonthSuffix] = useState(setting?.month_suffix ?? 'MONTH')
  const [daySuffix, setDaySuffix] = useState(setting?.day_suffix ?? 'DAY')
  const [message, setMessage] = useState('')

  const save = useMutation({
    mutationFn: async () => (await api.put<RawSetting>(
      `/designer/versions/${versionId}/raw-data-variables/fields/${field.id}`,
      kind === 'date'
        ? { year_suffix: yearSuffix, month_suffix: monthSuffix, day_suffix: daySuffix }
        : { suffix },
    )).data,
    onSuccess: async () => {
      setMessage('Saved')
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['raw-data-settings', versionId] }),
        queryClient.invalidateQueries({ queryKey: ['raw-data-datasets', versionId] }),
      ])
    },
    onError: (error) => setMessage(getApiErrorMessage(error, 'Could not save suffixes.')),
  })

  if (!kind) return null
  const preview = kind === 'date'
    ? [`${field.variable_name}_${yearSuffix.replace(/^_/, '')}`, `${field.variable_name}_${monthSuffix.replace(/^_/, '')}`, `${field.variable_name}_${daySuffix.replace(/^_/, '')}`]
    : [`${field.variable_name}_${suffix.replace(/^_/, '')}`]

  return (
    <div className="grid gap-3 rounded-md border p-3 lg:grid-cols-[minmax(12rem,1fr)_minmax(18rem,2fr)_auto] lg:items-end">
      <div>
        <p className="font-medium">{field.variable_name}</p>
        <p className="text-xs text-muted-foreground">{field.label} · {kind}</p>
      </div>
      <div className={kind === 'date' ? 'grid gap-2 sm:grid-cols-3' : ''}>
        {kind === 'date' ? <>
          <label className="space-y-1 text-xs">Year suffix<Input aria-label={`${field.variable_name} year suffix`} value={yearSuffix} onChange={(event) => setYearSuffix(event.target.value)} disabled={readOnly} /></label>
          <label className="space-y-1 text-xs">Month suffix<Input aria-label={`${field.variable_name} month suffix`} value={monthSuffix} onChange={(event) => setMonthSuffix(event.target.value)} disabled={readOnly} /></label>
          <label className="space-y-1 text-xs">Day suffix<Input aria-label={`${field.variable_name} day suffix`} value={daySuffix} onChange={(event) => setDaySuffix(event.target.value)} disabled={readOnly} /></label>
        </> : <label className="space-y-1 text-xs">Companion suffix<Input aria-label={`${field.variable_name} companion suffix`} value={suffix} onChange={(event) => setSuffix(event.target.value)} disabled={readOnly} /></label>}
        <p className="mt-1 text-xs text-muted-foreground sm:col-span-3">Generates: {preview.join(', ')}</p>
      </div>
      <div className="flex items-center gap-2">
        {!readOnly ? <Button type="button" size="sm" pending={save.isPending} loadingText="Saving…" onClick={() => { setMessage(''); save.mutate() }}>Save</Button> : null}
        {message ? <span className={save.isError ? 'text-xs text-destructive' : 'text-xs text-muted-foreground'}>{message}</span> : null}
      </div>
    </div>
  )
}

function RawDataVariablesEditor({ studyId, versionId, readOnly }: { studyId: string; versionId: string; readOnly: boolean }) {
  const formsQuery = useQuery({
    queryKey: ['raw-data-forms', studyId, versionId],
    queryFn: async () => (await api.get<DesignerForm[]>(`/designer/studies/${studyId}/forms`, { params: { study_version_id: versionId } })).data,
  })
  const settingsQuery = useQuery({
    queryKey: ['raw-data-settings', versionId],
    queryFn: async () => (await api.get<RawSetting[]>(`/designer/versions/${versionId}/raw-data-variables`)).data,
  })
  const datasetsQuery = useQuery({
    queryKey: ['raw-data-datasets', versionId],
    queryFn: async () => (await api.get<RawDataset[]>(`/designer/versions/${versionId}/raw-data-datasets`)).data,
  })

  if (formsQuery.isLoading || settingsQuery.isLoading || datasetsQuery.isLoading) return <PageContainer><LoadingState label="raw-data dataset settings" /></PageContainer>
  if (formsQuery.error || settingsQuery.error || datasetsQuery.error) return <PageContainer><ErrorState message="Raw-data dataset settings could not be loaded." onRetry={() => { void formsQuery.refetch(); void settingsQuery.refetch(); void datasetsQuery.refetch() }} /></PageContainer>

  const forms = formsQuery.data ?? []
  const settings = settingsQuery.data ?? []
  const datasets = datasetsQuery.data ?? []
  const settingsByField = new Map(settings.filter((item) => item.field_definition_id).map((item) => [item.field_definition_id as string, item]))

  return (
    <PageContainer wide>
      <PageHeader title="Raw-data variable settings" description="Each form produces one dataset. Fixed variables are automatic; configure only the suffixes for generated field companions." />
      <Alert className="mb-6"><AlertDescription>Codelist and numeric fields generate a base variable plus one companion. Date fields generate the base variable plus year, month, and day components.</AlertDescription></Alert>
      {!datasets.length ? <EmptyState title="No form datasets" description="Create a form and fields before configuring raw-data variables." /> : <div className="space-y-6">
        {datasets.map((dataset) => {
          const form = forms.find((item) => item.id === dataset.form_definition_id)
          const configurableFields = (form?.sections ?? [])
            .filter((section) => !section.is_label_only && section.output_to_dataset !== false)
            .flatMap((section) => section.fields ?? [])
            .filter((field) => generationKind(field) !== null)
          return <Card key={dataset.form_definition_id}>
            <CardHeader>
              <CardTitle>{dataset.dataset_name}</CardTitle>
              <CardDescription>{dataset.form_code} · {form?.name ?? 'Form dataset'} · {dataset.variables.length} variables</CardDescription>
            </CardHeader>
            <CardContent className="space-y-5">
              {configurableFields.length ? <div className="space-y-2">
                <h3 className="text-sm font-semibold">Generated-variable suffixes</h3>
                {configurableFields.map((field) => <FieldSuffixEditor key={field.id} versionId={versionId} field={field} setting={settingsByField.get(field.id)} readOnly={readOnly} />)}
              </div> : null}
              <div>
                <h3 className="mb-2 text-sm font-semibold">Generated dataset variables</h3>
                <div className="max-h-[28rem] overflow-auto rounded-md border">
                  <Table>
                    <caption className="sr-only">Variables generated for dataset {dataset.dataset_name}</caption>
                    <TableHeader><TableRow><TableHead>Variable</TableHead><TableHead>Type</TableHead><TableHead>Source</TableHead><TableHead>Label</TableHead></TableRow></TableHeader>
                    <TableBody>{dataset.variables.map((variable) => <TableRow key={`${variable.name}-${variable.source}`}>
                      <TableCell className="font-mono font-medium">{variable.name}</TableCell>
                      <TableCell>{variable.data_type}</TableCell>
                      <TableCell>{variable.source.replaceAll('_', ' ')}</TableCell>
                      <TableCell>{variable.label}</TableCell>
                    </TableRow>)}</TableBody>
                  </Table>
                </div>
              </div>
            </CardContent>
          </Card>
        })}
      </div>}
    </PageContainer>
  )
}

export function RawDataVariablesPage({ studyId }: { studyId: string }) {
  return (
    <PermissionGuard permission={PERMISSIONS.DESIGNER_RAW_DATA_VARIABLE_CONFIGURE} studyId={studyId}>
      <DraftGate studyId={studyId}>
        {(versionId, selection) => <RawDataVariablesEditor studyId={studyId} versionId={versionId} readOnly={selection.isReadOnly} />}
      </DraftGate>
    </PermissionGuard>
  )
}
