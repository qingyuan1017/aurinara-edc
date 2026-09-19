export interface AIStreamEvent {
  type?: 'token' | 'done' | 'error' | string
  content?: string
  code?: string
  message?: string
  [key: string]: unknown
}

function parseErrorBody(body: string): string {
  try {
    const parsed = JSON.parse(body) as { error?: { message?: string }; detail?: string }
    return parsed.error?.message ?? parsed.detail ?? 'The AI request could not be completed.'
  } catch {
    return body || 'The AI request could not be completed.'
  }
}

/**
 * Read the backend's Server-Sent Events stream using the browser fetch API.
 * Axios is intentionally not used here because browser response streaming is
 * exposed through ReadableStream on fetch. The access token is only a
 * convenience; the backend remains responsible for authentication and scope.
 */
export async function streamAI(
  path: string,
  payload: Record<string, unknown>,
  onEvent: (event: AIStreamEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const token = localStorage.getItem('access_token')
  const response = await fetch(`/api/v1${path}`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify(payload),
    signal,
  })

  if (!response.ok) {
    throw new Error(parseErrorBody(await response.text()))
  }
  if (!response.body) {
    throw new Error('The AI response did not include a stream.')
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  const consume = (block: string) => {
    const data = block
      .split(/\r?\n/)
      .filter((line) => line.startsWith('data:'))
      .map((line) => line.slice(5).trimStart())
      .join('\n')
    if (!data) return
    try {
      onEvent(JSON.parse(data) as AIStreamEvent)
    } catch {
      onEvent({ type: 'token', content: data })
    }
  }

  while (true) {
    const { done, value } = await reader.read()
    buffer += decoder.decode(value, { stream: !done })
    const blocks = buffer.split(/\r?\n\r?\n/)
    buffer = blocks.pop() ?? ''
    blocks.forEach(consume)
    if (done) break
  }
  if (buffer.trim()) consume(buffer)
}
