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
  offline?: boolean
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

export type CurrentConditions = {
  site_id: SiteId
  profile_id: string | null
  limits_from: string
  data: DataAge & { offline: boolean }
  forecast_now: {
    time: Instant
    reference: string
    values: Record<string, number | null>
    limits: {
      id: string
      label: string
      value: number | null
      limit: number
      unit: string
      comparison: 'max' | 'min'
      within_limit: boolean | null
    }[]
  } | null
  forecast_note: string
  lightning: {
    available: boolean
    note?: string
    strikes_within_48km?: number
    strikes_within_80km?: number
  }
}

export type AgentMessage = {
  role: 'user' | 'assistant'
  content: string
}
