import type { CachedForecast, SiteProfile } from '@/lib/weather'
import { siteKey } from '@/lib/weather'

const databaseName = 'offshore-weather'
const storeName = 'forecasts'
const stationStorageKey = 'offshore-weather:station'

function openDatabase(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(databaseName, 1)

    request.onupgradeneeded = () => {
      request.result.createObjectStore(storeName, { keyPath: 'key' })
    }
    request.onsuccess = () => resolve(request.result)
    request.onerror = () => reject(request.error ?? new Error('Could not open forecast storage.'))
  })
}

export async function readForecast(
  site: Pick<SiteProfile, 'latitude' | 'longitude'>,
): Promise<CachedForecast | undefined> {
  const database = await openDatabase()
  return new Promise((resolve, reject) => {
    const request = database
      .transaction(storeName, 'readonly')
      .objectStore(storeName)
      .get(siteKey(site))

    request.onsuccess = () => {
      database.close()
      resolve(request.result as CachedForecast | undefined)
    }
    request.onerror = () => {
      database.close()
      reject(request.error ?? new Error('Could not read the saved forecast.'))
    }
  })
}

export async function saveForecast(entry: CachedForecast): Promise<void> {
  const database = await openDatabase()
  return new Promise((resolve, reject) => {
    const transaction = database.transaction(storeName, 'readwrite')
    transaction.objectStore(storeName).put(entry)
    transaction.oncomplete = () => {
      database.close()
      resolve()
    }
    transaction.onerror = () => {
      database.close()
      reject(transaction.error ?? new Error('Could not save an offline forecast.'))
    }
    transaction.onabort = () => {
      database.close()
      reject(transaction.error ?? new Error('Saving the offline forecast was aborted.'))
    }
  })
}

export function readSavedStation(): SiteProfile | undefined {
  const raw = localStorage.getItem(stationStorageKey)
  if (!raw) return undefined

  const value: unknown = JSON.parse(raw)
  if (
    typeof value !== 'object' ||
    value === null ||
    !('name' in value) ||
    !('latitude' in value) ||
    !('longitude' in value) ||
    typeof value.name !== 'string' ||
    typeof value.latitude !== 'number' ||
    typeof value.longitude !== 'number'
  ) {
    throw new Error('Saved station details are invalid. Enter the station again.')
  }
  return value as SiteProfile
}

export function saveStation(site: SiteProfile): void {
  localStorage.setItem(stationStorageKey, JSON.stringify(site))
}
