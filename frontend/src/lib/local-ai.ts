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

export async function generateLocalSummary(
  prompt: string,
  onProgress: (progress: InitProgressReport) => void,
): Promise<string> {
  return generateLocalChatReply(
    [{ role: 'user', content: prompt }],
    'Summarize the supplied offshore forecast data. Be concise and factual.',
    onProgress,
    600,
  )
}

export async function generateLocalChatReply(
  messages: { role: 'user' | 'assistant'; content: string }[],
  context: string,
  onProgress: (progress: InitProgressReport) => void,
  maxTokens = 220,
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
          `You are Harbour Pulse, an offline assistant for offshore wind technicians. Answer only from the provided day briefing and general maintenance context. Distinguish forecast from observation, call out uncertainty or missing data, and do not invent measurements or thresholds. Never make a go/no-go or safety decision; direct the crew to site-approved limits and the vessel master. Keep answers concise.\n\nDAY BRIEFING:\n${context}`,
      },
      ...messages,
    ],
    temperature: 0.2,
    max_tokens: maxTokens,
  })
  const answer = response.choices[0]?.message.content
  if (typeof answer !== 'string' || !answer.trim()) {
    throw new Error('The browser model returned an empty summary. Try again.')
  }
  return answer.trim()
}
