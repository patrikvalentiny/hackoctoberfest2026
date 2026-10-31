import type { InitProgressReport, MLCEngineInterface } from '@mlc-ai/web-llm'

const modelId = 'Llama-3.2-1B-Instruct-q4f16_1-MLC'

type ForecastPoint = {
  time?: string
  wind_10m_kn?: number | null
  gust_10m_kn?: number | null
  waves_m?: number | null
  wave_period_s?: number | null
  visibility_m?: number | null
  rain_probability_pct?: number | null
}

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

function parseForecastPoints(context: string): ForecastPoint[] {
  const match = /Hourly forecast points:\s*(\[[\s\S]*?\])\./.exec(context)
  if (!match) return []
  try {
    const parsed = JSON.parse(match[1])
    return Array.isArray(parsed) ? parsed.filter((entry) => typeof entry === 'object' && entry !== null) as ForecastPoint[] : []
  } catch {
    return []
  }
}

function safeNumber(value: number | null | undefined) {
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

function formatRange(numbers: Array<number | null | undefined>, digits = 0, unit = '') {
  const values = numbers.map((value) => safeNumber(value)).filter((value): value is number => value !== null)
  if (!values.length) return 'not available'
  const min = Math.min(...values)
  const max = Math.max(...values)
  const formattedMin = min.toFixed(digits)
  const formattedMax = max.toFixed(digits)
  return min === max ? `${formattedMin}${unit}` : `${formattedMin}–${formattedMax}${unit}`
}

function buildFallbackSummary(context: string): string {
  const points = parseForecastPoints(context)
  if (!points.length) {
    return 'The device has a saved forecast, but no hourly readings were found in the day briefing. Check the forecast cards and keep the crew briefed on the current conditions.'
  }

  const windValues = points.map((point) => point.wind_10m_kn)
  const gustValues = points.map((point) => point.gust_10m_kn)
  const waveValues = points.map((point) => point.waves_m)
  const visibilityValues = points.map((point) => point.visibility_m)
  const rainValues = points.map((point) => point.rain_probability_pct)

  const roughest = [...points]
    .filter((point) => safeNumber(point.gust_10m_kn) !== null || safeNumber(point.waves_m) !== null)
    .sort((a, b) => {
      const lhs = Math.max(safeNumber(a.gust_10m_kn) ?? 0, safeNumber(a.waves_m) ?? 0)
      const rhs = Math.max(safeNumber(b.gust_10m_kn) ?? 0, safeNumber(b.waves_m) ?? 0)
      return rhs - lhs
    })[0]

  const roughestText = roughest
    ? `The roughest spell is around ${roughest.time ?? 'the middle of the day'} with ${safeNumber(roughest.gust_10m_kn) !== null ? `${safeNumber(roughest.gust_10m_kn)?.toFixed(0)} kn gusts` : ''}${safeNumber(roughest.gust_10m_kn) !== null && safeNumber(roughest.waves_m) !== null ? ' and ' : ''}${safeNumber(roughest.waves_m) !== null ? `${safeNumber(roughest.waves_m)?.toFixed(1)} m waves` : ''}.`
    : 'There is no clear roughest period in the saved forecast.'

  const sentences = [
    `On-device review shows 10 m wind ${formatRange(windValues, 0, ' kn')}, waves ${formatRange(waveValues, 1, ' m')}, and visibility ${formatRange(visibilityValues, 0, ' m')}.`,
    `The day is likely to carry ${formatRange(rainValues, 0, '%')} rain chance at peak, with gusts to ${formatRange(gustValues, 0, ' kn')} across the period.`,
    roughestText,
  ]

  return sentences.join(' ')
}

function fallbackReply(messages: { role: 'user' | 'assistant'; content: string }[], context: string): string {
  const latest = [...messages].reverse().find((message) => message.role === 'user')?.content ?? 'What should I watch for?'
  const summary = buildFallbackSummary(context)
  if (/transfer|access|wave|sea|swell|lift|height/i.test(latest)) {
    return `${summary} Keep the crew focused on the saved forecast and site-approved limits; this is a forecast summary, not a go/no-go call.`
  }
  return `${summary} Check the exact values in the forecast cards before making any operational decision. The answer is based on the saved local forecast only.`
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
  try {
    return await generateLocalChatReply(
      [{ role: 'user', content: prompt }],
      'Summarize the supplied offshore forecast data. Be concise and factual.',
      onProgress,
      400,
    )
  } catch {
    return buildFallbackSummary(prompt)
  }
}

export async function generateLocalChatReply(
  messages: { role: 'user' | 'assistant'; content: string }[],
  context: string,
  onProgress: (progress: InitProgressReport) => void,
  maxTokens = 400,
): Promise<string> {
  if (!('gpu' in navigator)) {
    return fallbackReply(messages, context)
  }

  try {
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
      return fallbackReply(messages, context)
    }
    const text = dropRepeatedLines(answer.trim())
    return choice.finish_reason === 'length' ? endOnSentence(text) : text
  } catch {
    return fallbackReply(messages, context)
  }
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
