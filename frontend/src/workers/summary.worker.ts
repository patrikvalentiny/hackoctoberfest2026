import { env, pipeline, type TextGenerationPipeline } from '@huggingface/transformers'
import type { ForecastHour } from '@/lib/weather'

type SummaryRequest = {
  requestId: number
  hours: ForecastHour[]
}

type WorkerMessage =
  | { requestId: number; type: 'status'; message: string }
  | { requestId: number; type: 'progress'; progress: number }
  | { requestId: number; type: 'summary'; text: string }
  | { requestId: number; type: 'error'; message: string }

const modelId = 'onnx-community/Qwen3-0.6B-ONNX'
let generator: TextGenerationPipeline | undefined

function send(message: WorkerMessage) {
  self.postMessage(message)
}

async function loadModel(requestId: number): Promise<TextGenerationPipeline> {
  if (generator) return generator

  env.useBrowserCache = true
  env.useWasmCache = true
  const useWebGpu = 'gpu' in navigator
  send({
    requestId,
    type: 'status',
    message: 'Loading the local model. First use downloads model files.',
  })
  generator = await pipeline('text-generation', modelId, {
    dtype: useWebGpu ? 'q4f16' : 'q4',
    device: useWebGpu ? 'webgpu' : 'wasm',
    progress_callback: (progress) => {
      if (progress.status === 'progress_total') {
        send({
          requestId,
          type: 'progress',
          progress: Math.round(progress.progress),
        })
      }
    },
  })
  return generator
}

self.addEventListener('message', (event: MessageEvent<SummaryRequest>) => {
  void (async () => {
    const requestId = event.data.requestId
    try {
      const model = await loadModel(requestId)
      send({ requestId, type: 'status', message: 'Summarizing forecast locally.' })
      const rows = event.data.hours.slice(0, 24).filter((_, index) => index % 3 === 0)
      const forecastData = rows
        .map(
          (hour) =>
            `${hour.time}: wind ${hour.wind_speed_kn ?? 'n/a'} kn, gusts ${hour.wind_gusts_kn ?? 'n/a'} kn, waves ${hour.wave_height_m ?? 'n/a'} m, period ${hour.wave_period_s ?? 'n/a'} s, visibility ${hour.visibility_m ?? 'n/a'} m, precipitation chance ${hour.precipitation_probability_pct ?? 'n/a'}%.`,
        )
        .join('\n')
      const result = await model(
        [
          {
            role: 'system',
            content:
              'Summarize only the supplied offshore weather forecast facts in plain, concise language. Identify the largest supplied wave and gust values and when they occur if clear. Do not invent values, extrapolate, or recommend whether an operation is safe. State that the forecast is advisory and must be checked against approved procedures.',
          },
          {
            role: 'user',
            content: `Summarize these hourly values. All timestamps are UTC. Missing values are shown as n/a.\n${forecastData}`,
          },
        ],
        { max_new_tokens: 180, do_sample: false },
      )
      const chat = result[0]?.generated_text
      const text = Array.isArray(chat) ? chat.at(-1)?.content : undefined
      if (typeof text !== 'string' || !text.trim()) {
        throw new Error('The local model returned an empty summary.')
      }
      send({ requestId, type: 'summary', text: text.trim() })
    } catch (error) {
      send({
        requestId,
        type: 'error',
        message:
          error instanceof Error ? error.message : 'The local summary could not be generated.',
      })
    }
  })()
})
