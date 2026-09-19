import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { AIAssistantPage } from '@/features/ai'
import { useAuthStore } from '@/lib/auth'
import { useStudyContext } from '@/lib/study-context'

function renderPage() {
  return render(<QueryClientProvider client={new QueryClient()}><AIAssistantPage /></QueryClientProvider>)
}

function streamResponse(content: string) {
  const body = new ReadableStream({
    start(controller) {
      controller.enqueue(new TextEncoder().encode(content))
      controller.close()
    },
  })
  return new Response(body, { status: 200, headers: { 'Content-Type': 'text/event-stream' } })
}

describe('AI assistant', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    useAuthStore.setState({
      user: { id: 'user-1', email: 'dm@example.com', first_name: 'Data', last_name: 'Manager', roles: [], permissions: ['form.read', 'editcheck.configure', 'form.enter'] },
      isAuthenticated: true,
    })
    useStudyContext.setState({ selectedStudyId: 'study-1', selectedSiteId: 'site-1' })
  })

  it('streams a scoped chat request into the output panel', async () => {
    const fetch = vi.fn().mockResolvedValue(streamResponse('data: {"type":"token","content":"Hello"}\n\ndata: {"type":"done"}\n\n'))
    vi.stubGlobal('fetch', fetch)
    renderPage()

    fireEvent.change(screen.getByLabelText('Message'), { target: { value: 'Help with this study.' } })
    fireEvent.click(screen.getByRole('button', { name: 'Generate' }))

    expect(await screen.findByText('Hello')).toBeInTheDocument()
    expect(fetch).toHaveBeenCalledWith('/api/v1/ai/chat', expect.objectContaining({
      method: 'POST',
      body: JSON.stringify({ message: 'Help with this study.', study_id: 'study-1', site_id: 'site-1' }),
    }))
  })

  it('requires explicit confirmation before applying a streamed data suggestion', async () => {
    const suggestion = JSON.stringify({ target: { id: 'form-1', entity_type: 'form_instance' }, changes: { 'field-1': 'updated' } })
    const fetch = vi.fn()
      .mockResolvedValueOnce(streamResponse(`data: {"type":"token","content":${JSON.stringify(suggestion)}}\n\ndata: {"type":"done"}\n\n`))
      .mockResolvedValueOnce(new Response(JSON.stringify({ status: 'applied' }), { status: 200 }))
    vi.stubGlobal('fetch', fetch)
    renderPage()

    fireEvent.click(screen.getByRole('tab', { name: 'Draft edit check' }))
    fireEvent.change(screen.getByLabelText('Edit-check request'), { target: { value: 'Draft a check.' } })
    fireEvent.click(screen.getByRole('button', { name: 'Generate' }))

    const apply = await screen.findByRole('button', { name: 'Apply reviewed suggestion' })
    expect(apply).toBeDisabled()
    expect(fetch).toHaveBeenCalledTimes(1)

    fireEvent.click(screen.getByRole('checkbox'))
    expect(apply).toBeEnabled()
    fireEvent.click(apply)
    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(2))
    expect(fetch.mock.calls[1][0]).toBe('/api/v1/ai/apply-suggestion')
    expect(JSON.parse(fetch.mock.calls[1][1].body)).toMatchObject({ confirmed: true })
  })
})
