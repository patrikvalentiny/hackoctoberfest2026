import { useEffect, useRef } from 'react'
import { cn } from '@/lib/utils'
import { useToolCalls } from '@/lib/tool-log'

function compact(value: unknown) {
  const text = JSON.stringify(value)
  return text === '{}' ? '' : text
}

export function ToolPanel() {
  const calls = useToolCalls()
  const list = useRef<HTMLOListElement>(null)

  // Scroll only the log itself, never the page, so the newest call stays in view.
  useEffect(() => {
    if (list.current) list.current.scrollTop = list.current.scrollHeight
  }, [calls])

  return (
    <section aria-labelledby="tools-title" className="tool-panel flex min-h-0 flex-col">
      <header className="flex items-baseline justify-between px-4 pt-3 pb-2">
        <h2 id="tools-title" className="font-display text-base font-semibold">
          Tool calls
        </h2>
        <p className="text-xs text-muted-foreground">Every number on the dashboard comes from one of these</p>
      </header>
      {calls.length === 0 ? (
        <p className="px-4 pb-4 text-sm text-muted-foreground">No tools called yet.</p>
      ) : (
        <ol ref={list} className="min-h-0 flex-1 overflow-y-auto px-2 pb-2 font-code text-xs" aria-live="polite">
          {calls.map((call) => (
            <li
              key={call.id}
              className="grid grid-cols-[2.2rem_minmax(8rem,auto)_1fr] items-baseline gap-x-3 rounded px-2 py-1 sm:grid-cols-[2.2rem_3.2rem_10rem_1fr_4rem]"
            >
              <span className="text-muted-foreground tabular-nums">{call.id}</span>
              <span className="hidden text-muted-foreground sm:block">{call.caller}</span>
              <span className="font-semibold">{call.tool}</span>
              <span className="col-span-full min-w-0 sm:col-span-1">
                <span className="block truncate text-muted-foreground">{compact(call.input)}</span>
                <span
                  className={cn(
                    'block',
                    call.status === 'error' && 'text-destructive',
                    call.status === 'running' && 'text-muted-foreground',
                  )}
                >
                  {call.status === 'running' ? 'running…' : call.summary}
                </span>
              </span>
              <span className="hidden text-right text-muted-foreground tabular-nums sm:block">
                {call.duration_ms !== undefined && `${call.duration_ms} ms`}
              </span>
            </li>
          ))}
        </ol>
      )}
    </section>
  )
}
