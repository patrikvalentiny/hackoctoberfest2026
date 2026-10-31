import type { Instant } from '@/lib/planner'

export const TIME_ZONE = 'Europe/Copenhagen'

const timeFormat = new Intl.DateTimeFormat('en-GB', {
  timeZone: TIME_ZONE,
  hour: '2-digit',
  minute: '2-digit',
})

export function clock(value: Instant | string | null | undefined) {
  if (!value) return '–'
  return timeFormat.format(new Date(typeof value === 'string' ? value : value.utc))
}

// Plain dates from the API (YYYY-MM-DD) are local Copenhagen days; format them
// at noon UTC so no time zone can shift them to a neighbouring day.
function noon(date: string) {
  return new Date(`${date}T12:00:00Z`)
}

export function weekday(date: string) {
  return new Intl.DateTimeFormat('en-GB', { weekday: 'short', timeZone: 'UTC' }).format(noon(date))
}

export function dayMonth(date: string) {
  return new Intl.DateTimeFormat('en-GB', { day: 'numeric', month: 'short', timeZone: 'UTC' }).format(
    noon(date),
  )
}

export function longDate(date: string) {
  return new Intl.DateTimeFormat('en-GB', {
    weekday: 'long',
    day: 'numeric',
    month: 'long',
    timeZone: 'UTC',
  }).format(noon(date))
}

export function dateTime(value: Instant | null | undefined) {
  if (!value) return '–'
  return new Intl.DateTimeFormat('en-GB', {
    timeZone: TIME_ZONE,
    day: 'numeric',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date(value.utc))
}

export function percent(value: number | null) {
  return value === null ? '–' : `${Math.round(value * 100)}%`
}

export const confidenceLabel = {
  high: 'High confidence, DMI 60 h',
  medium: 'Medium confidence, ensemble',
  low: 'Low confidence, ensemble',
  outlook: 'Outlook only',
} as const

export const limitNames: Record<string, string> = {
  wave_height: 'Wave height',
  wind_100m: 'Wind at 100 m',
  visibility: 'Visibility',
  daylight: 'Daylight',
}
