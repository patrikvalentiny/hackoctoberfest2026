import { finishCall, startCall } from '@/lib/tool-log'

// Types mirror the serializers in backend/src/backend/api/planner.py.

export type SiteId = 'hr1' | 'hr2' | 'hr3'
export type VesselId = 'ctv' | 'sov'
export type TaskId = 'nacelle' | 'hub_locked_rotor' | 'lifting'
export type Confidence = 'high' | 'medium' | 'low' | 'outlook'
export type Freshness = 'fresh' | 'aging' | 'stale'

export type Instant = { utc: string; local: string }
export type Span = { start: Instant; end: Instant }

export type Site = {
  id: SiteId
  name: string
  latitude: number
  longitude: number
  port: string
  ctv_transit_hours: number
  coordinates_verified: boolean
  note: string
}

export type Limit = {
  id: string
  label: string
  variable: string
  comparison: 'max' | 'min'
  value: number
  unit: string
  segment: 'span' | 'work'
  source: string
}

export type Profile = {
  profile_id: string
  site: Site
  vessel: VesselId
  task: TaskId
  work_hours_per_day: number
  transit_hours_each_way: number
  days_needed: number
  start_date: string
  end_date: string
  consecutive: boolean
  limits: Limit[]
  not_evaluated: string[]
  disclaimer: string
}

export type ProfileRequest = {
  site_id: SiteId
  vessel: VesselId
  task: TaskId
  work_hours_per_day: number
  days_needed?: number
  start_date?: string
  end_date?: string
  consecutive?: boolean
  sov_hs_limit_m?: number
}

export type DataAge = {
  fetched_at: Instant
  age_hours: number
  freshness: Freshness
}

export type Day = {
  date: string
  confidence: Confidence
  probability: number | null
  members: number
  members_with_window: number | null
  window: Span | null
  members_in_window: number | null
  deterministic_window: Span | null
  deterministic_evaluated: boolean
  limiting_parameter: string | null
  limit_failures: Record<string, number>
  sunrise: Instant
  sunset: Instant
  recompute_at: Instant | null
  note: string | null
}

export type Windows = {
  profile_id: string
  data: DataAge
  suggested_days: string[]
  days: Day[]
  notes: string[]
}

export type Spread = { min: number; p10: number; median: number; p90: number; max: number }
export type HourValue = Spread | { value: number } | null

export type Hour = {
  time: Instant
  daylight: boolean
  variables: Record<string, HourValue>
  deterministic: Record<string, number | null> | null
  members_failing: Record<string, number>
}

export type DayExplanation = {
  profile_id: string
  data: DataAge
  day: Day
  limits: Limit[]
  hours: Hour[]
  notes: string[]
}

export type TaskFit = {
  profile_id: string
  data: DataAge
  start: Instant
  duration_minutes: number
  reference: string | null
  fits: boolean | null
  latest_start: Instant | null
  last_transfer_back: Instant | null
  ensemble_fraction: number | null
  blocking_limits: string[]
  sunset: Instant
  note: string | null
  not_evaluated: string[]
}

export type DataStatus = {
  site_id: SiteId
  offline: boolean
  data: DataAge
  sources: Record<string, unknown>[]
  notes: string[]
}

const apiUrl = (import.meta.env.VITE_API_URL || 'http://localhost:8000').replace(/\/+$/, '')

async function call<T>(
  tool: string,
  input: unknown,
  path: string,
  summarize: (result: T) => string,
  init?: RequestInit,
): Promise<T> {
  const id = startCall(tool, input)
  try {
    const response = await fetch(`${apiUrl}${path}`, init)
    if (!response.ok) {
      let message = `${tool} failed (HTTP ${response.status}).`
      try {
        const body: { detail?: unknown } = await response.json()
        if (typeof body.detail === 'string') message = body.detail
      } catch {
        // Keep the HTTP status message when the server did not return JSON.
      }
      throw new Error(message)
    }
    const result = (await response.json()) as T
    finishCall(id, 'ok', summarize(result))
    return result
  } catch (error) {
    const message =
      error instanceof TypeError
        ? 'Planner API is unreachable. Start the backend or check the connection.'
        : error instanceof Error
          ? error.message
          : 'Unknown error.'
    finishCall(id, 'error', message)
    throw new Error(message, { cause: error })
  }
}

export function listSites() {
  return call<{ sites: Site[] }>('list_sites', {}, '/api/sites', (r) => `${r.sites.length} sites`)
}

export function buildJobProfile(request: ProfileRequest) {
  return call<Profile>(
    'build_job_profile',
    request,
    '/api/profiles',
    (r) => `profile ${r.profile_id}, ${r.limits.length} limits`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(request),
    },
  )
}

export function findWindows(profileId: string) {
  return call<Windows>(
    'find_windows',
    { profile_id: profileId },
    `/api/profiles/${profileId}/windows`,
    (r) =>
      `${r.days.length} days, suggested ${r.suggested_days.join(', ') || 'none'}, data ${r.data.age_hours} h old`,
  )
}

export function explainDay(profileId: string, date: string) {
  return call<DayExplanation>(
    'explain_day',
    { profile_id: profileId, date },
    `/api/profiles/${profileId}/days/${date}`,
    (r) =>
      `${r.hours.length} hours, limiting ${r.day.limiting_parameter ?? 'none'}`,
  )
}

export function checkTaskFits(profileId: string, start: string, durationMinutes: number) {
  const params = new URLSearchParams({ start, duration_minutes: String(durationMinutes) })
  return call<TaskFit>(
    'check_task_fits',
    { profile_id: profileId, start, duration_minutes: durationMinutes },
    `/api/profiles/${profileId}/task-fit?${params}`,
    (r) => `fits ${r.fits ?? 'unknown'}, latest start ${r.latest_start?.local.slice(11, 16) ?? 'none'}`,
  )
}

export function dataStatus(siteId: SiteId) {
  return call<DataStatus>(
    'data_status',
    { site_id: siteId },
    `/api/data-status?site_id=${siteId}`,
    (r) => `${r.sources.length} sources, ${r.data.freshness}`,
  )
}
