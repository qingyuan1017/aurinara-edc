import { Fragment } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbList,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from '@/components/ui/breadcrumb'
import { decodeRouteIdentifier, useRouteContext, type BreadcrumbItem as RouteBreadcrumbItem } from '@/lib/route-context'
import { api } from '@/lib/api'

interface SubjectBreadcrumbData {
  subject_number: string
}

interface FormBreadcrumbData {
  form_name: string
  subject_number: string
}

export interface BreadcrumbsProps {
  /** Optional override for consumers that already have a route context snapshot. */
  items?: readonly RouteBreadcrumbItem[]
}

/**
 * Route-aware breadcrumbs. Parent links use the route-context search updater so
 * breadcrumb navigation never drops supported filters or pagination state.
 */
export function Breadcrumbs({ items }: BreadcrumbsProps) {
  const routeContext = useRouteContext()
  const segments = routeContext.pathname.split('/').filter(Boolean)
  const subjectIndex = segments.indexOf('subjects') + 1
  const formsIndex = segments.indexOf('forms')
  const formIndex = formsIndex >= 0 ? formsIndex + 1 : -1
  const subjectId = subjectIndex > 0 ? decodeRouteIdentifier(segments[subjectIndex] ?? '') : ''
  const formInstanceId = formIndex > 0 ? decodeRouteIdentifier(segments[formIndex] ?? '') : ''
  const { data: form } = useQuery({
    queryKey: ['breadcrumb-form', formInstanceId],
    enabled: !items && Boolean(formInstanceId),
    queryFn: async () => (await api.get<FormBreadcrumbData>(`/form-instances/${formInstanceId}`)).data,
    staleTime: 5 * 60 * 1000,
  })
  const { data: subject } = useQuery({
    queryKey: ['breadcrumb-subject', subjectId],
    enabled: !items && Boolean(subjectId) && !formInstanceId,
    queryFn: async () => (await api.get<SubjectBreadcrumbData>(`/subjects/${subjectId}`)).data,
    staleTime: 5 * 60 * 1000,
  })
  const breadcrumbItems = (items ?? routeContext.breadcrumbs).map((item, index) => {
    if (index === subjectIndex) {
      const subjectNumber = form?.subject_number ?? subject?.subject_number
      return {
        ...item,
        label: subjectNumber ? `Subject ${subjectNumber}` : 'Subject',
        ...(index < segments.length - 1
          ? { to: `/subjects/${segments[subjectIndex]}/casebook`, current: false }
          : {}),
      }
    }
    if (index === formIndex) {
      return { ...item, label: form?.form_name ? `Form ${form.form_name}` : 'Form' }
    }
    return item
  }).filter((_, index) => !subjectId || index !== formsIndex)

  return (
    <Breadcrumb>
      <BreadcrumbList>
        {breadcrumbItems.map((item, index) => (
          <Fragment key={`${item.label}-${index}`}>
            <BreadcrumbItem>
              {item.to && !item.current ? (
                <Link
                  to={item.to}
                  search={item.search}
                  className="transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
                >
                  {item.label}
                </Link>
              ) : (
                <BreadcrumbPage>{item.label}</BreadcrumbPage>
              )}
            </BreadcrumbItem>
            {!item.current && <BreadcrumbSeparator />}
          </Fragment>
        ))}
      </BreadcrumbList>
    </Breadcrumb>
  )
}
