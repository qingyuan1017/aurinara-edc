import { Fragment } from 'react'
import { Link } from '@tanstack/react-router'
import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbList,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from '@/components/ui/breadcrumb'
import { useRouteContext, type BreadcrumbItem as RouteBreadcrumbItem } from '@/lib/route-context'

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
  const breadcrumbItems = items ?? routeContext.breadcrumbs

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
