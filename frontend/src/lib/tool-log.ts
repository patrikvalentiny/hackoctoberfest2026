import { useSyncExternalStore } from 'react'

// Every planner API call is recorded here. The agent's tool calls will join the
// same log, so the panel shows what produced each number on the dashboard.
export type ToolCall = {
  id: number
  tool: string
  caller: 'ui' | 'agent'
  input: unknown
  status: 'running' | 'ok' | 'error'
  summary?: string
  started_at: number
  duration_ms?: number
}

let calls: ToolCall[] = []
let nextId = 1
const listeners = new Set<() => void>()

function emit() {
  for (const listener of listeners) listener()
}

export function startCall(tool: string, input: unknown, caller: ToolCall['caller'] = 'ui') {
  const call: ToolCall = {
    id: nextId++,
    tool,
    caller,
    input,
    status: 'running',
    started_at: Date.now(),
  }
  calls = [...calls, call]
  emit()
  return call.id
}

export function finishCall(id: number, status: 'ok' | 'error', summary: string) {
  calls = calls.map((call) =>
    call.id === id
      ? { ...call, status, summary, duration_ms: Date.now() - call.started_at }
      : call,
  )
  emit()
}

export function clearCalls() {
  calls = []
  emit()
}

function subscribe(listener: () => void) {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

export function useToolCalls() {
  return useSyncExternalStore(subscribe, () => calls)
}
