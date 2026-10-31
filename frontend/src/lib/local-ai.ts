import type { InitProgressReport, MLCEngineInterface } from '@mlc-ai/web-llm'

const modelId = 'Llama-3.2-1B-Instruct-q4f16_1-MLC'

let enginePromise: Promise<MLCEngineInterface> | undefined

async function getEngine(onProgress: (progress: InitProgressReport) => void) {
  if (!enginePromise) {
    enginePromise = import('@mlc-ai/web-llm').then(({ CreateWebWorkerMLCEngine }) => {
      const worker = new Worker(new URL('./webllm.worker.ts', import.meta.url), {
        type: 'module',
      })
      return CreateWebWorkerMLCEngine(worker, modelId, {
        initProgressCallback: onProgress,
      })
    })
    enginePromise.catch(() => {
      enginePromise = undefined
    })
  }
  return enginePromise
}

// The limits are safety nets well above the requested length. If one is still
// hit, end on the last complete sentence instead of mid-word.
function endOnSentence(text: string): string {
  const end = Math.max(...['.', '!', '?'].map((mark) => text.lastIndexOf(mark)))
  return end > 0 ? text.slice(0, end + 1) : text
}

export async function generateLocalSummary(
  prompt: string,
  onProgress: (progress: InitProgressReport) => void,
): Promise<string> {
  return generateLocalChatReply(
    [{ role: 'user', content: prompt }],
    'Summarize the supplied offshore forecast data. Be concise and factual.',
    onProgress,
    400,
  )
}

export async function generateLocalChatReply(
  messages: { role: 'user' | 'assistant'; content: string }[],
  context: string,
  onProgress: (progress: InitProgressReport) => void,
  maxTokens = 400,
): Promise<string> {
  if (!('gpu' in navigator)) {
    throw new Error('This browser does not support WebGPU, which Harbour Pulse needs for local AI.')
  }

  const engine = await getEngine(onProgress)
  const response = await engine.chat.completions.create({
    messages: [
      {
        role: 'system',
        content:
          `You are Harbour Pulse, an offline assistant for offshore wind technicians. Answer only from the provided day briefing and general maintenance context. Distinguish forecast from observation, call out uncertainty or missing data, and do not invent measurements or thresholds. Never make a go/no-go or safety decision; direct the crew to site-approved limits and the vessel master. Keep answers short and simple: plain words, no preamble and no repeating the question. Unless the request gives its own format, use at most 3 short sentences or 4 short bullets and no headings; if it does, follow that format and keep every line short. Give times as HH:MM and always include units.\n\nDAY BRIEFING:\n${context}`,
      },
      ...messages,
    ],
    temperature: 0.2,
    // Small models loop on lists; discourage repeating the same words.
    frequency_penalty: 0.4,
    max_tokens: maxTokens,
  })
  const choice = response.choices[0]
  const answer = choice?.message.content
  if (typeof answer !== 'string' || !answer.trim()) {
    throw new Error('The browser model returned an empty summary. Try again.')
  }
  const text = dropRepeatedLines(answer.trim())
  return choice.finish_reason === 'length' ? endOnSentence(text) : text
}

// Keeps the first copy of any line the model repeats word for word.
function dropRepeatedLines(text: string): string {
  const seen = new Set<string>()
  return text
    .split('\n')
    .filter((line) => {
      const key = line.trim().toLowerCase()
      if (!key) return true
      if (seen.has(key)) return false
      seen.add(key)
      return true
    })
    .join('\n')
}
