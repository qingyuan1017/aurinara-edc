import { useMemo, useState } from 'react'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Checkbox } from '@/components/ui/checkbox'
import { Label } from '@/components/ui/label'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Textarea } from '@/components/ui/textarea'
import { PageContainer, PageHeader } from '@/components/patterns'
import { streamAI, type AIStreamEvent } from '@/lib/ai'
import { useStudyContext } from '@/lib/study-context'

const TABS = [
  { id: 'chat', label: 'Chat' },
  { id: 'edit-check', label: 'Draft edit check' },
  { id: 'query-summary', label: 'Summarize query' },
] as const

type TabId = (typeof TABS)[number]['id']
type Suggestion = Record<string, unknown>

function parseSuggestion(output: string): Suggestion | null {
  const fenced = output.match(/```(?:json)?\s*([\s\S]*?)```/i)?.[1] ?? output
  try {
    const parsed: unknown = JSON.parse(fenced.trim())
    return parsed && typeof parsed === 'object' && !Array.isArray(parsed)
      ? parsed as Suggestion
      : null
  } catch {
    return null
  }
}

export function AIAssistantPage() {
  const studyId = useStudyContext((state) => state.selectedStudyId)
  const siteId = useStudyContext((state) => state.selectedSiteId)
  const [tab, setTab] = useState<TabId>('chat')
  const [chatMessage, setChatMessage] = useState('')
  const [editPrompt, setEditPrompt] = useState('')
  const [queryText, setQueryText] = useState('{\n  "text": ""\n}')
  const [output, setOutput] = useState('')
  const [error, setError] = useState('')
  const [status, setStatus] = useState('')
  const [busy, setBusy] = useState(false)
  const [confirmed, setConfirmed] = useState(false)
  const [applyStatus, setApplyStatus] = useState('')

  const suggestion = useMemo(() => parseSuggestion(output), [output])
  const isDataChange = Boolean(suggestion && (suggestion.changes || suggestion.data_changes || suggestion.would_change_data || suggestion.data_change))

  const run = async (path: string, payload: Record<string, unknown>) => {
    setBusy(true)
    setError('')
    setStatus('Generating…')
    setOutput('')
    setApplyStatus('')
    setConfirmed(false)
    try {
      await streamAI(path, {
        ...payload,
        ...(studyId ? { study_id: studyId } : {}),
        ...(siteId ? { site_id: siteId } : {}),
      }, (event: AIStreamEvent) => {
        if (event.type === 'token') setOutput((current) => current + (event.content ?? ''))
        if (event.type === 'error') setError(event.message ?? 'The AI provider returned an error.')
        if (event.type === 'done') setStatus('Generation complete.')
      })
      setStatus((current) => current === 'Generating…' ? 'Generation complete.' : current)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'The AI request could not be completed.')
      setStatus('')
    } finally {
      setBusy(false)
    }
  }

  const applySuggestion = async () => {
    if (!suggestion || !confirmed) return
    setApplyStatus('Applying…')
    setError('')
    try {
      await fetch('/api/v1/ai/apply-suggestion', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(localStorage.getItem('access_token') ? { Authorization: `Bearer ${localStorage.getItem('access_token')}` } : {}),
        },
        body: JSON.stringify({ suggestion, confirmed: true }),
      }).then(async (response) => {
        if (!response.ok) throw new Error('The server rejected this AI suggestion.')
        return response.json()
      })
      setApplyStatus('Suggestion applied and audited.')
      setConfirmed(false)
    } catch (reason) {
      setApplyStatus('')
      setError(reason instanceof Error ? reason.message : 'The suggestion could not be applied.')
    }
  }

  const submit = (event: React.FormEvent) => {
    event.preventDefault()
    if (tab === 'chat') {
      if (!chatMessage.trim()) return setError('Enter a message first.')
      return void run('/ai/chat', { message: chatMessage.trim() })
    }
    if (tab === 'edit-check') {
      if (!editPrompt.trim()) return setError('Describe the edit check you want to draft.')
      return void run('/ai/edit-check-draft', { prompt: editPrompt.trim() })
    }
    try {
      const query = JSON.parse(queryText) as Record<string, unknown>
      return void run('/ai/query-summary', { query })
    } catch {
      setError('Query context must be valid JSON.')
    }
  }

  return (
    <PageContainer wide>
      <PageHeader
        title="AI assistant"
        description="Draft and summarize within your authorized study scope. The server remains authoritative for every request and change."
      />

      <Alert className="mb-6">
        <AlertDescription>
          Context scope: {studyId ? `study ${studyId}${siteId ? ` · site ${siteId}` : ''}` : 'No study selected; only non-clinical prompt text will be sent.'}
        </AlertDescription>
      </Alert>

      <Tabs value={tab} onValueChange={(value) => { setTab(value as TabId); setError('') }} className="space-y-6">
        <TabsList aria-label="AI assistant modes">
          {TABS.map((item) => <TabsTrigger key={item.id} value={item.id}>{item.label}</TabsTrigger>)}
        </TabsList>

        {error ? <Alert variant="destructive"><AlertDescription>{error}</AlertDescription></Alert> : null}
        {status ? <Alert variant="success"><AlertDescription>{status}</AlertDescription></Alert> : null}

        <form onSubmit={submit}>
          <Card>
            <CardContent className="space-y-4 pt-6">
              {tab === 'chat' && <Label>Message<Textarea value={chatMessage} onChange={(event) => setChatMessage(event.target.value)} className="mt-2 min-h-28" placeholder="Ask about an in-scope clinical data-management task." /></Label>}
              {tab === 'edit-check' && <Label>Edit-check request<Textarea value={editPrompt} onChange={(event) => setEditPrompt(event.target.value)} className="mt-2 min-h-28" placeholder="Draft a query-severity check when the adverse-event end date precedes its start date." /></Label>}
              {tab === 'query-summary' && <Label htmlFor="ai-query-context">Query context (JSON)<Textarea id="ai-query-context" value={queryText} onChange={(event) => setQueryText(event.target.value)} className="mt-2 min-h-40 font-mono text-sm" /></Label>}
              <div className="flex justify-end"><Button type="submit" disabled={busy}>{busy ? 'Generating…' : 'Generate'}</Button></div>
            </CardContent>
          </Card>
        </form>
      </Tabs>

      <Card className="mt-6">
        <CardHeader><CardTitle>Assistant output</CardTitle></CardHeader>
        <CardContent><pre aria-label="Assistant output" className="min-h-36 whitespace-pre-wrap rounded-md bg-muted p-4 text-sm text-foreground">{output || 'Generated content will appear here.'}</pre></CardContent>
      </Card>

      {isDataChange && suggestion ? (
        <Card className="mt-6 border-warning/50 bg-warning/10">
          <CardHeader><CardTitle className="text-warning-foreground">Review proposed data change</CardTitle></CardHeader>
          <CardContent>
            <p className="text-sm text-warning-foreground">Nothing is changed automatically. Confirm that the target and values are correct before sending the suggestion to the server.</p>
            <Label className="mt-3 flex items-start gap-2 text-sm text-warning-foreground"><Checkbox checked={confirmed} onChange={(event) => setConfirmed(event.target.checked)} className="mt-1" /> <span>I have reviewed this suggestion and explicitly authorize the proposed change.</span></Label>
            <Button className="mt-4" variant="destructive" disabled={!confirmed || busy} onClick={() => void applySuggestion()}>Apply reviewed suggestion</Button>
            {applyStatus ? <Alert variant="success" className="mt-3"><AlertDescription>{applyStatus}</AlertDescription></Alert> : null}
          </CardContent>
        </Card>
      ) : null}
    </PageContainer>
  )
}
