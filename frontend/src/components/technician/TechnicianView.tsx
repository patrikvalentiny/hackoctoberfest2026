import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { ChatCircleDots, Lightning } from '@phosphor-icons/react'
import { Button } from '@/components/ui/button'
import { clock, dateTime, limitNames, percent, TIME_ZONE } from '@/lib/format'
import { buildJobProfile, checkTaskFits } from '@/lib/planner'
import type { Freshness, Profile, SiteId, TaskFit, TaskId, VesselId } from '@/lib/planner'
import { cn } from '@/lib/utils'

const STORAGE_KEY = 'harbour-pulse:technician'
const STEP_MINUTES = 15

// The last answer from the engine is kept on the device, so the countdown and
// the data age still work when the vessel loses its connection.
type Saved = { profile: Profile; base: TaskFit; check?: TaskFit }

function readSaved(): Saved | undefined {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    return raw ? (JSON.parse(raw) as Saved) : undefined
  } catch {
    return undefined
  }
}

function writeSaved(saved: Saved) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(saved))
  } catch {
    // Storage can be full or blocked; the view still works for this session.
  }
}

function messageFrom(error: unknown) {
  return error instanceof Error ? error.message : 'Something went wrong.'
}

function useNow(intervalMs: number) {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), intervalMs)
    return () => clearInterval(timer)
  }, [intervalMs])
  return now
}

// Age is recomputed on the device, so it keeps growing while offline.
function freshness(fetchedAt: string, now: number): { hours: number; level: Freshness } {
  const hours = (now - new Date(fetchedAt).getTime()) / 3_600_000
  return { hours, level: hours < 6 ? 'fresh' : hours <= 12 ? 'aging' : 'stale' }
}

function duration(ms: number) {
  const minutes = Math.max(0, Math.floor(ms / 60_000))
  const hours = Math.floor(minutes / 60)
  return hours > 0 ? `${hours} h ${minutes % 60} min` : `${minutes} min`
}

function todayLocal() {
  return new Intl.DateTimeFormat('en-CA', { timeZone: TIME_ZONE }).format(new Date())
}

function nextQuarterHour() {
  const parts = new Intl.DateTimeFormat('en-GB', {
    timeZone: TIME_ZONE,
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23',
  }).formatToParts(new Date())
  const hour = Number(parts.find((part) => part.type === 'hour')?.value)
  const minute = Number(parts.find((part) => part.type === 'minute')?.value)
  const total = Math.min(23 * 60 + 45, Math.ceil((hour * 60 + minute) / STEP_MINUTES) * STEP_MINUTES)
  return `${String(Math.floor(total / 60)).padStart(2, '0')}:${String(total % 60).padStart(2, '0')}`
}

const control =
  'h-10 w-full rounded-md border border-input bg-card px-2.5 text-base text-foreground outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/40'

function Setup({ busy, onSubmit }: { busy: boolean; onSubmit: (site: SiteId, vessel: VesselId, task: TaskId) => void }) {
  const [site, setSite] = useState<SiteId>('hr1')
  const [vessel, setVessel] = useState<VesselId>('ctv')
  const [task, setTask] = useState<TaskId>('nacelle')

  function submit(event: FormEvent) {
    event.preventDefault()
    onSubmit(site, vessel, task)
  }

  return (
    <form onSubmit={submit} className="grid gap-3">
      <p className="text-muted-foreground">
        Pick today's farm, vessel and task. Do this before departure while you still have a
        connection.
      </p>
      <select className={control} value={site} onChange={(event) => setSite(event.target.value as SiteId)} aria-label="Wind farm">
        <option value="hr1">Horns Rev 1</option>
        <option value="hr2">Horns Rev 2</option>
        <option value="hr3">Horns Rev 3</option>
      </select>
      <select className={control} value={vessel} onChange={(event) => setVessel(event.target.value as VesselId)} aria-label="Vessel">
        <option value="ctv">CTV, sails back to port</option>
        <option value="sov">SOV, stays at the farm</option>
      </select>
      <select className={control} value={task} onChange={(event) => setTask(event.target.value as TaskId)} aria-label="Task">
        <option value="nacelle">Nacelle work</option>
        <option value="hub_locked_rotor">Hub work, rotor locked</option>
        <option value="lifting">Lifting and material transport</option>
      </select>
      <Button type="submit" size="lg" disabled={busy} className="h-11 text-base">
        {busy ? 'Downloading…' : 'Download today’s brief'}
      </Button>
    </form>
  )
}

function Countdown({ fit, now }: { fit: TaskFit; now: number }) {
  if (fit.fits === null) {
    return <p className="font-display text-2xl font-semibold">No timing given</p>
  }
  if (!fit.last_transfer_back) {
    return (
      <>
        <p className="font-display text-2xl font-semibold">No transfer back found</p>
        <p className="mt-1 text-sm">{fit.note}</p>
      </>
    )
  }
  const left = new Date(fit.last_transfer_back.utc).getTime() - now
  return (
    <>
      <p className="font-display text-6xl leading-none font-bold tabular-nums">{clock(fit.last_transfer_back)}</p>
      <p className="mt-2 text-lg">
        {left > 0 ? `Last transfer back in ${duration(left)}` : 'Last transfer back has passed'}
      </p>
    </>
  )
}

function FitResult({ fit }: { fit: TaskFit }) {
  if (fit.fits === null) return <p className="text-sm">{fit.note}</p>
  const blocking = fit.blocking_limits.map((id) => limitNames[id] ?? id).join(', ')
  return (
    <div className={cn('rounded-md border-l-4 px-4 py-3', fit.fits ? 'fit-yes' : 'fit-no')}>
      <p className="font-display text-xl font-semibold">
        {fit.fits ? 'Fits before the last transfer back' : 'Does not fit from that start'}
      </p>
      <dl className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1 text-sm">
        <dt className="text-muted-foreground">Latest start</dt>
        <dd className="tabular-nums">{fit.latest_start ? clock(fit.latest_start) : 'None today'}</dd>
        <dt className="text-muted-foreground">Last transfer back</dt>
        <dd className="tabular-nums">{clock(fit.last_transfer_back)}</dd>
        <dt className="text-muted-foreground">Ensemble members agreeing</dt>
        <dd className="tabular-nums">{percent(fit.ensemble_fraction)}</dd>
        {blocking && (
          <>
            <dt className="text-muted-foreground">Limited by</dt>
            <dd>{blocking}</dd>
          </>
        )}
      </dl>
      <p className="mt-2 text-xs text-muted-foreground">
        Timing from: {fit.reference}. {fit.note}
      </p>
    </div>
  )
}

export function TechnicianView({ plannerProfile, online }: { plannerProfile?: Profile; online: boolean }) {
  const [saved, setSaved] = useState<Saved | undefined>(readSaved)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [start, setStart] = useState(nextQuarterHour)
  const [minutes, setMinutes] = useState(90)
  const now = useNow(30_000)

  const download = useCallback(async (profile: Profile) => {
    setBusy(true)
    setError('')
    try {
      // The engine steps in quarter hours from the start, so align the start to
      // match the times a technician gets from "Check the task".
      const step = STEP_MINUTES * 60_000
      const start = new Date(Math.floor(Date.now() / step) * step).toISOString()
      const base = await checkTaskFits(profile.profile_id, start, STEP_MINUTES)
      const next = { profile, base }
      setSaved(next)
      writeSaved(next)
    } catch (failure) {
      setError(messageFrom(failure))
    } finally {
      setBusy(false)
    }
  }, [])

  async function setup(site_id: SiteId, vessel: VesselId, task: TaskId) {
    setBusy(true)
    setError('')
    try {
      const today = todayLocal()
      const profile = await buildJobProfile({
        site_id,
        vessel,
        task,
        work_hours_per_day: 1,
        start_date: today,
        end_date: today,
      })
      await download(profile)
    } catch (failure) {
      setError(messageFrom(failure))
      setBusy(false)
    }
  }

  async function check(event: FormEvent) {
    event.preventDefault()
    if (!saved) return
    setBusy(true)
    setError('')
    try {
      // A time without an offset is read by the backend as Copenhagen time.
      const fit = await checkTaskFits(saved.profile.profile_id, `${todayLocal()}T${start}`, minutes)
      const next = { ...saved, check: fit }
      setSaved(next)
      writeSaved(next)
    } catch (failure) {
      setError(
        online
          ? messageFrom(failure)
          : 'No connection to the planner engine. The countdown above is from the last download.',
      )
    } finally {
      setBusy(false)
    }
  }

  const age = saved && freshness(saved.base.data.fetched_at.utc, now)

  return (
    <div className="mx-auto grid w-full max-w-md gap-6 p-4 sm:p-6">
      {error && (
        <p role="alert" className="rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-destructive">
          {error}
        </p>
      )}

      {!saved ? (
        <section aria-labelledby="setup-title" className="grid gap-3">
          <h2 id="setup-title" className="font-display text-2xl font-semibold">
            Today offshore
          </h2>
          {plannerProfile && (
            <Button variant="outline" size="lg" disabled={busy} onClick={() => download(plannerProfile)} className="h-11">
              Use the planned job: {plannerProfile.site.name}, {plannerProfile.vessel.toUpperCase()}
            </Button>
          )}
          <Setup busy={busy} onSubmit={setup} />
        </section>
      ) : (
        <>
          <section aria-labelledby="countdown-title" className="countdown rounded-lg p-5">
            <div className="flex items-baseline justify-between gap-3">
              <h2 id="countdown-title" className="text-sm">
                {saved.profile.site.name}, {saved.profile.vessel.toUpperCase()}
              </h2>
              {age && (
                <p className={cn('inline-flex items-center gap-1.5 text-sm', `age-${age.level}`)}>
                  <span className="age-dot size-2 rounded-full" aria-hidden />
                  Data {age.hours.toFixed(1)} h old
                </p>
              )}
            </div>
            <div className="mt-4">
              {age?.level === 'stale' ? (
                <>
                  <p className="font-display text-2xl font-semibold">Data older than 12 hours</p>
                  <p className="mt-1">No timing is given from old data. Ask the vessel master.</p>
                </>
              ) : (
                <Countdown fit={saved.base} now={now} />
              )}
            </div>
            <p className="mt-4 text-sm opacity-80">
              Sunset {clock(saved.base.sunset)}. Forecast fetched {dateTime(saved.base.data.fetched_at)}.
            </p>
          </section>

          <p className="flex gap-2 text-sm">
            <Lightning className="mt-0.5 size-4 shrink-0 text-(--signal)" aria-hidden />
            <span>
              Live lightning is not in this brief. Follow the vessel's lightning procedure and listen to
              the radio.
            </span>
          </p>

          <section aria-labelledby="fit-title" className="grid gap-3">
            <h2 id="fit-title" className="font-display text-xl font-semibold">
              Will a task fit?
            </h2>
            <form onSubmit={check} className="grid grid-cols-2 gap-3">
              <label className="grid gap-1.5 text-sm">
                <span className="text-muted-foreground">Start</span>
                <input className={control} type="time" step={STEP_MINUTES * 60} value={start} onChange={(event) => setStart(event.target.value)} />
              </label>
              <label className="grid gap-1.5 text-sm">
                <span className="text-muted-foreground">Duration, minutes</span>
                <input
                  className={control}
                  type="number"
                  min={15}
                  max={720}
                  step={15}
                  value={minutes}
                  onChange={(event) => setMinutes(Number(event.target.value))}
                />
              </label>
              <Button type="submit" size="lg" disabled={busy || age?.level === 'stale'} className="col-span-2 h-11 text-base">
                Check the task
              </Button>
            </form>
            {saved.check && <FitResult fit={saved.check} />}
          </section>

          <section aria-labelledby="tech-chat-title" className="grid gap-2">
            <h2 id="tech-chat-title" className="font-display text-xl font-semibold">
              Ask the agent
            </h2>
            <div className="flex gap-3 rounded-md border border-dashed p-3 text-sm text-muted-foreground">
              <ChatCircleDots className="mt-0.5 size-5 shrink-0" aria-hidden />
              <p>The offline agent is not connected yet. It will answer from this same brief.</p>
            </div>
          </section>

          <div className="flex flex-wrap gap-2">
            <Button variant="outline" disabled={busy || !online} onClick={() => download(saved.profile)}>
              Download again
            </Button>
            <Button
              variant="ghost"
              onClick={() => {
                setSaved(undefined)
                try {
                  localStorage.removeItem(STORAGE_KEY)
                } catch {
                  // Nothing to clear when storage is blocked.
                }
              }}
            >
              Change job
            </Button>
          </div>
        </>
      )}
    </div>
  )
}
