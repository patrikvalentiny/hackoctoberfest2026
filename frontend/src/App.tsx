import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  Anchor,
  ArrowClockwise,
  Brain,
  CheckCircle,
  CloudArrowDown,
  Compass,
  DownloadSimple,
  MapPin,
  Warning,
  WaveSine,
  WifiHigh,
  WifiSlash,
  Wind,
} from '@phosphor-icons/react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import { readForecast, readSavedStation, saveForecast, saveStation } from '@/lib/forecast-cache'
import { fetchForecast, formatNumber, formatUtcTime, siteKey } from '@/lib/weather'
import type { CachedForecast, SiteProfile, WeatherForecast } from '@/lib/weather'

type SummaryState = 'idle' | 'loading' | 'summarizing' | 'ready' | 'error'

type SummaryWorkerMessage =
  | { requestId: number; type: 'status'; message: string }
  | { requestId: number; type: 'progress'; progress: number }
  | { requestId: number; type: 'summary'; text: string }
  | { requestId: number; type: 'error'; message: string }

function messageFrom(error: unknown) {
  return error instanceof Error ? error.message : 'Something went wrong.'
}

function loadInitialStation() {
  try {
    return { station: readSavedStation(), error: '' }
  } catch (error) {
    return { station: undefined, error: messageFrom(error) }
  }
}

function formatSavedAt(value: string) {
  return new Intl.DateTimeFormat('en-GB', {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(new Date(value))
}

function App() {
  const [initialStation] = useState(loadInitialStation)
  const [site, setSite] = useState<SiteProfile | undefined>(initialStation.station)
  const [name, setName] = useState(initialStation.station?.name ?? '')
  const [latitude, setLatitude] = useState(
    initialStation.station ? String(initialStation.station.latitude) : '',
  )
  const [longitude, setLongitude] = useState(
    initialStation.station ? String(initialStation.station.longitude) : '',
  )
  const [forecast, setForecast] = useState<WeatherForecast>()
  const [savedAt, setSavedAt] = useState<string>()
  const [online, setOnline] = useState(navigator.onLine)
  const [fetching, setFetching] = useState(false)
  const [error, setError] = useState(initialStation.error)
  const [summary, setSummary] = useState('')
  const [summaryState, setSummaryState] = useState<SummaryState>('idle')
  const [summaryMessage, setSummaryMessage] = useState('')
  const [modelProgress, setModelProgress] = useState<number>()
  const workerRef = useRef<Worker | null>(null)
  const summaryRequestId = useRef(0)

  const loadForecast = useCallback(async (profile: SiteProfile) => {
    setFetching(true)
    setError('')
    setSummary('')
    setSummaryState('idle')
    setSummaryMessage('')
    summaryRequestId.current += 1

    try {
      const nextForecast = await fetchForecast(profile)
      setForecast(nextForecast)
      const saved = new Date().toISOString()
      setSavedAt(saved)

      try {
        await saveForecast({
          key: siteKey(profile),
          saved_at: saved,
          forecast: nextForecast,
        })
      } catch {
        setError('Forecast updated, but this device could not save an offline copy.')
      }
    } catch (requestError) {
      if (requestError instanceof TypeError) {
        setOnline(false)
        setError('Could not reach the forecast service. Showing any saved forecast.')
      } else {
        setError(messageFrom(requestError))
      }
    } finally {
      setFetching(false)
    }
  }, [])

  useEffect(() => {
    const updateConnection = () => setOnline(navigator.onLine)
    window.addEventListener('online', updateConnection)
    window.addEventListener('offline', updateConnection)

    return () => {
      window.removeEventListener('online', updateConnection)
      window.removeEventListener('offline', updateConnection)
    }
  }, [])

  useEffect(() => {
    if (!site) return
    let cancelled = false

    void (async () => {
      try {
        const cached: CachedForecast | undefined = await readForecast(site)
        if (cancelled) return
        if (cached) {
          setForecast(cached.forecast)
          setSavedAt(cached.saved_at)
        } else {
          setForecast(undefined)
          setSavedAt(undefined)
        }
        if (online) await loadForecast(site)
        else if (!cached) setError('No saved forecast for this site. Connect to download one first.')
      } catch (cacheError) {
        if (!cancelled) setError(messageFrom(cacheError))
      }
    })()

    return () => {
      cancelled = true
    }
  }, [loadForecast, online, site])

  useEffect(() => {
    const worker = new Worker(new URL('./workers/summary.worker.ts', import.meta.url), {
      type: 'module',
    })
    workerRef.current = worker
    worker.addEventListener('message', (event: MessageEvent<SummaryWorkerMessage>) => {
      const message = event.data
      if (message.requestId !== summaryRequestId.current) return

      if (message.type === 'status') {
        setSummaryMessage(message.message)
        setSummaryState(
          message.message.startsWith('Summarizing') ? 'summarizing' : 'loading',
        )
      } else if (message.type === 'progress') {
        setModelProgress(message.progress)
      } else if (message.type === 'summary') {
        setSummary(message.text)
        setSummaryMessage('')
        setSummaryState('ready')
      } else {
        setSummaryMessage(message.message)
        setSummaryState('error')
      }
    })
    worker.addEventListener('error', (event) => {
      setSummaryMessage(event.message || 'The local model worker stopped unexpectedly.')
      setSummaryState('error')
    })
    return () => {
      worker.terminate()
      workerRef.current = null
    }
  }, [])

  function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const profile: SiteProfile = {
      name: name.trim(),
      latitude: Number(latitude),
      longitude: Number(longitude),
    }
    if (!profile.name || !Number.isFinite(profile.latitude) || !Number.isFinite(profile.longitude)) {
      setError('Enter a station name and valid coordinates.')
      return
    }

    try {
      saveStation(profile)
      setSite(profile)
      setError('')
      setSummary('')
      setSummaryState('idle')
      setSummaryMessage('')
    } catch (storageError) {
      setError(messageFrom(storageError))
    }
  }

  function summarizeLocally() {
    if (!forecast || !workerRef.current) return
    const requestId = summaryRequestId.current + 1
    summaryRequestId.current = requestId
    setSummary('')
    setSummaryState('loading')
    setSummaryMessage(
      online
        ? 'Preparing a local model. First use downloads model files.'
        : 'Looking for the model files saved on this device.',
    )
    setModelProgress(undefined)
    workerRef.current.postMessage({ requestId, hours: forecast.hours })
  }

  const outlook = useMemo(
    () => forecast?.hours.slice(0, 25).filter((_, index) => index % 4 === 0) ?? [],
    [forecast],
  )
  const maxWave = Math.max(0, ...outlook.map((hour) => hour.wave_height_m ?? 0))
  const latest = forecast?.hours[0]

  return (
    <div className="min-h-dvh bg-background text-foreground">
      <header className="border-b border-border/80">
        <div className="mx-auto flex min-h-16 max-w-7xl items-center justify-between gap-4 px-4 sm:px-8">
          <div className="flex items-center gap-3">
            <div className="flex size-9 items-center justify-center rounded-lg bg-primary text-primary-foreground">
              <Anchor aria-hidden="true" size={19} weight="bold" />
            </div>
            <div>
              <p className="font-semibold tracking-tight">Offshore Weather</p>
              <p className="text-xs text-muted-foreground">Field forecast brief</p>
            </div>
          </div>
          <Badge variant={online ? 'secondary' : 'outline'} className="gap-1.5">
            {online ? (
              <WifiHigh aria-hidden="true" size={14} />
            ) : (
              <WifiSlash aria-hidden="true" size={14} />
            )}
            {online ? 'Online' : 'Offline'}
          </Badge>
        </div>
      </header>

      <main className="mx-auto grid max-w-7xl gap-8 px-4 py-8 sm:px-8 lg:grid-cols-[minmax(0,1fr)_20rem] lg:gap-12 lg:py-12">
        <div className="min-w-0">
          <div className="mb-8 flex flex-wrap items-end justify-between gap-4">
            <div>
              <p className="mb-2 flex items-center gap-2 text-sm text-muted-foreground">
                <Compass aria-hidden="true" size={17} />
                Offshore conditions
              </p>
              <h1 className="text-3xl font-semibold tracking-tight sm:text-4xl">
                {site?.name || 'Weather brief'}
              </h1>
              <p className="mt-2 text-sm text-muted-foreground">
                {forecast
                  ? `Forecast times in UTC. Data fetched ${formatSavedAt(forecast.fetched_at)}.`
                  : 'Choose a site to load its marine forecast.'}
              </p>
            </div>
            {site && (
              <Button
                onClick={() => void loadForecast(site)}
                disabled={fetching || !online}
                variant="outline"
              >
                <ArrowClockwise
                  aria-hidden="true"
                  className={fetching ? 'animate-spin' : ''}
                  size={17}
                />
                Refresh forecast
              </Button>
            )}
          </div>

          {error && (
            <div
              role="alert"
              className="mb-6 flex items-start gap-3 rounded-lg border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive"
            >
              <Warning aria-hidden="true" className="mt-0.5 shrink-0" size={18} />
              <p>{error}</p>
            </div>
          )}

          {!online && forecast && (
            <div className="mb-6 flex items-start gap-3 rounded-lg border border-border bg-muted/60 p-4 text-sm">
              <CloudArrowDown
                aria-hidden="true"
                className="mt-0.5 shrink-0 text-primary"
                size={18}
              />
              <div>
                <p className="font-medium">Showing a saved forecast</p>
                <p className="mt-1 text-muted-foreground">
                  Saved {savedAt ? formatSavedAt(savedAt) : 'on this device'}. Forecasts
                  can become stale; verify conditions before use.
                </p>
              </div>
            </div>
          )}

          {fetching && !forecast && (
            <div
              aria-label="Loading forecast"
              className="mb-8 grid gap-3 sm:grid-cols-2"
            >
              {[0, 1, 2, 3].map((item) => (
                <div
                  key={item}
                  className="h-28 animate-pulse rounded-lg border border-border bg-muted/50"
                />
              ))}
            </div>
          )}

          {forecast && latest ? (
            <div className="space-y-8">
              <section aria-labelledby="conditions-heading">
                <div className="mb-4 flex items-center justify-between">
                  <h2 id="conditions-heading" className="text-lg font-semibold">
                    Marine conditions
                  </h2>
                  <span className="text-sm text-muted-foreground">
                    {formatUtcTime(latest.time)} UTC
                  </span>
                </div>
                <Card className="rounded-xl shadow-none">
                  <CardContent className="grid grid-cols-2 gap-x-6 gap-y-7 p-5 sm:grid-cols-4 sm:p-6">
                    <Metric
                      icon={<WaveSine aria-hidden="true" size={19} />}
                      label="Wave height"
                      value={formatNumber(latest.wave_height_m)}
                      unit="m"
                    />
                    <Metric
                      icon={<WaveSine aria-hidden="true" size={19} />}
                      label="Wave period"
                      value={formatNumber(latest.wave_period_s)}
                      unit="s"
                    />
                    <Metric
                      icon={<Wind aria-hidden="true" size={19} />}
                      label="Wind"
                      value={formatNumber(latest.wind_speed_kn)}
                      unit="kn"
                    />
                    <Metric
                      icon={<Wind aria-hidden="true" size={19} />}
                      label="Wind gusts"
                      value={formatNumber(latest.wind_gusts_kn)}
                      unit="kn"
                    />
                  </CardContent>
                </Card>
                <p className="mt-3 text-xs leading-relaxed text-muted-foreground">
                  Forecast guidance only. It does not determine whether an offshore
                  operation is safe. Follow approved procedures and current site
                  limits.
                </p>
              </section>

              <section aria-labelledby="outlook-heading">
                <div className="mb-4 flex items-center justify-between gap-4">
                  <h2 id="outlook-heading" className="text-lg font-semibold">
                    Next 24 hours
                  </h2>
                  <span className="text-sm text-muted-foreground">
                    Wave height, metres
                  </span>
                </div>
                <Card className="rounded-xl shadow-none">
                  <CardContent className="grid grid-cols-3 gap-x-3 gap-y-6 p-5 sm:grid-cols-6 sm:gap-5 sm:p-6">
                    {outlook.map((hour) => {
                      const height = hour.wave_height_m ?? 0
                      const barHeight = maxWave > 0 ? Math.max(4, (height / maxWave) * 76) : 4
                      return (
                        <div
                          key={hour.time}
                          className="flex min-w-0 flex-col items-center gap-2"
                        >
                          <span className="text-xs text-muted-foreground">
                            {formatUtcTime(hour.time)}
                          </span>
                          <div
                            role="img"
                            aria-label={`${formatUtcTime(hour.time)} UTC: ${formatNumber(hour.wave_height_m)} metres`}
                            className="flex h-20 w-8 items-end overflow-hidden rounded-sm bg-muted"
                          >
                            <div
                              className="w-full bg-primary"
                              style={{ height: `${barHeight}px` }}
                            />
                          </div>
                          <span className="text-sm font-medium">
                            {formatNumber(hour.wave_height_m)}
                          </span>
                          <span className="text-xs text-muted-foreground">
                            {formatNumber(hour.wind_speed_kn, 0)} kn wind
                          </span>
                        </div>
                      )
                    })}
                    {outlook.length === 0 && (
                      <p className="col-span-full text-sm text-muted-foreground">
                        No hourly outlook is available in this saved forecast.
                      </p>
                    )}
                  </CardContent>
                </Card>
              </section>

              <section aria-labelledby="summary-heading">
                <div className="mb-4 flex items-center gap-2">
                  <Brain aria-hidden="true" className="text-primary" size={19} />
                  <h2 id="summary-heading" className="text-lg font-semibold">
                    On-device summary
                  </h2>
                </div>
                <Card className="rounded-xl shadow-none">
                  <CardHeader className="pb-0">
                    <CardTitle className="text-sm font-medium">
                      Qwen 3 0.6B runs in this browser
                    </CardTitle>
                  </CardHeader>
                  <CardContent className="space-y-4 p-5 pt-3 sm:p-6 sm:pt-3">
                    {summary ? (
                      <p aria-live="polite" className="text-sm leading-relaxed">
                        {summary}
                      </p>
                    ) : (
                      <p aria-live="polite" className="text-sm leading-relaxed text-muted-foreground">
                        {summaryMessage ||
                          'The local model summarizes downloaded or saved forecast data. It does not create weather forecasts.'}
                      </p>
                    )}
                    {modelProgress !== undefined && summaryState === 'loading' && (
                      <p className="text-xs text-muted-foreground">
                        Model files: {modelProgress}% loaded
                      </p>
                    )}
                    <Button
                      onClick={summarizeLocally}
                      disabled={
                        summaryState === 'loading' ||
                        summaryState === 'summarizing' ||
                        !forecast
                      }
                    >
                      {summaryState === 'ready' ? (
                        <CheckCircle aria-hidden="true" size={17} />
                      ) : summaryState === 'loading' ||
                        summaryState === 'summarizing' ? (
                        <ArrowClockwise
                          aria-hidden="true"
                          className="animate-spin"
                          size={17}
                        />
                      ) : (
                        <Brain aria-hidden="true" size={17} />
                      )}
                      {summaryState === 'ready' ? 'Refresh summary' : 'Summarize locally'}
                    </Button>
                    <p className="text-xs leading-relaxed text-muted-foreground">
                      First use needs internet to cache model files. Once cached, model
                      summaries can run offline in this browser. Browser storage may be
                      cleared by the device.
                    </p>
                  </CardContent>
                </Card>
              </section>

              <p className="text-xs text-muted-foreground">
                Source:{' '}
                <a
                  className="underline underline-offset-4"
                  href={forecast.source_url}
                  rel="noreferrer"
                  target="_blank"
                >
                  {forecast.source}
                </a>
                . Confirm conditions with approved marine forecasts and site procedures.
              </p>
            </div>
          ) : !fetching ? (
            <div className="flex min-h-64 flex-col items-center justify-center rounded-xl border border-dashed border-border px-6 text-center">
              <CloudArrowDown
                aria-hidden="true"
                className="mb-4 text-muted-foreground"
                size={28}
              />
              <p className="font-medium">No forecast loaded</p>
              <p className="mt-2 max-w-sm text-sm text-muted-foreground">
                Enter a named offshore site and coordinates. Download a forecast while
                connected to keep a local copy for later.
              </p>
            </div>
          ) : null}
        </div>

        <aside className="space-y-6 lg:pt-1">
          <Card className="rounded-xl shadow-none">
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-base">
                <MapPin aria-hidden="true" className="text-primary" size={18} />
                Forecast location
              </CardTitle>
            </CardHeader>
            <CardContent>
              <form className="space-y-4" onSubmit={(event) => void handleSubmit(event)}>
                <Field
                  id="site-name"
                  label="Site name"
                  onChange={setName}
                  placeholder="For example, North Sea platform"
                  required
                  value={name}
                />
                <div className="grid grid-cols-2 gap-3">
                  <Field
                    id="latitude"
                    label="Latitude"
                    max="90"
                    min="-90"
                    onChange={setLatitude}
                    placeholder="56.0"
                    required
                    step="any"
                    type="number"
                    value={latitude}
                  />
                  <Field
                    id="longitude"
                    label="Longitude"
                    max="180"
                    min="-180"
                    onChange={setLongitude}
                    placeholder="2.0"
                    required
                    step="any"
                    type="number"
                    value={longitude}
                  />
                </div>
                <Button className="w-full" disabled={fetching} type="submit">
                  <DownloadSimple aria-hidden="true" size={17} />
                  {fetching ? 'Loading forecast' : 'Load forecast'}
                </Button>
              </form>
              <p className="mt-4 text-xs leading-relaxed text-muted-foreground">
                Coordinates are sent to Open-Meteo to retrieve weather and wave model
                data. Check provider coverage for the selected location.
              </p>
            </CardContent>
          </Card>

          <div className="rounded-xl border border-border bg-muted/50 p-5">
            <h2 className="flex items-center gap-2 text-sm font-semibold">
              <CloudArrowDown aria-hidden="true" className="text-primary" size={17} />
              Offline readiness
            </h2>
            <p className="mt-2 text-sm leading-relaxed text-muted-foreground">
              The app shell and saved forecasts stay on this device. Refresh forecasts
              and load the local model before leaving connectivity.
            </p>
            <p className="mt-3 text-xs text-muted-foreground">
              {savedAt
                ? `Saved forecast: ${formatSavedAt(savedAt)}`
                : 'No forecast saved for this site yet.'}
            </p>
          </div>
        </aside>
      </main>
    </div>
  )
}

function Metric({
  icon,
  label,
  value,
  unit,
}: {
  icon: React.ReactNode
  label: string
  value: string
  unit: string
}) {
  return (
    <div className="min-w-0">
      <div className="mb-3 flex items-center gap-2 text-muted-foreground">
        {icon}
        <span className="text-xs sm:text-sm">{label}</span>
      </div>
      <p className="truncate text-2xl font-semibold tracking-tight sm:text-3xl">
        {value}
        <span className="ml-1 text-sm font-normal text-muted-foreground">{unit}</span>
      </p>
    </div>
  )
}

function Field({
  id,
  label,
  onChange,
  ...props
}: {
  id: string
  label: string
  onChange: (value: string) => void
  value: string
  type?: string
  min?: string
  max?: string
  step?: string
  placeholder?: string
  required?: boolean
}) {
  return (
    <div className="space-y-2">
      <label className="text-sm font-medium" htmlFor={id}>
        {label}
      </label>
      <input
        {...props}
        className="flex h-10 w-full min-w-0 rounded-lg border border-input bg-background px-3 text-sm text-foreground shadow-sm outline-none transition-colors placeholder:text-muted-foreground focus-visible:ring-2 focus-visible:ring-ring"
        id={id}
        onChange={(event) => onChange(event.target.value)}
      />
    </div>
  )
}

export default App
