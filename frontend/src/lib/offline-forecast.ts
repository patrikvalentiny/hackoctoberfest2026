import { readForecastByKey, saveForecast } from '@/lib/forecast-cache'
import { fetchForecast } from '@/lib/weather'
import type { CachedForecast, SiteProfile } from '@/lib/weather'

export const OFFLINE_FORECAST_HOURS = 72

export async function downloadOfflineForecast(
  siteId: string,
  site: Pick<SiteProfile, 'latitude' | 'longitude'>,
): Promise<CachedForecast> {
  const forecast = await fetchForecast(site)
  const firstHour = Date.parse(forecast.fetched_at)
  const lastHour = firstHour + OFFLINE_FORECAST_HOURS * 60 * 60 * 1000
  const hours = forecast.hours.filter((hour) => {
    const time = Date.parse(hour.time)
    return time >= firstHour && time < lastHour
  })

  if (hours.length === 0) {
    throw new Error('The forecast contains no hourly data to save for the next 3 days.')
  }

  const entry: CachedForecast = {
    key: `site:${siteId}`,
    saved_at: new Date().toISOString(),
    forecast: { ...forecast, hours },
  }
  await saveForecast(entry)
  return entry
}

export function readOfflineForecast(siteId: string) {
  return readForecastByKey(`site:${siteId}`)
}
