import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { usePermission, PERMISSIONS } from '@/lib/permissions'

interface Field {
  id: string
  label: string
  variable_name: string
  control_type: string
  data_type: string
  is_required: boolean
  display_order: number
}
interface Section { id: string; name: string; display_order: number; fields: Field[] }
interface FormDefinition {
  id: string; name: string; form_code: string; display_order: number
  is_repeating: boolean; sections?: Section[]
}

const CONTROL_TYPES = ['text', 'textarea', 'integer', 'decimal', 'date', 'datetime', 'time', 'radio', 'checkbox', 'dropdown', 'multi-select', 'boolean', 'file_upload', 'calculated', 'repeating_table', 'coded_term']

export function FormBuilderPage({ studyId }: { studyId: string }) {
  const queryClient = useQueryClient()
  const canConfigure = usePermission(PERMISSIONS.FORM_CONFIGURE)
  const [selectedId, setSelectedId] = useState('')
  const [form, setForm] = useState({ name: '', form_code: '', display_order: 0, is_repeating: false })
  const [sectionName, setSectionName] = useState('')
  const [field, setField] = useState({ label: '', variable_name: '', control_type: 'text', data_type: 'string', is_required: false })
  const [error, setError] = useState('')

  const formsQuery = useQuery({
    queryKey: ['form-definitions', studyId],
    queryFn: async () => (await api.get<FormDefinition[]>(`/studies/${studyId}/forms`)).data,
  })
  const selected = formsQuery.data?.find((item) => item.id === selectedId)
  const detailQuery = useQuery({
    queryKey: ['form-definition', selectedId],
    enabled: !!selectedId,
    queryFn: async () => (await api.get<FormDefinition>(`/forms/${selectedId}`)).data,
  })
  const activeForm = detailQuery.data ?? selected

  const createForm = useMutation({
    mutationFn: () => api.post(`/studies/${studyId}/forms`, form),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ['form-definitions', studyId] }); setForm({ name: '', form_code: '', display_order: 0, is_repeating: false }) },
    onError: () => setError('Could not create form. A draft study version and form.configure permission are required.'),
  })
  const createSection = useMutation({
    mutationFn: () => api.post(`/forms/${selectedId}/sections`, { name: sectionName, display_order: activeForm?.sections?.length ?? 0 }),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ['form-definition', selectedId] }); setSectionName('') },
    onError: () => setError('Could not create section.'),
  })
  const createField = useMutation({
    mutationFn: (sectionId: string) => api.post(`/forms/${selectedId}/fields`, { ...field, display_order: 0 }, { params: { section_id: sectionId } }),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ['form-definition', selectedId] }); setField({ label: '', variable_name: '', control_type: 'text', data_type: 'string', is_required: false }) },
    onError: () => setError('Could not create field.'),
  })

  return (
    <div className="space-y-6">
      <div><h1 className="text-2xl font-bold text-gray-900">Form Builder</h1><p className="text-sm text-gray-500">Configure eCRF definitions on the current draft study version.</p></div>
      {error && <p className="rounded bg-red-50 p-3 text-sm text-red-700">{error}</p>}
      <div className="grid gap-6 lg:grid-cols-[18rem_1fr]">
        <section className="rounded-lg border bg-white p-4 space-y-3">
          <div className="flex items-center justify-between"><h2 className="font-semibold">Forms</h2><span className="text-xs text-gray-500">{formsQuery.data?.length ?? 0}</span></div>
          {formsQuery.isLoading && <p className="text-sm text-gray-500">Loading…</p>}
          {formsQuery.data?.map((item) => <button type="button" key={item.id} onClick={() => setSelectedId(item.id)} className={`block w-full rounded px-3 py-2 text-left text-sm ${item.id === selectedId ? 'bg-blue-50 text-blue-700' : 'hover:bg-gray-50'}`}><b>{item.form_code}</b> — {item.name}</button>)}
          {!formsQuery.data?.length && <p className="text-sm text-gray-500">No forms yet.</p>}
          {canConfigure && <form className="border-t pt-3 space-y-2" onSubmit={(e) => { e.preventDefault(); createForm.mutate() }}>
            <h3 className="text-sm font-medium">Add form</h3>
            <input required placeholder="Form name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} className="w-full rounded border px-2 py-1.5 text-sm" />
            <input required placeholder="Form code" value={form.form_code} onChange={(e) => setForm({ ...form, form_code: e.target.value })} className="w-full rounded border px-2 py-1.5 text-sm" />
            <label className="flex gap-2 text-sm"><input type="checkbox" checked={form.is_repeating} onChange={(e) => setForm({ ...form, is_repeating: e.target.checked })} /> Repeating form</label>
            <button disabled={createForm.isPending} className="w-full rounded bg-blue-600 px-3 py-2 text-sm text-white disabled:opacity-50">{createForm.isPending ? 'Creating…' : 'Create form'}</button>
          </form>}
        </section>
        <section className="rounded-lg border bg-white p-5">
          {!activeForm ? <p className="text-gray-500">Select a form to configure its sections and fields.</p> : <>
            <div className="flex items-start justify-between"><div><h2 className="text-xl font-semibold">{activeForm.name}</h2><p className="text-sm text-gray-500">{activeForm.form_code} · {activeForm.is_repeating ? 'Repeating' : 'Non-repeating'}</p></div></div>
            {canConfigure && <form className="mt-5 flex gap-2" onSubmit={(e) => { e.preventDefault(); createSection.mutate() }}><input required placeholder="New section name" value={sectionName} onChange={(e) => setSectionName(e.target.value)} className="flex-1 rounded border px-3 py-2 text-sm" /><button className="rounded border px-3 py-2 text-sm hover:bg-gray-50">Add section</button></form>}
            <div className="mt-5 space-y-4">{activeForm.sections?.map((section) => <div key={section.id} className="rounded border p-4"><h3 className="font-medium">{section.name}</h3><div className="mt-2 space-y-1">{section.fields?.map((item) => <div key={item.id} className="flex justify-between rounded bg-gray-50 px-3 py-2 text-sm"><span>{item.label} <span className="text-gray-400">({item.variable_name})</span></span><span className="text-gray-500">{item.control_type}{item.is_required ? ' · required' : ''}</span></div>)}</div>{canConfigure && <form className="mt-3 grid gap-2 sm:grid-cols-4" onSubmit={(e) => { e.preventDefault(); createField.mutate(section.id) }}><input required placeholder="Field label" value={field.label} onChange={(e) => setField({ ...field, label: e.target.value })} className="rounded border px-2 py-1.5 text-sm" /><input required placeholder="Variable name" value={field.variable_name} onChange={(e) => setField({ ...field, variable_name: e.target.value })} className="rounded border px-2 py-1.5 text-sm" /><select value={field.control_type} onChange={(e) => setField({ ...field, control_type: e.target.value })} className="rounded border px-2 py-1.5 text-sm">{CONTROL_TYPES.map((type) => <option key={type}>{type}</option>)}</select><button className="rounded bg-gray-800 px-2 py-1.5 text-sm text-white">Add field</button></form>}</div>)}</div>
          </>}
        </section>
      </div>
    </div>
  )
}
