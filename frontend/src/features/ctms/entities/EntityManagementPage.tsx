import { useState, type FormEvent } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { DataTableShell, DetailCard, PageContainer, PageHeader } from '@/components/patterns'
import { PERMISSIONS, usePermission } from '@/lib/permissions'
import { useStudyContext } from '@/lib/study-context'
import {
  ctmsApi,
  ctmsKeys,
  useCTMSReferenceValues,
  useCTMSStudyEntities,
  type CTMSManagedEntity,
  type CTMSManagedSitePayload,
  type CTMSManagedEntityType,
} from '../api'

type EntityTab = Exclude<CTMSManagedEntityType, 'country'>
export type PortfolioEntityType = Exclude<EntityTab, 'site'>
type EntityDraft = Record<string, string>

const ENTITY_TABS: readonly { value: EntityTab; label: string; pluralLabel: string }[] = [
  { value: 'site', label: 'Site', pluralLabel: 'Sites' },
  { value: 'depot', label: 'Depot', pluralLabel: 'Depots' },
  { value: 'staff', label: 'Staff', pluralLabel: 'Staff' },
  { value: 'participating_organization', label: 'Participating Organization', pluralLabel: 'Organizations' },
  { value: 'investigational_product', label: 'Investigational Product', pluralLabel: 'Investigational Products' },
]

const PORTFOLIO_ENTITY_CONTEXT = { pagination: { pageSize: 100 } } as const

export type EntityManagementView = 'study' | 'site-directory' | 'entity-directory'

export interface EntityManagementPageProps {
  view?: EntityManagementView
  entityType?: PortfolioEntityType
}

function emptyDraft(): EntityDraft {
  return {}
}

function compact(values: EntityDraft, keys: readonly string[]) {
  return Object.fromEntries(keys.flatMap((key) => {
    const value = values[key]?.trim()
    return value ? [[key, value]] : []
  }))
}

function entityCode(source: string) {
  return source.trim().toUpperCase().replace(/[^A-Z0-9]+/g, '-').replace(/^-|-$/g, '').slice(0, 100)
}

function payloadFor(entityType: EntityTab, draft: EntityDraft) {
  if (entityType === 'site') {
    throw new Error('Sites use the study-scoped creation endpoint.')
  }
  if (entityType === 'depot') {
    return {
      entity_type: entityType,
      code: entityCode(draft.name),
      name: draft.name.trim(),
      attributes: compact(draft, ['country', 'state', 'city', 'email', 'phone', 'zip_code', 'fax', 'address']),
    }
  }
  if (entityType === 'staff') {
    const name = `${draft.first_name.trim()} ${draft.last_name.trim()}`
    return {
      entity_type: entityType,
      code: entityCode(draft.email),
      name,
      attributes: compact(draft, ['first_name', 'last_name', 'email', 'phone', 'country', 'state', 'address']),
    }
  }
  if (entityType === 'participating_organization') {
    return {
      entity_type: entityType,
      code: entityCode(draft.name),
      name: draft.name.trim(),
      attributes: compact(draft, ['address', 'phone', 'organization_type', 'primary_contact_id']),
    }
  }
  return {
    entity_type: entityType,
    code: entityCode(`${draft.compound_name}-${draft.generic_name}`),
    name: draft.compound_name.trim(),
    attributes: compact(draft, ['generic_name', 'trade_name', 'formulation', 'specification', 'pharmaceutical_company_id']),
  }
}

function sitePayload(draft: EntityDraft): CTMSManagedSitePayload {
  return {
    name: draft.name.trim(),
    state: draft.state.trim(),
    city: draft.city.trim(),
    ...compact(draft, ['country', 'phone', 'fax', 'zip_code', 'email', 'address']),
  }
}

function updatePayloadFor(entityType: EntityTab, draft: EntityDraft) {
  if (entityType === 'site') {
    return {
      name: draft.name.trim(),
      attributes: compact(draft, ['country', 'state', 'city', 'phone', 'fax', 'zip_code', 'email', 'address']),
    }
  }
  const payload = payloadFor(entityType, draft)
  return { name: payload.name, attributes: payload.attributes }
}

function draftFor(entity: CTMSManagedEntity): EntityDraft {
  if (entity.entity_type === 'staff') return { ...(entity.attributes as EntityDraft) }
  if (entity.entity_type === 'investigational_product') {
    return { compound_name: entity.name, ...(entity.attributes as EntityDraft) }
  }
  return { name: entity.name, ...(entity.attributes as EntityDraft) }
}

function attribute(entity: CTMSManagedEntity, name: string) {
  const value = entity.attributes[name]
  return typeof value === 'string' ? value : ''
}

function entitySummary(entity: CTMSManagedEntity) {
  if (entity.entity_type === 'staff') return attribute(entity, 'email')
  if (entity.entity_type === 'participating_organization') return attribute(entity, 'organization_type')
  if (entity.entity_type === 'investigational_product') return attribute(entity, 'generic_name')
  return [attribute(entity, 'city'), attribute(entity, 'state'), attribute(entity, 'country')].filter(Boolean).join(', ')
}

interface EntityFieldProps {
  entityType: EntityTab
  name: string
  label: string
  value: string
  onChange: (name: string, value: string) => void
  required?: boolean
  type?: 'text' | 'email' | 'tel'
  className?: string
  description?: string
}

function EntityField({ entityType, name, label, value, onChange, required, type = 'text', className, description }: EntityFieldProps) {
  const id = `${entityType}-${name}`
  return <div className={`space-y-1.5 ${className ?? ''}`}>
    <Label htmlFor={id}>{label}{required ? ' *' : ''}</Label>
    <Input id={id} name={name} type={type} value={value} onChange={(event) => onChange(name, event.target.value)} required={required} />
    {description ? <p className="text-xs text-muted-foreground">{description}</p> : null}
  </div>
}

interface EntitySelectProps {
  entityType: EntityTab
  name: string
  label: string
  value: string
  onChange: (name: string, value: string) => void
  options: readonly { value: string; label: string }[]
  placeholder: string
  required?: boolean
  disabled?: boolean
  className?: string
  description?: string
}

function EntitySelect({ entityType, name, label, value, onChange, options, placeholder, required, disabled, className, description }: EntitySelectProps) {
  const id = `${entityType}-${name}`
  return <div className={`space-y-1.5 ${className ?? ''}`}>
    <Label htmlFor={id}>{label}{required ? ' *' : ''}</Label>
    <select id={id} name={name} className="h-10 w-full rounded-md border bg-background px-3 text-sm" value={value} onChange={(event) => onChange(name, event.target.value)} required={required} disabled={disabled}>
      <option value="">{placeholder}</option>
      {options.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
    </select>
    {description ? <p className="text-xs text-muted-foreground">{description}</p> : null}
  </div>
}

interface EntityFormProps {
  entityType: EntityTab
  draft: EntityDraft
  staff: readonly CTMSManagedEntity[]
  organizations: readonly CTMSManagedEntity[]
  creationEnabled: boolean
  creationHelp?: string
  availableSites?: readonly CTMSManagedEntity[]
  studySiteMode?: boolean
  submitLabel: string
  countryOptions: readonly { value: string; label: string }[]
  organizationTypeOptions: readonly { value: string; label: string }[]
  onChange: (name: string, value: string) => void
  onSubmit: (event: FormEvent<HTMLFormElement>) => void
  pending: boolean
  error: boolean
}

function EntityForm({ entityType, draft, staff, organizations, creationEnabled, creationHelp, availableSites = [], studySiteMode, submitLabel, countryOptions, organizationTypeOptions, onChange, onSubmit, pending, error }: EntityFormProps) {
  const field = (name: string) => draft[name] ?? ''
  const common = { entityType, onChange }

  return <form className="grid gap-4 sm:grid-cols-2" onSubmit={onSubmit}>
    {entityType === 'site' && studySiteMode ? <>
      <EntitySelect {...common} name="entity_id" label="Available Site" value={field('entity_id')} required placeholder={availableSites.length ? 'Select an available Site' : 'No Sites are available'} options={availableSites.map((site) => ({ value: site.id, label: `${site.name} — ${entitySummary(site) || site.code}` }))} className="sm:col-span-2" />
      <EntityField {...common} name="site_number" label="Study Site ID" value={field('site_number')} required className="sm:col-span-2" description="This identifier is unique within this study and may differ for the same Site in another study." />
    </> : null}

    {entityType === 'site' && !studySiteMode ? <>
      <EntityField {...common} name="name" label="Name" value={field('name')} required />
      <EntitySelect {...common} name="country" label="Country" value={field('country')} placeholder="Select a country" options={countryOptions} />
      <EntityField {...common} name="state" label="State" value={field('state')} required />
      <EntityField {...common} name="city" label="City" value={field('city')} required />
      <EntityField {...common} name="phone" label="Phone" type="tel" value={field('phone')} />
      <EntityField {...common} name="fax" label="Fax" type="tel" value={field('fax')} />
      <EntityField {...common} name="zip_code" label="Zip Code" value={field('zip_code')} />
      <EntityField {...common} name="email" label="Email" type="email" value={field('email')} />
      <EntityField {...common} name="address" label="Address" value={field('address')} className="sm:col-span-2" />
    </> : null}

    {entityType === 'depot' ? <>
      <EntityField {...common} name="name" label="Name" value={field('name')} required />
      <EntitySelect {...common} name="country" label="Country" value={field('country')} required placeholder="Select a country" options={countryOptions} />
      <EntityField {...common} name="state" label="State" value={field('state')} required />
      <EntityField {...common} name="city" label="City" value={field('city')} required />
      <EntityField {...common} name="email" label="Email" type="email" value={field('email')} required />
      <EntityField {...common} name="phone" label="Phone" type="tel" value={field('phone')} required />
      <EntityField {...common} name="zip_code" label="Zip Code" value={field('zip_code')} required />
      <EntityField {...common} name="fax" label="Fax" type="tel" value={field('fax')} />
      <EntityField {...common} name="address" label="Address" value={field('address')} required className="sm:col-span-2" />
    </> : null}

    {entityType === 'staff' ? <>
      <EntityField {...common} name="first_name" label="First Name" value={field('first_name')} required />
      <EntityField {...common} name="last_name" label="Last Name" value={field('last_name')} required />
      <EntityField {...common} name="email" label="Email" type="email" value={field('email')} required />
      <EntityField {...common} name="phone" label="Phone" type="tel" value={field('phone')} />
      <EntitySelect {...common} name="country" label="Country" value={field('country')} placeholder="Select a country" options={countryOptions} />
      <EntityField {...common} name="state" label="State" value={field('state')} />
      <EntityField {...common} name="address" label="Address" value={field('address')} className="sm:col-span-2" />
    </> : null}

    {entityType === 'participating_organization' ? <>
      <EntityField {...common} name="name" label="Name" value={field('name')} required />
      <EntityField {...common} name="address" label="Address" value={field('address')} required />
      <EntityField {...common} name="phone" label="Phone" type="tel" value={field('phone')} required />
      <EntitySelect {...common} name="organization_type" label="Type" value={field('organization_type')} required placeholder="Select an organization type" options={organizationTypeOptions} />
      <EntitySelect {...common} name="primary_contact_id" label="Primary Contact" value={field('primary_contact_id')} placeholder={staff.length ? 'Select a staff member' : 'No staff configured'} options={staff.map((person) => ({ value: person.id, label: person.name }))} />
    </> : null}

    {entityType === 'investigational_product' ? <>
      <EntityField {...common} name="compound_name" label="Compound Name" value={field('compound_name')} required />
      <EntityField {...common} name="generic_name" label="Generic Name" value={field('generic_name')} required />
      <EntityField {...common} name="trade_name" label="Trade Name" value={field('trade_name')} />
      <EntityField {...common} name="formulation" label="Formulation" value={field('formulation')} required />
      <EntityField {...common} name="specification" label="Specification" value={field('specification')} required />
      <EntitySelect {...common} name="pharmaceutical_company_id" label="Pharmaceutical Company" value={field('pharmaceutical_company_id')} required placeholder={organizations.length ? 'Select a participating organization' : 'Create a participating organization first'} options={organizations.map((organization) => ({ value: organization.id, label: organization.name }))} />
    </> : null}

    <div className="sm:col-span-2">
      <Button type="submit" pending={pending} disabled={!creationEnabled}>{submitLabel}</Button>
      {!creationEnabled && creationHelp ? <p className="mt-2 text-sm text-muted-foreground">{creationHelp}</p> : null}
      {error ? <p className="mt-2 text-sm text-destructive" role="alert">Unable to save this entity. Check the required fields or use a unique name.</p> : null}
    </div>
  </form>
}

export function EntityManagementPage({ view = 'study', entityType: requestedEntityType }: EntityManagementPageProps) {
  const studyId = useStudyContext((state) => state.selectedStudyId) ?? ''
  const portfolioView = view !== 'study'
  const visibleTabs = view === 'site-directory'
    ? ENTITY_TABS.filter((tab) => tab.value === 'site')
    : view === 'entity-directory'
      ? ENTITY_TABS.filter((tab) => requestedEntityType ? tab.value === requestedEntityType : tab.value !== 'site')
      : ENTITY_TABS
  const [entityType, setEntityType] = useState<EntityTab>(() => visibleTabs[0]?.value ?? 'site')
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [editingEntity, setEditingEntity] = useState<CTMSManagedEntity | null>(null)
  const [drafts, setDrafts] = useState<Record<EntityTab, EntityDraft>>(() => Object.fromEntries(ENTITY_TABS.map((tab) => [tab.value, emptyDraft()])) as Record<EntityTab, EntityDraft>)
  const canManageCatalog = usePermission(PERMISSIONS.CTMS_OPERATIONAL_STUDY_MANAGEMENT)
  const canManageSites = usePermission(PERMISSIONS.CTMS_OPERATIONAL_SITE_MANAGEMENT, portfolioView ? undefined : studyId || undefined)
  const canAssign = usePermission(PERMISSIONS.CTMS_OPERATIONAL_STUDY_MANAGEMENT, studyId || undefined)
  const references = useCTMSReferenceValues()
  const assignments = useCTMSStudyEntities(portfolioView ? '' : studyId)
  const catalog = useQuery({
    queryKey: ctmsKeys.entities(undefined, PORTFOLIO_ENTITY_CONTEXT),
    queryFn: () => ctmsApi.entities(undefined, PORTFOLIO_ENTITY_CONTEXT),
    enabled: portfolioView,
  })
  const availableSites = useQuery({
    queryKey: [...ctmsKeys.entities(studyId, PORTFOLIO_ENTITY_CONTEXT), 'site'],
    queryFn: () => ctmsApi.availableEntities(studyId, 'site', PORTFOLIO_ENTITY_CONTEXT),
    enabled: !portfolioView && entityType === 'site' && Boolean(studyId) && drawerOpen && !editingEntity,
  })
  const client = useQueryClient()

  const studyEntities = (assignments.data?.items ?? []).map((assignment) => assignment.entity)
  const assignmentsByEntityId = new Map((assignments.data?.items ?? []).map((assignment) => [assignment.entity_id, assignment]))
  const entities = portfolioView ? (catalog.data?.items ?? []) : studyEntities
  const staff = entities.filter((entity) => entity.entity_type === 'staff')
  const organizations = entities.filter((entity) => entity.entity_type === 'participating_organization')
  const countryOptions = (references.data?.items ?? []).filter((value) => value.category === 'country').map((value) => ({ value: value.code, label: value.label }))
  const organizationTypeOptions = (references.data?.items ?? []).filter((value) => value.category === 'participating_organization_type').map((value) => ({ value: value.code, label: value.label }))
  const visibleEntities = entities.filter((entity) => entity.entity_type === entityType)
  const canCreateCurrentType = portfolioView
    ? view === 'site-directory' ? canManageSites : canManageCatalog
    : entityType === 'site' ? canManageSites : canManageCatalog && canAssign
  const canEditCurrentType = portfolioView && (entityType === 'site' ? canManageSites : canManageCatalog)
  const selectedEntity = ENTITY_TABS.find((tab) => tab.value === entityType)
  const selectedEntityLabel = selectedEntity?.label ?? 'entity'
  const selectedEntityPluralLabel = selectedEntity?.pluralLabel ?? 'Entities'
  const save = useMutation({
    mutationFn: async () => {
      if (editingEntity) return ctmsApi.updateEntity(editingEntity.id, updatePayloadFor(entityType, drafts[entityType]))
      if (view === 'site-directory') return ctmsApi.createSite(sitePayload(drafts.site))
      if (portfolioView) return ctmsApi.createEntity(payloadFor(entityType, drafts[entityType]))
      if (entityType === 'site') return ctmsApi.createStudySite(studyId, {
        entity_id: drafts.site.entity_id,
        site_number: drafts.site.site_number.trim(),
      })
      const entity = await ctmsApi.createEntity(payloadFor(entityType, drafts[entityType]))
      await ctmsApi.assignStudyEntity(studyId, entity.id)
      return entity
    },
    onSuccess: async () => {
      setDrafts((current) => ({ ...current, [entityType]: emptyDraft() }))
      await client.invalidateQueries({ queryKey: ctmsKeys.all })
      setEditingEntity(null)
      setDrawerOpen(false)
    },
  })

  const updateDraft = (name: string, value: string) => {
    setDrafts((current) => ({ ...current, [entityType]: { ...current[entityType], [name]: value } }))
  }
  const switchTab = (value: string) => {
    setEntityType(value as EntityTab)
    save.reset()
  }
  const openCreate = () => {
    setEditingEntity(null)
    setDrafts((current) => ({ ...current, [entityType]: emptyDraft() }))
    save.reset()
    setDrawerOpen(true)
  }
  const openEdit = (entity: CTMSManagedEntity) => {
    setEditingEntity(entity)
    setDrafts((current) => ({ ...current, [entityType]: draftFor(entity) }))
    save.reset()
    setDrawerOpen(true)
  }
  const pageTitle = view === 'site-directory' ? 'Site directory' : view === 'entity-directory' ? requestedEntityType ? selectedEntityPluralLabel : 'Entity directory' : 'Entity management'
  const pageDescription = view === 'site-directory'
    ? 'Manage reusable Sites that can be added to one or more studies with a different Study Site ID in each study.'
    : view === 'entity-directory'
      ? requestedEntityType
        ? `Manage ${selectedEntityPluralLabel.toLowerCase()} independently of platform-owned user identities.`
        : 'Manage Depots, Staff, Participating Organizations, and Investigational Products independently of platform-owned user identities.'
      : 'Review the Sites, Depots, Staff, Participating Organizations, and Investigational Products assigned to the selected study.'
  const query = portfolioView ? catalog : assignments
  const emptyTitle = portfolioView
    ? `No ${selectedEntityLabel.toLowerCase()} entities are available.`
    : studyId ? `No ${selectedEntityLabel.toLowerCase()} entities have been added to this study.` : 'Select a study to view its entities.'

  return <PageContainer wide>
    <PageHeader
      title={pageTitle}
      description={pageDescription}
      actions={<Button type="button" onClick={openCreate} disabled={!canCreateCurrentType || (!portfolioView && !studyId)}>{portfolioView ? `Create ${selectedEntityLabel}` : entityType === 'site' ? 'Add Site' : 'Create entity'}</Button>}
    />
    <Tabs value={entityType} onValueChange={switchTab}>
      <div className="overflow-x-auto pb-1">
        <TabsList className="h-auto min-w-max" aria-label="Entity types">
          {visibleTabs.map((tab) => <TabsTrigger key={tab.value} value={tab.value}>{tab.label}</TabsTrigger>)}
        </TabsList>
      </div>

      {visibleTabs.map((tab) => <TabsContent key={tab.value} value={tab.value}>
        <DataTableShell label={`${tab.label} entities`} loading={query.isLoading} error={Boolean(query.error)} errorMessage="Entities could not be loaded." empty={visibleEntities.length === 0} emptyTitle={emptyTitle}>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {visibleEntities.map((entity) => {
              const assignment = assignmentsByEntityId.get(entity.id)
              const summary = entitySummary(entity) || entity.code
              const description = !portfolioView && entity.entity_type === 'site' && assignment?.site_number
                ? `Study Site ID: ${assignment.site_number} · ${summary}`
                : summary
              return <DetailCard key={entity.id} title={entity.name} description={description} footer={canEditCurrentType ? <Button type="button" variant="outline" size="sm" onClick={() => openEdit(entity)}>Edit {selectedEntityLabel}</Button> : undefined}>
              <p className="text-xs text-muted-foreground">{entity.active ? 'Active' : 'Inactive'} · {entity.code}</p>
              </DetailCard>
            })}
          </div>
        </DataTableShell>
      </TabsContent>)}
    </Tabs>

    <Sheet open={drawerOpen} onOpenChange={(open) => { setDrawerOpen(open); if (!open) { save.reset(); setEditingEntity(null) } }}>
      <SheetContent side="right" className="w-full overflow-y-auto sm:max-w-2xl">
        <SheetHeader className="pr-8">
          <SheetTitle>{`${editingEntity ? 'Edit' : !portfolioView && entityType === 'site' ? 'Add' : 'Create'} ${selectedEntityLabel}`}</SheetTitle>
          <SheetDescription>{editingEntity ? `Update this ${selectedEntityLabel.toLowerCase()} without changing its stable identity.` : view === 'site-directory' ? 'Create a reusable Site that study teams can add to their Site lists.' : portfolioView ? `Create a ${selectedEntityLabel.toLowerCase()} in the CTMS entity catalog.` : entityType === 'site' ? 'Select an available Site and enter the site number used in this study.' : `Create a ${selectedEntityLabel.toLowerCase()} and add it to the selected study.`}</SheetDescription>
        </SheetHeader>
        <div className="mt-2 pt-4">
          <EntityForm
            entityType={entityType}
            draft={drafts[entityType]}
            staff={staff}
            organizations={organizations}
            availableSites={availableSites.data?.items ?? []}
            studySiteMode={!portfolioView && entityType === 'site' && !editingEntity}
            creationEnabled={editingEntity ? canEditCurrentType : canCreateCurrentType && (portfolioView || Boolean(studyId)) && (!(!portfolioView && entityType === 'site') || (availableSites.data?.items.length ?? 0) > 0)}
            creationHelp={!portfolioView && entityType === 'site' && !availableSites.isLoading && (availableSites.data?.items.length ?? 0) === 0 ? 'No unassigned Sites are available. Create one in the Site directory first.' : portfolioView ? undefined : 'Select a study before creating an entity.'}
            submitLabel={`${editingEntity ? 'Save' : !portfolioView && entityType === 'site' ? 'Add' : 'Create'} ${selectedEntityLabel}`}
            countryOptions={countryOptions}
            organizationTypeOptions={organizationTypeOptions}
            onChange={updateDraft}
            onSubmit={(event) => { event.preventDefault(); save.mutate() }}
            pending={save.isPending}
            error={Boolean(save.error)}
          />
        </div>
      </SheetContent>
    </Sheet>
  </PageContainer>
}
