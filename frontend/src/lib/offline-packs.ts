const databaseName = 'harbour-pulse'
const storeName = 'briefing-packs'

function openDatabase(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(databaseName, 1)
    request.onupgradeneeded = () => {
      request.result.createObjectStore(storeName)
    }
    request.onsuccess = () => resolve(request.result)
    request.onerror = () => reject(request.error ?? new Error('Could not open offline briefing storage.'))
  })
}

export async function saveBriefingPack(profileId: string, pack: Record<string, unknown>) {
  const database = await openDatabase()
  return new Promise<void>((resolve, reject) => {
    const transaction = database.transaction(storeName, 'readwrite')
    transaction.objectStore(storeName).put(pack, profileId)
    transaction.oncomplete = () => {
      database.close()
      resolve()
    }
    transaction.onerror = () => {
      database.close()
      reject(transaction.error ?? new Error('Could not save the offline briefing pack.'))
    }
    transaction.onabort = () => {
      database.close()
      reject(transaction.error ?? new Error('Saving the offline briefing pack was aborted.'))
    }
  })
}

export async function readBriefingPack(profileId: string) {
  const database = await openDatabase()
  return new Promise<Record<string, unknown> | undefined>((resolve, reject) => {
    const request = database.transaction(storeName, 'readonly').objectStore(storeName).get(profileId)
    request.onsuccess = () => {
      database.close()
      resolve(request.result as Record<string, unknown> | undefined)
    }
    request.onerror = () => {
      database.close()
      reject(request.error ?? new Error('Could not read the saved briefing pack.'))
    }
  })
}
