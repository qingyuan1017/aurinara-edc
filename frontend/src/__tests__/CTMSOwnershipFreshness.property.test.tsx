import { render, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import {
  OwnershipCard,
  QualitySignalPresentation,
  StatusPresentation,
  type CanonicalIdentifiers,
  type ProjectionMetadata,
} from '@/features/ctms/components'

type FreshnessState = 'current' | 'stale' | 'unknown'
type SourceModule = 'EDC' | 'CTMS'

interface GeneratedOwnershipCase {
  operationalStatus: string
  clinicalStatus: string
  identifiers: CanonicalIdentifiers
  projection: ProjectionMetadata
  qualitySignal: {
    type: string
    value: number | string | null
  }
}

/** Keep property coverage deterministic and dependency-free when fast-check is unavailable. */
function generatedOwnershipCases(count: number): GeneratedOwnershipCase[] {
  const modules: SourceModule[] = ['EDC', 'CTMS']
  const freshnessStates: FreshnessState[] = ['current', 'stale', 'unknown']

  return Array.from({ length: count }, (_, index) => {
    const freshness = freshnessStates[index % freshnessStates.length]
    const sourceModule = modules[index % modules.length]
    const identifiers: CanonicalIdentifiers = {
      studyId: `study-${index}`,
      siteId: index % 2 === 0 ? `site-${index}` : null,
      subjectId: index % 3 === 0 ? `subject-${index}` : null,
      visitInstanceId: index % 4 === 0 ? `visit-${index}` : null,
    }

    return {
      operationalStatus: `Operational status ${index}`,
      clinicalStatus: `Clinical access state ${index}`,
      identifiers,
      projection: {
        sourceModule,
        sourceRecordId: index % 5 === 0 ? null : `source-record-${index}`,
        sourceTimestamp: freshness === 'unknown' ? null : `2026-03-${String((index % 9) + 1).padStart(2, '0')}T09:55:00Z`,
        projectedAt: `2026-03-${String((index % 9) + 1).padStart(2, '0')}T10:00:00Z`,
        sourceVersion: index % 2 === 0 ? index : null,
        ruleVersion: index % 3 === 0 ? `quality-rule-${index}` : null,
        freshness,
        status: freshness,
        // The presentation must remain read-only even if a malformed response says otherwise.
        readOnly: index % 2 === 0,
      },
      qualitySignal: {
        type: `Quality signal ${index}`,
        value: index % 3 === 0 ? index : index % 3 === 1 ? `value-${index}` : null,
      },
    }
  })
}

describe('CTMS ownership and freshness presentation properties', () => {
  // Feature: ctms-frontend, Property 4: Ownership and freshness presentation is explicit
  // **Validates: Requirements 1.3, 1.6, 6.3, 7.1–7.5, 12.1–12.4**
  it('always presents ownership, canonical identifiers, freshness, and read-only projection semantics across 128 generated cases', () => {
    for (const scenario of generatedOwnershipCases(128)) {
      const { unmount } = render(
        <div data-testid="ownership-scenario">
          <StatusPresentation kind="operational" status={scenario.operationalStatus} owner="CTMS" readOnly={false} />
          <StatusPresentation kind="clinical" status={scenario.clinicalStatus} owner="EDC" />
          <OwnershipCard title="Generated operational record" identifiers={scenario.identifiers}>
            <QualitySignalPresentation
              signalType={scenario.qualitySignal.type}
              value={scenario.qualitySignal.value}
              metadata={scenario.projection}
            />
          </OwnershipCard>
        </div>,
      )

      const root = within(document.body).getByTestId('ownership-scenario')
      const operational = within(root).getByTestId('operational-status')
      const clinical = within(root).getByTestId('clinical-status')
      const qualitySignal = within(root).getByTestId('quality-signal')
      const freshness = within(qualitySignal).getByTestId('projection-freshness')

      expect(operational).toHaveTextContent(`Operational status: ${scenario.operationalStatus}`)
      expect(within(operational).getByLabelText(new RegExp(`authoritative module: CTMS`))).toBeInTheDocument()
      expect(within(operational).queryByTestId('read-only-indicator')).not.toBeInTheDocument()

      expect(clinical).toHaveTextContent(`Clinical access state: ${scenario.clinicalStatus}`)
      expect(within(clinical).getByLabelText(new RegExp(`authoritative module: EDC`))).toBeInTheDocument()
      expect(within(clinical).getByTestId('read-only-indicator')).toBeInTheDocument()

      const identifierLabels: Array<[keyof CanonicalIdentifiers, string]> = [
        ['studyId', 'EDC Study ID'],
        ['siteId', 'EDC Site ID'],
        ['subjectId', 'EDC Subject ID'],
        ['visitInstanceId', 'EDC Visit Instance ID'],
      ]
      for (const [key, label] of identifierLabels) {
        const identifier = scenario.identifiers[key]
        if (identifier) {
          expect(within(root).getByText(label)).toBeInTheDocument()
          expect(within(root).getByText(identifier)).toBeInTheDocument()
        }
      }

      expect(qualitySignal).toHaveTextContent(scenario.qualitySignal.type)
      expect(qualitySignal).toHaveTextContent(String(scenario.qualitySignal.value ?? '—'))
      expect(within(qualitySignal).getByText('Approved aggregate quality signal · read-only projection')).toBeInTheDocument()
      expect(within(qualitySignal).getByText(/does not expose individual clinical records or authorize EDC clinical changes/)).toBeInTheDocument()
      expect(qualitySignal).toHaveAttribute('data-clinical-mutation-actions', 'none')

      expect(freshness).toHaveAttribute('data-freshness', scenario.projection.freshness)
      expect(within(freshness).getByLabelText(new RegExp(`authoritative module: ${scenario.projection.sourceModule}`))).toBeInTheDocument()
      expect(within(freshness).getByTestId('read-only-indicator')).toBeInTheDocument()
      expect(within(freshness).getByText('Source timestamp:')).toBeInTheDocument()
      expect(within(freshness).getByText('Projected at:')).toBeInTheDocument()
      expect(freshness).toHaveAttribute('data-clinical-mutation-actions', 'none')

      if (scenario.projection.sourceRecordId) {
        expect(within(freshness).getByText(scenario.projection.sourceRecordId)).toBeInTheDocument()
      }
      if (scenario.projection.sourceVersion !== null) {
        expect(within(freshness).getByText(String(scenario.projection.sourceVersion))).toBeInTheDocument()
      }
      if (scenario.projection.ruleVersion !== null) {
        expect(within(freshness).getByText(scenario.projection.ruleVersion)).toBeInTheDocument()
      }

      unmount()
    }
  })
})
