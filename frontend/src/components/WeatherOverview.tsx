import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'
import { ArrowClockwise, CloudSun, DownloadSimple, Sparkle, Waves, Wind } from '@phosphor-icons/react'
import type { CachedForecast, ForecastHour, SiteProfile } from '@/lib/weather'
import type { SiteId } from '@/lib/planner'
import { downloadOfflineForecast, OFFLINE_FORECAST_HOURS, readOfflineForecast } from '@/lib/offline-forecast'
import { generateLocalSummary } from '@/lib/local-ai'
import { TIME_ZONE } from '@/lib/format'
import { Button } from '@/components/ui/button'

function DailyMetric({
  icon,
  label,
  value: reading,
}: {
  icon: ReactNode
  label: string
  value: string
}) {
  return (
    <div className="rounded-md border bg-card px-3 py-2.5">
      <p className="flex items-center gap-2 text-[0.7rem] text-muted-foreground">{icon}{label}</p>
      <p className="mt-1 font-display text-base font-semibold tabular-nums">{reading}</p>
    </div>
  )
}

function localDate(timestamp: string | number) {
  return new Intl.DateTimeFormat('en-CA', { timeZone: TIME_ZONE }).format(new Date(timestamp))
}

function hourLabel(timestamp: string) {
  return new Intl.DateTimeFormat('en-GB', {
    timeZone: TIME_ZONE,
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date(timestamp))
}

function dailyHours(entry: CachedForecast, date: string, now: number) {
  const today = localDate(now)
  return entry.forecast.hours.filter((hour) => {
    if (localDate(hour.time) !== date) return false
    return date !== today || new Date(hour.time).getTime() + 60 * 60 * 1000 > now
  })
}

function rangeOf(values: (number | null)[]) {
  const valid = values.filter((value): value is number => value !== null)
  return valid.length ? { min: Math.min(...valid), max: Math.max(...valid) } : undefined
}

function summaryPrompt(
  siteName: string,
  date: string,
  hours: ForecastHour[],
) {
  const table = hours.map((hour) => ({
    time_local: hourLabel(hour.time),
    wind_10m_kn: hour.wind_speed_kn,
    gust_10m_kn: hour.wind_gusts_kn,
    significant_waves_m: hour.wave_height_m,
    wave_period_s: hour.wave_period_s,
    visibility_m: hour.visibility_m,
    precipitation_probability_pct: hour.precipitation_probability_pct,
  }))
  return [
    `Summarize this hourly forecast for ${siteName} on ${date}.`,
    'Write 2–4 short sentences: overall conditions and the timing of any meaningful changes.',
    'Summarize only the supplied forecast hours. If coverage is partial, say so and do not imply these are all 24 hours.',
    'Mention weather factors that may affect vessel access or maintenance, but do not invent operating thresholds or claim a threshold crossing.',
    'Wind readings are at 10 m and must not be compared to any 100 m work limit.',
    'Do not make a go/no-go decision. State that this is a forecast, not an observation.',
    JSON.stringify({ hourly_forecast: table }),
  ].join('\n')
}

export function WeatherOverview({
  site,
  siteId: suppliedSiteId,
  online,
  now,
  wallNow,
  selectedDate,
  demoTimeActive = false,
  onForecastEntry,
}: {
  site: SiteProfile & { id: SiteId }
  siteId?: SiteId
  online: boolean
  now: number
  wallNow: number
  selectedDate: string
  demoTimeActive?: boolean
  onForecastEntry?: (entry: CachedForecast | undefined) => void
}) {
  const siteId = suppliedSiteId ?? site.id
  const [offlineForecast, setOfflineForecast] = useState<CachedForecast>()
  const [forecastLoading, setForecastLoading] = useState(false)
  const [forecastError, setForecastError] = useState('')
  const [summary, setSummary] = useState<{ date: string; text: string }>()
  const [summaryError, setSummaryError] = useState('')
  const [summaryProgress, setSummaryProgress] = useState('')
  const [summaryBusy, setSummaryBusy] = useState(false)

  const todaysHours = useMemo(
    () => (offlineForecast ? dailyHours(offlineForecast, selectedDate, now) : []),
    [offlineForecast, now, selectedDate],
  )
  const windRange = useMemo(() => rangeOf(todaysHours.map((hour) => hour.wind_speed_kn)), [todaysHours])
  const gustRange = useMemo(() => rangeOf(todaysHours.map((hour) => hour.wind_gusts_kn)), [todaysHours])
  const waveRange = useMemo(() => rangeOf(todaysHours.map((hour) => hour.wave_height_m)), [todaysHours])
  const visibilityRange = useMemo(() => rangeOf(todaysHours.map((hour) => hour.visibility_m)), [todaysHours])

  useEffect(() => {
    onForecastEntry?.(offlineForecast)
  }, [offlineForecast, onForecastEntry])

  const refreshOfflineForecast = useCallback(async () => {
    if (!online) {
      setForecastError('Connect to download or refresh the next 3 days of hourly forecast data.')
      return
    }
    setForecastLoading(true)
    setForecastError('')
    try {
      const saved = await downloadOfflineForecast(siteId, site)
      setOfflineForecast(saved)
    } catch (failure) {
      setForecastError(failure instanceof Error ? failure.message : 'The 3-day forecast could not be downloaded.')
    } finally {
      setForecastLoading(false)
    }
  }, [online, site, siteId])

  useEffect(() => {
    let active = true
    async function prepareForecast() {
      setForecastError('')
      let saved: CachedForecast | undefined
      try {
        saved = await readOfflineForecast(siteId)
        if (active && saved) setOfflineForecast(saved)
        if (!online) {
          if (active && !saved) setForecastError('No 3-day forecast is saved on this device yet.')
          return
        }
        if (active) setForecastLoading(true)
        const downloaded = await downloadOfflineForecast(siteId, site)
        if (active) setOfflineForecast(downloaded)
      } catch (failure) {
        if (active) {
          const detail = failure instanceof Error ? failure.message : 'The forecast could not be refreshed.'
          setForecastError(
            saved
              ? `Refresh failed; the saved forecast is still available. ${detail}`
              : detail,
          )
        }
      } finally {
        if (active) setForecastLoading(false)
      }
    }
    void prepareForecast()
    return () => {
      active = false
    }
  }, [online, site, siteId])

  async function createSummary() {
    setSummaryError('')
    setSummaryBusy(true)
    setSummaryProgress('Starting the browser model…')
    try {
      let entry = offlineForecast
      if (!entry || !entry.forecast.hours.length) {
        if (!online) throw new Error('Download a 3-day forecast while connected before using the local summary.')
        entry = await downloadOfflineForecast(siteId, site)
        setOfflineForecast(entry)
      }
      if (wallNow - new Date(entry.forecast.fetched_at).getTime() > OFFLINE_FORECAST_HOURS * 60 * 60 * 1000) {
        throw new Error('The saved forecast is over 72 hours old. Reconnect and refresh it before generating a summary.')
      }
      const hours = dailyHours(entry, selectedDate, now)
      if (hours.length === 0) {
        throw new Error(`The saved forecast has no hourly data for ${selectedDate}. Refresh the 3-day forecast.`)
      }
      const result = await generateLocalSummary(
        summaryPrompt(site.name, selectedDate, hours),
        (progress) => {
          const percentage = Math.round(progress.progress * 100)
          setSummaryProgress(
            progress.progress < 1
              ? `${progress.text} ${percentage}%`
              : 'Local model ready; writing the daily summary…',
          )
        },
      )
      setSummary({ date: selectedDate, text: result })
      setSummaryProgress('')
    } catch (failure) {
      setSummaryError(failure instanceof Error ? failure.message : 'The local summary could not be generated.')
    } finally {
      setSummaryBusy(false)
    }
  }

  const savedHours = offlineForecast?.forecast.hours.length ?? 0
  const cachedAt = offlineForecast
    ? new Intl.DateTimeFormat('en-GB', { timeZone: TIME_ZONE, hour: '2-digit', minute: '2-digit' }).format(
        new Date(offlineForecast.saved_at),
      )
    : undefined
  const oldForecast = offlineForecast
    ? wallNow - new Date(offlineForecast.forecast.fetched_at).getTime() > OFFLINE_FORECAST_HOURS * 60 * 60 * 1000
    : false
  const outlookTitle = todaysHours.length === 24
    ? 'Full-day outlook'
    : selectedDate === localDate(now)
      ? 'Remaining-day outlook'
      : 'Partial-day outlook'

  return (
    <section aria-labelledby="weather-overview-title" className="weather-overview rounded-xl border bg-card p-4 sm:p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex items-center gap-3">
          <span className="grid size-10 place-items-center rounded-md bg-secondary text-primary">
            <CloudSun className="size-6" aria-hidden />
          </span>
          <div>
            <h2 id="weather-overview-title" className="font-display text-lg font-semibold">
              Weather window
            </h2>
            <p className="text-sm text-muted-foreground">
              {demoTimeActive
                ? `Local forecast for ${selectedDate} · demo clock moves the task timeline`
                : `Hourly forecast for ${selectedDate}`}
            </p>
          </div>
        </div>
      </div>

      <section aria-labelledby="daily-outlook-title" className="daily-outlook mt-4 rounded-md border border-primary/20 bg-secondary/40 p-3 sm:p-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <p className="text-xs font-semibold tracking-wide text-primary uppercase">Local forecast · {selectedDate}</p>
            <h3 id="daily-outlook-title" className="mt-1 font-display text-base font-semibold">
              {outlookTitle}
            </h3>
            <p className="mt-1 text-xs text-muted-foreground">
              {todaysHours.length
                ? `${todaysHours.length} hourly points · ${savedHours} points saved for up to 72 hours`
                : 'Download up to 72 hours of hourly data for this device.'}
              {todaysHours.length > 0 && todaysHours.length < 24
                ? ` · partial coverage (${todaysHours.length} of 24 hours)`
                : ''}
              {cachedAt ? ` · saved ${cachedAt}` : ''}
              {oldForecast ? ' · forecast is over 72 hours old' : ''}
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button
              type="button"
              size="sm"
              variant="outline"
              onClick={() => void refreshOfflineForecast()}
              disabled={!online || forecastLoading}
              aria-label="Download or refresh the next 3 days for offline use"
            >
              {forecastLoading ? (
                <ArrowClockwise className="size-4 animate-spin" aria-hidden />
              ) : (
                <DownloadSimple className="size-4" aria-hidden />
              )}
              {offlineForecast ? 'Refresh 3-day data' : 'Download 3-day data'}
            </Button>
            <Button
              type="button"
              size="sm"
              onClick={() => void createSummary()}
              disabled={summaryBusy || forecastLoading}
              aria-label="Generate a daily summary with the local browser model"
            >
              <Sparkle className="size-4" aria-hidden />
              {summaryBusy ? 'Preparing local AI…' : 'Summarize locally'}
            </Button>
          </div>
        </div>

        <p className="mt-2 text-xs text-muted-foreground">
          First use downloads the model. WebGPU is required; summary inference runs in this browser.
        </p>
        {summaryProgress && (
          <p role="status" className="mt-3 text-xs text-muted-foreground">
            {summaryProgress}
          </p>
        )}
        {summaryError && (
          <p role="alert" className="mt-3 rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-destructive">
            {summaryError}
          </p>
        )}
        {forecastError && (
          <p role="status" className="mt-3 text-xs text-muted-foreground">
            {forecastError}
          </p>
        )}
        {summary?.date === selectedDate && (
          <div className="mt-3 border-t border-primary/15 pt-3" aria-live="polite">
            <p className="text-xs font-semibold text-primary">Local AI summary</p>
            <p className="mt-1 text-sm leading-relaxed">{summary.text}</p>
          </div>
        )}

        {todaysHours.length > 0 && (
          <div className="mt-3 border-t border-primary/15 pt-3">
            <h4 className="text-xs font-semibold">Weather factors to review</h4>
            <ul className="mt-1 grid gap-1 text-xs text-muted-foreground">
              <li>
                Transfer access: {waveRange
                  ? `significant waves ${waveRange.min.toFixed(1)}–${waveRange.max.toFixed(1)} m;`
                  : 'wave data unavailable;'} compare with vessel and site transfer limits.
              </li>
              <li>
                Work at height and lifts: {windRange
                  ? `10 m wind ${windRange.min.toFixed(0)}–${windRange.max.toFixed(0)} kn${gustRange ? `, gusts to ${gustRange.max.toFixed(0)} kn` : ''};`
                  : 'wind data unavailable;'} check turbine-height/task-specific limits.
              </li>
              <li>
                Access and visibility: {visibilityRange
                  ? `${(visibilityRange.min / 1000).toFixed(1)}–${(visibilityRange.max / 1000).toFixed(1)} km forecast;`
                  : 'visibility data unavailable;'} follow vessel procedures.
              </li>
              <li>Lightning is not part of this offline hourly forecast; use live site alerts and radio procedures.</li>
            </ul>
            <p className="mt-2 text-[0.7rem] text-muted-foreground">
              Forecast only, not observations. Lightning and other site procedures are not covered by this summary.
            </p>
          </div>
        )}
      </section>

      {todaysHours.length > 0 && (
        <div className="mt-4 grid grid-cols-2 gap-2 sm:grid-cols-4">
          <DailyMetric label="Wind · 10 m" value={windRange ? `${windRange.min.toFixed(0)}–${windRange.max.toFixed(0)} kn` : 'No data'} icon={<Wind aria-hidden />} />
          <DailyMetric label="Gusts · 10 m" value={gustRange ? `${gustRange.max.toFixed(0)} kn peak` : 'No data'} icon={<Wind aria-hidden />} />
          <DailyMetric label="Significant waves" value={waveRange ? `${waveRange.min.toFixed(1)}–${waveRange.max.toFixed(1)} m` : 'No data'} icon={<Waves aria-hidden />} />
          <DailyMetric label="Visibility" value={visibilityRange ? `${(visibilityRange.min / 1000).toFixed(1)}–${(visibilityRange.max / 1000).toFixed(1)} km` : 'No data'} icon={<CloudSun aria-hidden />} />
        </div>
      )}

      <p className="mt-3 text-xs text-muted-foreground">
        Forecast values are not observations. Wind readings are at 10 m; they are not turbine-height values.
      </p>
    </section>
  )
}
