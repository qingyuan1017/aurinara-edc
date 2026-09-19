import * as React from 'react'
import { PageContainer, PageHeader, OwnershipBadge } from '@/components/patterns'
import { SignatureDialog } from './SignatureDialog'
import { SignatureHistory } from './SignatureHistory'

interface SubjectSignaturesPageProps { subjectId: string }

/** Subject-level signature workspace with re-authenticated signing and history. */
export function SubjectSignaturesPage({ subjectId }: SubjectSignaturesPageProps) {
  const [refreshKey, setRefreshKey] = React.useState(0)
  return <PageContainer wide>
    <PageHeader title="Electronic signatures" description="Review and attest the signed subject and form data." ownership={<OwnershipBadge owner="EDC" />} actions={<SignatureDialog objectType="subject" objectId={subjectId} buttonLabel="Sign subject" onSigned={() => setRefreshKey((value) => value + 1)} />} />
    <div key={refreshKey}><SignatureHistory subjectId={subjectId} /></div>
  </PageContainer>
}

export { SignatureDialog, SignatureHistory }
export type { SignatureRecord } from './SignatureDialog'
