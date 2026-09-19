export type FreshnessState = 'current' | 'stale' | 'unknown'

export function isFreshnessState(value: unknown): value is FreshnessState {
  return value === 'current' || value === 'stale' || value === 'unknown'
}

export function getProjectionFreshness(
  sourceTimestamp?: string | null,
  now: Date = new Date(),
  staleAfterMinutes = 60,
): FreshnessState {
  if (!sourceTimestamp) return 'unknown'
  const source = new Date(sourceTimestamp)
  if (Number.isNaN(source.getTime())) return 'unknown'
  const ageMinutes = (now.getTime() - source.getTime()) / 60_000
  return ageMinutes > staleAfterMinutes ? 'stale' : 'current'
}

/** Prefer a server freshness classification, falling back to the timestamp contract. */
export function resolveProjectionFreshness({
  freshness,
  sourceTimestamp,
  now,
  staleAfterMinutes,
}: {
  freshness?: unknown
  sourceTimestamp?: string | null
  now?: Date
  staleAfterMinutes?: number
}): FreshnessState {
  if (freshness === 'fresh') return 'current'
  return isFreshnessState(freshness)
    ? freshness
    : getProjectionFreshness(sourceTimestamp, now, staleAfterMinutes)
}
