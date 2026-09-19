import { useRef, useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'

interface Attachment { id: string; filename: string; content_type: string; size_bytes: number; uploaded_at: string }
interface FileUploadProps { objectType: string; objectId: string; disabled?: boolean }

export function FileUpload({ objectType, objectId, disabled = false }: FileUploadProps) {
  const input = useRef<HTMLInputElement>(null)
  const [attachment, setAttachment] = useState<Attachment | null>(null)
  const [error, setError] = useState('')
  const upload = useMutation({ mutationFn: async (file: File) => { const form = new FormData(); form.append('file', file); return (await api.post<Attachment>(`/objects/${objectType}/${objectId}/files`, form, { headers: { 'Content-Type': 'multipart/form-data' } })).data }, onSuccess: (data) => { setAttachment(data); setError('') }, onError: () => setError('Upload failed. Confirm the object is accessible and not frozen or locked.') })
  const onChange = (event: React.ChangeEvent<HTMLInputElement>) => { const file = event.target.files?.[0]; if (file) upload.mutate(file); event.target.value = '' }
  return <Card><CardHeader className="pb-3"><div className="flex flex-wrap items-center justify-between gap-3"><div><CardTitle className="text-base">Supporting files</CardTitle><p className="text-xs text-muted-foreground">Upload source or supporting documentation linked to this form.</p></div><input ref={input} type="file" className="hidden" onChange={onChange} disabled={disabled || upload.isPending} /><Button type="button" variant="outline" onClick={() => input.current?.click()} disabled={disabled || upload.isPending}>{upload.isPending ? 'Uploading…' : 'Upload file'}</Button></div></CardHeader><CardContent className="space-y-2">{disabled ? <p className="text-xs text-warning-foreground">Uploads are disabled while the parent form is frozen or locked.</p> : null}{attachment ? <p className="text-sm text-success">Uploaded {attachment.filename} ({Math.ceil(attachment.size_bytes / 1024)} KB).</p> : null}{error ? <Alert variant="destructive"><AlertDescription>{error}</AlertDescription></Alert> : null}</CardContent></Card>
}
