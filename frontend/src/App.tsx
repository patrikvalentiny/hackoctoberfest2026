import { useEffect, useState } from 'react'
import { ChatCircleDots, WifiHigh, WifiSlash } from '@phosphor-icons/react'
import { Calendar } from '@/components/planner/Calendar'
import { DayDetail } from '@/components/planner/DayDetail'
import { JobForm } from '@/components/planner/JobForm'
import { ToolPanel } from '@/components/planner/ToolPanel'
import { TechnicianView } from '@/components/technician/TechnicianView'
import { cn } from '@/lib/utils'
import { buildJobProfile, explainDay, findWindows } from '@/lib/planner'
import type { DataAge, DayExplanation, Profile, ProfileRequest, Windows } from '@/lib/planner'
import { dateTime } from '@/lib/format'

function messageFrom(error: unknown) {
  return error instanceof Error ? error.message : 'Something went wrong.'
}

const freshnessText = {
  fresh: 'Data fresh',
  aging: 'Data aging',
  stale: 'Data stale, for information only',
} as const

function DataAgeChip({ data }: { data: DataAge }) {
  return (
    <p
      className={cn('age-chip inline-flex items-center gap-2 rounded-full px-3 py-1 text-sm', `age-${data.freshness}`)}
      title={`Fetched ${dateTime(data.fetched_at)}`}
    >
      <span className="age-dot size-2 rounded-full" aria-hidden />
      {freshnessText[data.freshness]}, {data.age_hours} h old
    </p>
  )
}

function useOnline() {
  const [online, setOnline] = useState(navigator.onLine)
  useEffect(() => {
    const update = () => setOnline(navigator.onLine)
    window.addEventListener('online', update)
    window.addEventListener('offline', update)
    return () => {
      window.removeEventListener('online', update)
      window.removeEventListener('offline', update)
    }
  }, [])
  return online
}

type Mode = 'planner' | 'technician'

const MODE_KEY = 'harbour-pulse:mode'

function readMode(): Mode {
  try {
    return localStorage.getItem(MODE_KEY) === 'technician' ? 'technician' : 'planner'
  } catch {
    return 'planner'
  }
}

function App() {
  const online = useOnline()
  const [mode, setMode] = useState<Mode>(readMode)
  const [profile, setProfile] = useState<Profile>()
  const [windows, setWindows] = useState<Windows>()
  const [selected, setSelected] = useState<string>()
  const [explanation, setExplanation] = useState<DayExplanation>()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  async function selectDay(profileId: string, date: string) {
    setSelected(date)
    setError('')
    try {
      setExplanation(await explainDay(profileId, date))
    } catch (failure) {
      setExplanation(undefined)
      setError(messageFrom(failure))
    }
  }

  async function plan(request: ProfileRequest) {
    setBusy(true)
    setError('')
    try {
      const nextProfile = await buildJobProfile(request)
      setProfile(nextProfile)
      const nextWindows = await findWindows(nextProfile.profile_id)
      setWindows(nextWindows)
      const first = nextWindows.suggested_days[0] ?? nextWindows.days[0]?.date
      setExplanation(undefined)
      if (first) await selectDay(nextProfile.profile_id, first)
    } catch (failure) {
      setError(messageFrom(failure))
    } finally {
      setBusy(false)
    }
  }

  function changeMode(next: Mode) {
    setMode(next)
    try {
      localStorage.setItem(MODE_KEY, next)
    } catch {
      // The choice is only a convenience; ignore blocked storage.
    }
  }

  return (
    <div className="grid min-h-dvh grid-rows-[auto_1fr_auto] lg:h-dvh">
      <header className="flex flex-wrap items-center justify-between gap-3 border-b px-4 py-3 sm:px-6">
        <div className="flex items-baseline gap-3">
          <h1 className="font-display text-2xl font-bold tracking-tight">Harbour Pulse</h1>
          <p className="hidden text-sm text-muted-foreground sm:block">
            Work windows for the Horns Rev wind farms
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <div role="group" aria-label="View" className="flex rounded-md border p-0.5">
            {(['planner', 'technician'] as const).map((value) => (
              <button
                key={value}
                type="button"
                aria-pressed={mode === value}
                onClick={() => changeMode(value)}
                className="rounded px-3 py-1 text-sm outline-none focus-visible:ring-3 focus-visible:ring-ring/50 aria-pressed:bg-primary aria-pressed:text-primary-foreground"
              >
                {value === 'planner' ? 'Planner' : 'Technician'}
              </button>
            ))}
          </div>
          {mode === 'planner' && windows && <DataAgeChip data={windows.data} />}
          <p className="inline-flex items-center gap-1.5 text-sm text-muted-foreground">
            {online ? <WifiHigh aria-hidden /> : <WifiSlash aria-hidden />}
            {online ? 'Online' : 'Offline'}
          </p>
        </div>
      </header>

      {mode === 'technician' ? (
        <main className="grid min-h-0 lg:grid-rows-[1fr_12rem]">
          <div className="lg:overflow-y-auto">
            <TechnicianView plannerProfile={profile} online={online} />
          </div>
          <div className="min-h-56 border-t lg:min-h-0">
            <ToolPanel />
          </div>
        </main>
      ) : (
        <main className="grid min-h-0 lg:grid-cols-[23rem_1fr] lg:grid-rows-[1fr_12rem]">
          <aside className="agent-column border-b p-4 sm:p-6 lg:row-span-2 lg:overflow-y-auto lg:border-r lg:border-b-0">
            <section aria-labelledby="agent-title" className="mb-6">
              <h2 id="agent-title" className="font-display text-lg font-semibold">
                Plan a job
              </h2>
              <div className="mt-3 flex gap-3 rounded-md border border-dashed p-3 text-sm text-muted-foreground">
                <ChatCircleDots className="mt-0.5 size-5 shrink-0" aria-hidden />
                <p>
                  The planning agent is not connected yet. Describe the job with the form; the
                  agent will fill in the same profile from a chat message.
                </p>
              </div>
            </section>
            <JobForm busy={busy} onSubmit={plan} />
            {profile && (
              <section aria-labelledby="limits-title" className="mt-6 text-sm">
                <h2 id="limits-title" className="font-display text-base font-semibold">
                  Limits applied
                </h2>
                <ul className="mt-2 grid gap-2">
                  {profile.limits.map((limit) => (
                    <li key={limit.id}>
                      <span className="font-medium">
                        {limit.label}: {limit.comparison === 'max' ? 'up to' : 'at least'} {limit.value}{' '}
                        {limit.unit}
                      </span>
                      <span className="block text-xs text-muted-foreground">{limit.source}</span>
                    </li>
                  ))}
                </ul>
                <h3 className="mt-4 font-medium">Not evaluated</h3>
                <ul className="mt-1 grid list-disc gap-1 pl-4 text-xs text-muted-foreground">
                  {profile.not_evaluated.map((item) => (
                    <li key={item}>{item}</li>
                  ))}
                </ul>
              </section>
            )}
          </aside>

          <section aria-label="Dashboard" className="min-w-0 p-4 sm:p-6 lg:overflow-y-auto">
            {error && (
              <p role="alert" className="mb-4 rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-destructive">
                {error}
              </p>
            )}
            {windows && profile ? (
              <div className="grid gap-8">
                <section aria-labelledby="calendar-title">
                  <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
                    <h2 id="calendar-title" className="font-display text-xl font-semibold">
                      {profile.site.name}, next 21 days
                    </h2>
                    <p className="text-sm text-muted-foreground">
                      {profile.vessel.toUpperCase()}, {profile.work_hours_per_day} h work
                      {profile.transit_hours_each_way > 0 && ` + ${profile.transit_hours_each_way} h transit each way`},{' '}
                      {profile.days_needed} {profile.days_needed === 1 ? 'day' : 'days'} needed
                    </p>
                  </div>
                  <Calendar
                    days={windows.days}
                    suggested={windows.suggested_days}
                    selected={selected}
                    onSelect={(date) => selectDay(profile.profile_id, date)}
                  />
                  {windows.notes.length > 0 && (
                    <ul className="mt-3 grid gap-1 text-xs text-muted-foreground">
                      {windows.notes.map((note) => (
                        <li key={note}>{note}</li>
                      ))}
                    </ul>
                  )}
                </section>
                {explanation && explanation.day.date === selected && (
                  <DayDetail explanation={explanation} transitHours={profile.transit_hours_each_way} />
                )}
              </div>
            ) : (
              <div className="grid h-full min-h-64 place-content-center text-center">
                <p className="font-display text-2xl font-semibold">Which days can the team get out?</p>
                <p className="mt-2 max-w-md text-muted-foreground">
                  Describe the job on the left. The engine checks wave height, wind, visibility and daylight for every hour of the next 21 days.
                </p>
              </div>
            )}
          </section>

          <div className="min-h-56 border-t lg:col-start-2 lg:min-h-0">
            <ToolPanel />
          </div>
        </main>
      )}

      <footer className="flex flex-wrap justify-between gap-x-6 gap-y-1 border-t px-4 py-2 text-xs text-muted-foreground sm:px-6">
        <p>
          Decision support only. The vessel master and team lead decide, using site-approved limits and
          procedures.
        </p>
        <p>
          Data: DMI, ECMWF and Open-Meteo, CC BY 4.0. Times in Europe/Copenhagen.
        </p>
      </footer>
    </div>
  )
}

export default App
