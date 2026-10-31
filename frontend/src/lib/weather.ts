export type SiteProfile = {
  name: string
  latitude: number
  longitude: number
}

export type ForecastHour = {
  time: string
  wind_speed_kn: number | null
  wind_gusts_kn: number | null
  wind_direction_deg: number | null
  wave_height_m: number | null
  wave_period_s: number | null
  wave_direction_deg: number | null
  swell_height_m: number | null
  swell_period_s: number | null
  precipitation_probability_pct: number | null
  visibility_m: number | null
}

export type WeatherForecast = {
  latitude: number
  longitude: number
  fetched_at: string
  source: string
  source_url: string
  hours: ForecastHour[]
}

export type CachedForecast = {
  key: string
  saved_at: string
  forecast: WeatherForecast
}

export function siteKey(site: Pick<SiteProfile, 'latitude' | 'longitude'>) {
  return `${site.latitude.toFixed(4)},${site.longitude.toFixed(4)}`
}

export async function fetchForecast(
  site: Pick<SiteProfile, 'latitude' | 'longitude'>,
): Promise<WeatherForecast> {
  const apiUrl = (import.meta.env.VITE_API_URL || 'http://localhost:8000').replace(
    /\/+$/,
    '',
  )
  const params = new URLSearchParams({
    latitude: String(site.latitude),
    longitude: String(site.longitude),
  })
  const response = await fetch(`${apiUrl}/api/forecast?${params}`)

  if (!response.ok) {
    let message = `Forecast request failed (${response.status}).`
    try {
      const body: { detail?: unknown } = await response.json()
      if (typeof body.detail === 'string') message = body.detail
    } catch {
      // Keep the HTTP status message when the server did not return JSON.
    }
    throw new Error(message)
  }

  return response.json() as Promise<WeatherForecast>
}

export function formatUtcTime(value: string, options?: Intl.DateTimeFormatOptions) {
  return new Intl.DateTimeFormat('en-GB', {
    timeZone: 'UTC',
    hour: '2-digit',
    minute: '2-digit',
    ...options,
  }).format(new Date(value))
}

export function formatNumber(value: number | null, digits = 1) {
  return value === null ? 'Not available' : value.toFixed(digits)
}
