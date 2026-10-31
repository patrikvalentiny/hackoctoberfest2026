import { useEffect, useRef, useState, type FormEvent } from 'react'
import { ChatCircleDots, PaperPlaneRight, Sparkle } from '@phosphor-icons/react'
import { Button } from '@/components/ui/button'
import { ModelText } from '@/components/ModelText'
import { generateLocalChatReply } from '@/lib/local-ai'
import type { AgentMessage } from '@/lib/planner'

const examples = [
  'What should I watch for during today’s transfers?',
  'Which weather conditions could affect the planned work?',
  'Summarize this day’s forecast and uncertainties.',
]

function storageKey(siteId: string, date: string) {
  return `harbour-pulse:field-chat:${siteId}:${date}`
}

function readMessages(key: string): AgentMessage[] {
  try {
    const value: unknown = JSON.parse(localStorage.getItem(key) ?? '[]')
    if (!Array.isArray(value)) return []
    return value.filter(
      (message): message is AgentMessage =>
        typeof message === 'object' &&
        message !== null &&
        'role' in message &&
        'content' in message &&
        (message.role === 'user' || message.role === 'assistant') &&
        typeof message.content === 'string',
    )
  } catch {
    return []
  }
}

export function ChatPanel({
  siteId,
  date,
  context,
  questionRequest,
}: {
  siteId: string
  date: string
  context: string
  questionRequest?: { id: number; question: string }
}) {
  const key = storageKey(siteId, date)
  const [messages, setMessages] = useState<AgentMessage[]>(() => readMessages(key))
  const [draft, setDraft] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [progress, setProgress] = useState('')
  const list = useRef<HTMLDivElement>(null)
  const section = useRef<HTMLElement>(null)
  const textarea = useRef<HTMLTextAreaElement>(null)

  function persistMessages(next: AgentMessage[]) {
    try {
      localStorage.setItem(key, JSON.stringify(next.slice(-16)))
    } catch {
      setError('This conversation could not be saved on the device.')
    }
  }

  useEffect(() => {
    list.current?.scrollTo({ top: list.current.scrollHeight })
  }, [messages, busy])

  useEffect(() => {
    if (!questionRequest) return
    const frame = window.requestAnimationFrame(() => {
      setDraft(questionRequest.question)
      const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches
      section.current?.scrollIntoView({
        behavior: reducedMotion ? 'auto' : 'smooth',
        block: 'center',
      })
      textarea.current?.focus({ preventScroll: true })
    })
    return () => window.cancelAnimationFrame(frame)
  }, [questionRequest])

  async function submit(event: FormEvent) {
    event.preventDefault()
    const content = draft.trim()
    if (!content || busy) return
    const next = [...messages, { role: 'user' as const, content }].slice(-16)
    setError('')
    setMessages(next)
    persistMessages(next)
    setDraft('')
    setBusy(true)
    setProgress('Loading the local model…')
    try {
      const reply = await generateLocalChatReply(next, context, (report) => {
        setProgress(
          report.progress < 1
            ? `${report.text} ${Math.round(report.progress * 100)}%`
            : 'Thinking about this day…',
        )
      })
      const completed = [...next, { role: 'assistant' as const, content: reply }].slice(-16)
      setMessages(completed)
      persistMessages(completed)
      setProgress('')
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : 'The local assistant could not answer.')
      setProgress('')
    } finally {
      setBusy(false)
    }
  }

  return (
    <section ref={section} aria-labelledby="field-chat-title" className="chat-panel min-h-[24rem]">
      <header className="flex items-start justify-between gap-3 border-b border-border/70 px-4 py-3">
        <div className="flex items-center gap-3">
          <span className="grid size-9 place-items-center rounded-md bg-secondary text-primary">
            <ChatCircleDots className="size-5" aria-hidden />
          </span>
          <div>
            <h2 id="field-chat-title" className="font-display text-lg font-semibold">Ask about this day</h2>
            <p className="text-xs text-muted-foreground">Private, on-device AI · day-specific forecast context</p>
          </div>
        </div>
        <span className="inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs text-muted-foreground">
          <Sparkle className="size-3.5" aria-hidden />
          WebLLM
        </span>
      </header>

      <div
        ref={list}
        className="chat-messages min-h-44 flex-1 space-y-3 overflow-y-auto px-4 py-4"
        aria-live="polite"
        aria-label={`Conversation for ${date}`}
      >
        {messages.length === 0 ? (
          <div className="grid min-h-36 content-center gap-3">
            <p className="text-sm text-muted-foreground">
              Ask about the selected day’s work plan, forecast changes, or weather concerns.
              Answers use the forecast saved on this device.
            </p>
            <div className="flex flex-wrap gap-2">
              {examples.map((example) => (
                <button
                  key={example}
                  type="button"
                  disabled={busy}
                  onClick={() => setDraft(example)}
                  className="rounded-full border px-3 py-1.5 text-left text-xs transition-colors hover:bg-secondary focus-visible:outline-2 focus-visible:outline-ring disabled:opacity-50"
                >
                  {example}
                </button>
              ))}
            </div>
          </div>
        ) : (
          messages.map((message, index) => (
            <div
              key={`${index}-${message.role}`}
              className={`max-w-[92%] rounded-md px-3 py-2.5 text-sm leading-relaxed ${
                message.role === 'user'
                  ? 'ml-auto whitespace-pre-wrap bg-primary text-primary-foreground'
                  : 'mr-auto border bg-card'
              }`}
            >
              {message.role === 'assistant' ? <ModelText text={message.content} /> : message.content}
            </div>
          ))
        )}
        {busy && (
          <p className="mr-auto rounded-md border bg-card px-3 py-2.5 text-sm text-muted-foreground" role="status">
            {progress}
          </p>
        )}
      </div>

      {error && (
        <p role="alert" className="mx-4 mb-2 rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-destructive">
          {error}
        </p>
      )}

      <form onSubmit={submit} className="border-t border-border/70 p-3">
        <label className="sr-only" htmlFor={`field-chat-${siteId}-${date}`}>Ask about the selected workday</label>
        <div className="flex items-end gap-2">
          <textarea
            ref={textarea}
            id={`field-chat-${siteId}-${date}`}
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter' && !event.shiftKey) {
                event.preventDefault()
                event.currentTarget.form?.requestSubmit()
              }
            }}
            placeholder="Ask about this day…"
            rows={2}
            maxLength={1000}
            disabled={busy}
            className="min-h-11 flex-1 resize-y rounded-md border border-input bg-background px-3 py-2 text-sm outline-none placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/40 disabled:opacity-60"
          />
          <Button type="submit" aria-label="Send question" disabled={busy || !draft.trim()} className="size-11 shrink-0 px-0">
            <PaperPlaneRight className="size-5" aria-hidden />
          </Button>
        </div>
        <p className="mt-2 px-1 text-xs text-muted-foreground">
          Local model answers can be incomplete. Confirm operational limits and decisions with the vessel master.
        </p>
      </form>
    </section>
  )
}
