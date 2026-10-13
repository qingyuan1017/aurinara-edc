export function normalizeDataEntryStatus(status: string): 'Not Started' | 'In Progress' | 'Complete' {
  const normalized = status.trim().toLowerCase().replaceAll('_', ' ')
  if (['submitted', 'complete', 'completed', 'reviewed', 'signed', 'frozen', 'locked'].includes(normalized)) return 'Complete'
  if (['in progress', 'draft'].includes(normalized)) return 'In Progress'
  return 'Not Started'
}
