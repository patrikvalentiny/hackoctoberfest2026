import { useState, type FormEvent } from 'react'
import { Button } from '@/components/ui/button'
import type { ProfileRequest, SiteId, TaskId, VesselId } from '@/lib/planner'

const sites: { id: SiteId; name: string }[] = [
  { id: 'hr1', name: 'Horns Rev 1' },
  { id: 'hr2', name: 'Horns Rev 2' },
  { id: 'hr3', name: 'Horns Rev 3' },
]

const vessels: { id: VesselId; name: string; hint: string }[] = [
  { id: 'ctv', name: 'CTV', hint: 'Sails out and back daily, Hs up to 1.5 m' },
  { id: 'sov', name: 'SOV', hint: 'Stays at the farm, gangway, Hs 2.5 m' },
]

const tasks: { id: TaskId; name: string }[] = [
  { id: 'nacelle', name: 'Nacelle work, wind up to 20 m/s' },
  { id: 'hub_locked_rotor', name: 'Hub work, rotor locked, up to 15 m/s' },
  { id: 'lifting', name: 'Lifting and material transport, below 10 m/s' },
]

// Matches the demo request: 4 days of bearing work on HR1 from an SOV, 6 h a day.
const demo: ProfileRequest = {
  site_id: 'hr1',
  vessel: 'sov',
  task: 'nacelle',
  work_hours_per_day: 6,
  days_needed: 4,
  consecutive: false,
}

const field = 'grid gap-1.5 text-sm'
const control =
  'h-9 w-full rounded-md border border-input bg-card px-2.5 text-sm text-foreground outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/40'

export function JobForm({
  busy,
  onSubmit,
}: {
  busy: boolean
  onSubmit: (request: ProfileRequest) => void
}) {
  const [request, setRequest] = useState<ProfileRequest>(demo)

  function update<K extends keyof ProfileRequest>(key: K, value: ProfileRequest[K]) {
    setRequest((current) => ({ ...current, [key]: value }))
  }

  function submit(event: FormEvent) {
    event.preventDefault()
    onSubmit(request)
  }

  return (
    <form onSubmit={submit} className="grid gap-4">
      <label className={field}>
        <span className="text-muted-foreground">Wind farm</span>
        <select
          className={control}
          value={request.site_id}
          onChange={(event) => update('site_id', event.target.value as SiteId)}
        >
          {sites.map((site) => (
            <option key={site.id} value={site.id}>
              {site.name}
            </option>
          ))}
        </select>
      </label>

      <fieldset className={field}>
        <legend className="mb-1.5 text-muted-foreground">Vessel</legend>
        <div className="grid grid-cols-2 gap-2">
          {vessels.map((vessel) => (
            <label
              key={vessel.id}
              className="cursor-pointer rounded-md border border-input bg-card px-3 py-2 has-checked:border-primary has-checked:bg-secondary has-focus-visible:ring-3 has-focus-visible:ring-ring/40"
            >
              <input
                type="radio"
                name="vessel"
                className="sr-only"
                checked={request.vessel === vessel.id}
                onChange={() => update('vessel', vessel.id)}
              />
              <span className="block font-semibold">{vessel.name}</span>
              <span className="block text-xs leading-snug text-muted-foreground">{vessel.hint}</span>
            </label>
          ))}
        </div>
      </fieldset>

      <label className={field}>
        <span className="text-muted-foreground">Task</span>
        <select
          className={control}
          value={request.task}
          onChange={(event) => update('task', event.target.value as TaskId)}
        >
          {tasks.map((task) => (
            <option key={task.id} value={task.id}>
              {task.name}
            </option>
          ))}
        </select>
      </label>

      <div className="grid grid-cols-2 gap-3">
        <label className={field}>
          <span className="text-muted-foreground">Work hours a day</span>
          <input
            className={control}
            type="number"
            min={0.5}
            max={12}
            step={0.5}
            value={request.work_hours_per_day}
            onChange={(event) => update('work_hours_per_day', Number(event.target.value))}
          />
        </label>
        <label className={field}>
          <span className="text-muted-foreground">Days needed</span>
          <input
            className={control}
            type="number"
            min={1}
            max={21}
            value={request.days_needed}
            onChange={(event) => update('days_needed', Number(event.target.value))}
          />
        </label>
      </div>

      <label className="flex items-center gap-2 text-sm">
        <input
          type="checkbox"
          className="size-4 accent-(--primary)"
          checked={request.consecutive}
          onChange={(event) => update('consecutive', event.target.checked)}
        />
        Days must be consecutive
      </label>

      <Button type="submit" size="lg" disabled={busy} className="h-10 text-base">
        {busy ? 'Finding windows…' : 'Find work windows'}
      </Button>
    </form>
  )
}
