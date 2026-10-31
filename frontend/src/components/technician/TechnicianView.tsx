import { useCallback, useMemo, useState } from 'react'
import { ArrowLeft, ArrowRight, ChatCircleDots, Check, Clock, Compass, MapPin, Waves, Wind } from '@phosphor-icons/react'
import { ChatPanel } from '@/components/ChatPanel'
import { WeatherOverview } from '@/components/WeatherOverview'
import { cn } from '@/lib/utils'
import { TIME_ZONE, weekday, dayMonth } from '@/lib/format'
import type { CachedForecast } from '@/lib/weather'
import type { SiteId } from '@/lib/planner'
import {
  formatTaskForecast,
  taskForecastHours,
  taskWindowLabel,
  technicianTasks,
} from '@/lib/technician-tasks'

const sites = [
  { id: 'hr1', name: 'Horns Rev 1', short: 'HR1', latitude: 55.483, longitude: 7.833, port: 'Esbjerg' },
  { id: 'hr2', name: 'Horns Rev 2', short: 'HR2', latitude: 55.6, longitude: 7.583, port: 'Esbjerg' },
  { id: 'hr3', name: 'Horns Rev 3', short: 'HR3', latitude: 55.703, longitude: 7.689, port: 'Hvide Sande' },
] as const

const TASK_STATE_KEY = 'harbour-pulse:sample-task-state'
const SITE_KEY = 'harbour-pulse:technician-site'
const DATE_KEY = 'harbour-pulse:technician-date'

function localDate(timestamp: number) {
  return new Intl.DateTimeFormat('en-CA', { timeZone: TIME_ZONE }).format(new Date(timestamp))
}

function shiftDate(date: string, days: number) {
  const value = new Date(`${date}T12:00:00Z`)
  value.setUTCDate(value.getUTCDate() + days)
  return value.toISOString().slice(0, 10)
}

function localMinute(timestamp: number) {
  const parts = new Intl.DateTimeFormat('en-GB', {
    timeZone: TIME_ZONE,
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23',
  }).formatToParts(new Date(timestamp))
  return Number(parts.find((part) => part.type === 'hour')?.value) * 60
    + Number(parts.find((part) => part.type === 'minute')?.value)
}

function readSite(): SiteId {
  try {
    const saved = localStorage.getItem(SITE_KEY)
    const match = sites.find((site) => site.id === saved)
    if (match) return match.id
  } catch {
    // Use the PoC's default site when storage is unavailable.
  }
  return 'hr1'
}

function readSelectedDate(now: number) {
  try {
    const saved = localStorage.getItem(DATE_KEY)
    const today = localDate(now)
    if (saved && saved >= today && saved <= shiftDate(today, 2)) return saved
  } catch {
    // Start on the current local day when storage is unavailable.
  }
  return localDate(now)
}

function readTaskState(): Record<string, string[]> {
  try {
    const value: unknown = JSON.parse(localStorage.getItem(TASK_STATE_KEY) ?? '{}')
    if (!value || typeof value !== 'object' || Array.isArray(value)) return {}
    return Object.fromEntries(
      Object.entries(value).filter(
        (entry): entry is [string, string[]] =>
          Array.isArray(entry[1]) &&
          entry[1].every(
            (item): item is string =>
              typeof item === 'string' && technicianTasks.some((task) => task.id === item),
          ),
      ),
    )
  } catch {
    return {}
  }
}

function forecastContext(siteName: string, date: string, completed: string[], entry: CachedForecast | undefined) {
  const hours = entry?.forecast.hours.filter(
    (hour) => localDate(new Date(hour.time).getTime()) === date,
  ) ?? []
  const weather = hours.map((hour) => ({
    time: new Intl.DateTimeFormat('en-GB', { timeZone: TIME_ZONE, hour: '2-digit' }).format(new Date(hour.time)),
    wind_10m_kn: hour.wind_speed_kn,
    gust_10m_kn: hour.wind_gusts_kn,
    waves_m: hour.wave_height_m,
    wave_period_s: hour.wave_period_s,
    visibility_m: hour.visibility_m,
    rain_probability_pct: hour.precipitation_probability_pct,
  }))
  return [
    `Site: ${siteName}; work date: ${date}.`,
    `The plan is a PoC sample, not a work order: ${technicianTasks.map((task) => `${taskWindowLabel(task)} ${task.title} (${task.durationMinutes} min; watch ${task.weatherWatch})`).join('; ')}.`,
    `Tasks marked complete: ${completed.join(', ') || 'none'}.`,
    `Forecast coverage: ${weather.length} hourly points${weather.length < 24 ? ', partial day only' : ', full 24 hours'}.`,
    `Hourly forecast points: ${JSON.stringify(weather)}.`,
    'Forecast wind values are at 10 m, not turbine hub height. No lightning forecast is included.',
    'Explain possible effects on access, work at height, lifts, and schedule only when supported by the forecast. Never invent site limits or declare the work safe.',
  ].join('\n')
}

function taskState(task: (typeof technicianTasks)[number], date: string, today: string, now: number, done: boolean) {
  if (done) return 'Complete'
  if (date !== today) return 'Planned'
  const [hours, minutes] = task.time.split(':').map(Number)
  const start = hours * 60 + minutes
  const finish = start + task.durationMinutes
  const current = localMinute(now)
  if (current >= start && current < finish) return 'In progress'
  return current >= finish ? 'Next shift' : 'Upcoming'
}

export function TechnicianView({
  online,
  now,
  wallNow,
  demoTimeActive,
}: {
  online: boolean
  now: number
  wallNow: number
  demoTimeActive: boolean
}) {
  const [siteId, setSiteId] = useState<SiteId>(readSite)
  const [selectedDate, setSelectedDate] = useState(() => readSelectedDate(now))
  const [completedByDay, setCompletedByDay] = useState(readTaskState)
  const [forecastEntry, setForecastEntry] = useState<CachedForecast>()
  const [taskQuestion, setTaskQuestion] = useState<{ id: number; question: string }>()
  const [taskQuestionId, setTaskQuestionId] = useState(0)
  const site = sites.find((item) => item.id === siteId) ?? sites[0]
  const today = localDate(now)
  const completed = useMemo(
    () => completedByDay[`${siteId}:${selectedDate}`] ?? [],
    [completedByDay, selectedDate, siteId],
  )
  const hours = useMemo(
    () => forecastEntry?.forecast.hours.filter((hour) => localDate(new Date(hour.time).getTime()) === selectedDate) ?? [],
    [forecastEntry, selectedDate],
  )
  const tasksComplete = completed.length
  const handleForecastEntry = useCallback((entry: CachedForecast | undefined) => {
    setForecastEntry(entry)
  }, [])
  const context = useMemo(
    () => forecastContext(site.name, selectedDate, completed, forecastEntry),
    [completed, forecastEntry, selectedDate, site.name],
  )

  function changeSite(value: SiteId) {
    setTaskQuestion(undefined)
    setSiteId(value)
    setForecastEntry(undefined)
    try {
      localStorage.setItem(SITE_KEY, value)
    } catch {
      // The selected site remains active until reload.
    }
  }

  function changeDate(value: string) {
    if (value < today || value > shiftDate(today, 2)) return
    setTaskQuestion(undefined)
    setSelectedDate(value)
    try {
      localStorage.setItem(DATE_KEY, value)
    } catch {
      // The selected work date remains active until reload.
    }
  }

  function askAboutTask(task: (typeof technicianTasks)[number]) {
    const matchingHours = taskForecastHours(task, selectedDate, forecastEntry?.forecast.hours ?? [])
    const readings = matchingHours.length
      ? matchingHours.map(formatTaskForecast).join('; ')
      : 'No hourly forecast data covers this task window.'
    // The readings are already listed on the task card; ask only for a short plain read of them.
    const question = [
      `How does the weather look for ${task.title} at ${site.name}, ${selectedDate} ${taskWindowLabel(task)} local?`,
      `Forecast: ${readings}.`,
      `Answer in 2 short, plain sentences, mentioning ${task.weatherWatch.toLowerCase()}.`,
      'Use only these numbers with their units; do not list them all again or guess at storms or causes.',
    ].join(' ')
    const id = taskQuestionId + 1
    setTaskQuestionId(id)
    setTaskQuestion({ id, question })
  }

  function toggleTask(id: string) {
    const key = `${siteId}:${selectedDate}`
    const next = completed.includes(id)
      ? completed.filter((item) => item !== id)
      : [...completed, id]
    const state = { ...completedByDay, [key]: next }
    setCompletedByDay(state)
    try {
      localStorage.setItem(TASK_STATE_KEY, JSON.stringify(state))
    } catch {
      // Task checkmarks remain available until reload.
    }
  }

  const startDate = today
  const endDate = shiftDate(today, 2)
  const dataAgeHours = forecastEntry
    ? Math.max(0, (wallNow - new Date(forecastEntry.forecast.fetched_at).getTime()) / 3_600_000)
    : undefined
  const dataLabel = dataAgeHours === undefined
    ? 'Forecast not downloaded'
    : dataAgeHours > 72
      ? 'Forecast older than 72 h'
      : `Forecast ${dataAgeHours.toFixed(1)} h old`

  return (
    <div className="grid gap-5">
      <section className="field-hero relative overflow-hidden rounded-xl p-5 text-white sm:p-7">
        <div className="field-hero-contour" aria-hidden />
        <div className="relative z-10 flex flex-wrap items-end justify-between gap-5">
          <div>
            <p className="text-xs font-semibold tracking-[0.18em] text-cyan-100/75 uppercase">Technician field brief · PoC</p>
            <h2 className="mt-2 font-display text-3xl font-semibold tracking-tight sm:text-4xl">{site.name}</h2>
            <p className="mt-2 flex items-center gap-2 text-sm text-white/75">
              <MapPin className="size-4" aria-hidden />
              Service base {site.port} · approximate site centre
            </p>
          </div>
          <div className="flex flex-wrap items-end gap-3">
            <label className="grid gap-1 text-xs text-white/70">
              Wind farm
              <select
                className="h-10 min-w-40 rounded-md border border-white/20 bg-[#14333d] px-3 text-sm text-white outline-none focus-visible:ring-2 focus-visible:ring-cyan-200"
                value={siteId}
                onChange={(event) => {
                  const match = sites.find((item) => item.id === event.target.value)
                  if (match) changeSite(match.id)
                }}
              >
                {sites.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
              </select>
            </label>
            <label className="grid gap-1 text-xs text-white/70">
              Work date
              <input
                className="h-10 rounded-md border border-white/20 bg-[#14333d] px-3 text-sm text-white outline-none focus-visible:ring-2 focus-visible:ring-cyan-200"
                type="date"
                value={selectedDate}
                min={startDate}
                max={endDate}
                onChange={(event) => changeDate(event.target.value)}
              />
            </label>
          </div>
        </div>
        <div className="relative z-10 mt-6 flex flex-wrap items-center justify-between gap-3 border-t border-white/15 pt-4">
          <div className="flex items-center gap-2 text-sm">
            <Compass className="size-4 text-cyan-200" aria-hidden />
            <span>{weekday(selectedDate)}, {dayMonth(selectedDate)}</span>
            {demoTimeActive && <span className="rounded-full bg-white/10 px-2 py-0.5 text-xs">Demo time</span>}
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => changeDate(shiftDate(selectedDate, -1))}
              disabled={selectedDate <= startDate}
              aria-label="Previous workday"
              className="grid size-9 place-items-center rounded-md border border-white/20 outline-none hover:bg-white/10 focus-visible:ring-2 focus-visible:ring-cyan-200 disabled:opacity-30"
            >
              <ArrowLeft className="size-4" aria-hidden />
            </button>
            <div className="flex gap-1 rounded-md bg-black/15 p-1" role="group" aria-label="Select workday">
              {[0, 1, 2].map((offset) => {
                const day = shiftDate(today, offset)
                return (
                  <button
                    key={day}
                    type="button"
                    onClick={() => changeDate(day)}
                    aria-pressed={selectedDate === day}
                    className="rounded px-3 py-1.5 text-xs text-white/75 outline-none hover:bg-white/10 focus-visible:ring-2 focus-visible:ring-cyan-200 aria-pressed:bg-white aria-pressed:font-semibold aria-pressed:text-[#12303a]"
                  >
                    {offset === 0 ? 'Today' : weekday(day)}
                  </button>
                )
              })}
            </div>
            <button
              type="button"
              onClick={() => changeDate(shiftDate(selectedDate, 1))}
              disabled={selectedDate >= endDate}
              aria-label="Next workday"
              className="grid size-9 place-items-center rounded-md border border-white/20 outline-none hover:bg-white/10 focus-visible:ring-2 focus-visible:ring-cyan-200 disabled:opacity-30"
            >
              <ArrowRight className="size-4" aria-hidden />
            </button>
          </div>
        </div>
      </section>

      <section className="grid gap-5 xl:grid-cols-[minmax(0,1.15fr)_minmax(20rem,0.85fr)]">
        <div className="grid content-start gap-5">
          <WeatherOverview
            key={siteId}
            site={site}
            tasks={technicianTasks}
            siteId={site.id}
            online={online}
            now={now}
            wallNow={wallNow}
            selectedDate={selectedDate}
            demoTimeActive={demoTimeActive}
            onForecastEntry={handleForecastEntry}
          />

          <section aria-labelledby="task-plan-title" className="rounded-xl border bg-card p-4 sm:p-5">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <p className="text-xs font-semibold tracking-wide text-primary uppercase">Day plan</p>
                <h3 id="task-plan-title" className="mt-1 font-display text-xl font-semibold">Maintenance task breakdown</h3>
                <p className="mt-1 text-xs text-muted-foreground">Sample shift · confirm the actual work order, permits and site procedures.</p>
              </div>
              <p className="inline-flex items-center gap-2 rounded-full bg-secondary px-3 py-1.5 text-xs font-medium text-secondary-foreground">
                <Check className="size-3.5" aria-hidden />
                {tasksComplete}/{technicianTasks.length} complete
              </p>
            </div>

            <ol className="mt-4 grid gap-2">
              {technicianTasks.map((task) => {
                const done = completed.includes(task.id)
                const state = taskState(task, selectedDate, today, now, done)
                const active = state === 'In progress'
                const taskHours = taskForecastHours(task, selectedDate, forecastEntry?.forecast.hours ?? [])
                const taskConditions = taskHours.length
                  ? taskHours.map(formatTaskForecast).join(' · ')
                  : 'No hourly forecast data for this scheduled window.'
                return (
                  <li
                    key={task.id}
                    className={cn(
                      'task-row grid gap-3 rounded-lg border p-3 sm:grid-cols-[4.25rem_minmax(0,1fr)_auto] sm:items-center',
                      active && 'task-row-active',
                      done && 'task-row-complete',
                    )}
                  >
                    <div className="flex items-center gap-2 font-code text-sm font-semibold tabular-nums text-primary">
                      <Clock className="size-4" aria-hidden />
                      {task.time}
                    </div>
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-2">
                        <h4 className={cn('font-medium', done && 'line-through opacity-60')}>{task.title}</h4>
                        <span className={cn(
                          'rounded-full px-2 py-0.5 text-[0.65rem] font-semibold',
                          active ? 'bg-primary text-primary-foreground' : done ? 'bg-emerald-100 text-emerald-900' : 'bg-muted text-muted-foreground',
                        )}>
                          {state}
                        </span>
                      </div>
                      <p className="mt-1 text-xs text-muted-foreground">
                        {task.area} · {task.durationMinutes} min · Weather watch: {task.weatherWatch}
                      </p>
                      <p className="mt-1 text-xs leading-relaxed text-foreground/75">
                        <span className="font-medium">Hourly forecast overlapping task:</span> {taskConditions}
                      </p>
                    </div>
                    <div className="flex flex-wrap gap-2 sm:flex-col">
                      <button
                        type="button"
                        onClick={() => askAboutTask(task)}
                        aria-label={`Ask about ${task.title} and its weather conditions`}
                        className="inline-flex min-h-9 items-center justify-center gap-1.5 rounded-md border border-primary/30 px-3 text-xs font-medium text-primary outline-none hover:bg-secondary focus-visible:ring-2 focus-visible:ring-ring/50"
                      >
                        <ChatCircleDots className="size-4" aria-hidden />
                        Ask about conditions
                      </button>
                      <button
                        type="button"
                        onClick={() => toggleTask(task.id)}
                        aria-pressed={done}
                        className="min-h-9 rounded-md border px-3 text-xs font-medium outline-none hover:bg-secondary focus-visible:ring-2 focus-visible:ring-ring/50"
                      >
                        {done ? 'Mark pending' : 'Mark complete'}
                      </button>
                    </div>
                  </li>
                )
              })}
            </ol>
            <p className="mt-3 border-t pt-3 text-xs leading-relaxed text-muted-foreground">
              Demonstration activities, not a prescribed industry work pack. Safety context:
              {' '}
              <a
                href="https://www.gplusoffshorewind.com/work-programme/workstreams/guidelines"
                target="_blank"
                rel="noreferrer"
                className="font-medium text-primary underline underline-offset-2 focus-visible:outline-2 focus-visible:outline-ring"
              >
                G+ good-practice guidance
              </a>
              {' · '}
              <a
                href="https://www.gplusoffshorewind.com/work-programme/workstreams/statistics"
                target="_blank"
                rel="noreferrer"
                className="font-medium text-primary underline underline-offset-2 focus-visible:outline-2 focus-visible:outline-ring"
              >
                incident data
              </a>
              . No universal weather limits are implied.
            </p>
          </section>
        </div>

        <div className="grid content-start gap-5">
          <ChatPanel
            key={`${siteId}:${selectedDate}`}
            siteId={siteId}
            date={selectedDate}
            context={context}
            questionRequest={taskQuestion}
          />
          <section className="rounded-xl border bg-card p-4 sm:p-5">
            <div className="flex items-center justify-between gap-3">
              <div>
                <p className="text-xs font-semibold tracking-wide text-primary uppercase">Shift snapshot</p>
                <h3 className="mt-1 font-display text-lg font-semibold">Workday at a glance</h3>
              </div>
              <span className="rounded-full border px-2.5 py-1 text-xs text-muted-foreground">{dataLabel}</span>
            </div>
            <dl className="mt-4 grid grid-cols-2 gap-3">
              <Snapshot label="Planned activities" value={`${technicianTasks.length}`} />
              <Snapshot label="Forecast hours" value={hours.length ? `${hours.length} hourly points` : 'Not downloaded'} />
              <Snapshot label="Completed" value={`${tasksComplete} of ${technicianTasks.length}`} />
              <Snapshot label="Data source" value={forecastEntry?.forecast.source ?? 'Waiting for forecast'} />
            </dl>
            <p className="mt-3 flex items-start gap-2 border-t pt-3 text-xs leading-relaxed text-muted-foreground">
              <Waves className="mt-0.5 size-4 shrink-0 text-primary" aria-hidden />
              Sea state can change transfer access and vessel motion; wind and gusts may constrain work at height and lifting.
              Site-approved limits take precedence over this prototype.
            </p>
            {!online && (
              <p className="mt-3 flex items-center gap-2 rounded-md bg-amber-50 px-3 py-2 text-xs text-amber-950">
                <Wind className="size-4 shrink-0" aria-hidden />
                Offline mode: use the forecast saved on this device. Live lightning is not included.
              </p>
            )}
          </section>
        </div>
      </section>
    </div>
  )
}

function Snapshot({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md bg-muted/50 px-3 py-2.5">
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="mt-1 truncate text-sm font-semibold" title={value}>{value}</dd>
    </div>
  )
}
