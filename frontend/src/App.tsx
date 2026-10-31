import { useEffect, useState } from 'react'
import { WifiHigh, WifiSlash } from '@phosphor-icons/react'
import { TechnicianView } from '@/components/technician/TechnicianView'

const DEMO_CLOCK_KEY = 'harbour-pulse:demo-clock'

function localClock(timestamp: number) {
  return new Intl.DateTimeFormat('en-GB', {
    timeZone: 'Europe/Copenhagen',
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23',
  }).format(new Date(timestamp))
}

function readDemoClock(): string | null {
  try {
    const saved = localStorage.getItem(DEMO_CLOCK_KEY)
    return saved && /^\d{2}:\d{2}$/.test(saved) ? saved : null
  } catch {
    return null
  }
}

function simulatedNow(realNow: number, clock: string | null) {
  if (!clock) return realNow
  const [hour, minute] = clock.split(':').map(Number)
  if (hour > 23 || minute > 59) return realNow
  const actual = localClock(realNow).split(':').map(Number)
  const differenceMinutes = hour * 60 + minute - (actual[0] * 60 + actual[1])
  return realNow + differenceMinutes * 60_000
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

function App() {
  const online = useOnline()
  const localAiReady = 'gpu' in navigator
  const [realNow, setRealNow] = useState(() => Date.now())
  const [demoClock, setDemoClock] = useState(readDemoClock)
  const now = simulatedNow(realNow, demoClock)

  useEffect(() => {
    const timer = setInterval(() => setRealNow(Date.now()), 10_000)
    return () => clearInterval(timer)
  }, [])

  function changeDemoClock(value: string | null) {
    setDemoClock(value)
    try {
      if (value) localStorage.setItem(DEMO_CLOCK_KEY, value)
      else localStorage.removeItem(DEMO_CLOCK_KEY)
    } catch {
      // The demo clock remains available until the page is reloaded.
    }
  }

  return (
    <div className="min-h-dvh bg-background">
      <header className="technician-header sticky top-0 z-20 flex flex-wrap items-center justify-between gap-3 px-4 py-3 text-white sm:px-7">
        <div className="flex items-baseline gap-3">
          <h1 className="font-display text-xl font-bold tracking-tight sm:text-2xl">Harbour Pulse</h1>
          <p className="hidden text-sm text-white/65 sm:block">Offshore field briefing</p>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <label htmlFor="demo-clock" className="flex items-center gap-2 rounded-md border border-white/15 bg-white/5 px-2.5 py-1.5 text-xs text-white/75">
            Demo time
            <input
              id="demo-clock"
              type="time"
              value={demoClock ?? localClock(realNow)}
              onChange={(event) => changeDemoClock(event.target.value || null)}
              aria-label="Set the demo time in Copenhagen"
              className="h-7 w-24 rounded bg-transparent px-1 text-sm tabular-nums text-white outline-none focus-visible:ring-2 focus-visible:ring-white/60"
            />
          </label>
          {demoClock && (
            <button
              type="button"
              onClick={() => changeDemoClock(null)}
              className="rounded px-2 py-1 text-xs text-white/75 outline-none hover:bg-white/10 focus-visible:ring-2 focus-visible:ring-white/60"
            >
              Live time
            </button>
          )}
          <p className="inline-flex items-center gap-2 rounded-full border border-white/15 px-3 py-1.5 text-xs text-white/75">
            <span className={online ? 'size-2 rounded-full bg-emerald-400' : 'size-2 rounded-full bg-amber-300'} aria-hidden />
            {online ? <WifiHigh aria-hidden /> : <WifiSlash aria-hidden />}
            {online ? 'Connected' : 'Offline'}
          </p>
          <p className="inline-flex items-center gap-2 rounded-full border border-white/15 bg-white/5 px-3 py-1.5 text-[11px] font-medium tracking-wide text-white/80 uppercase">
            <span className={localAiReady ? 'size-2 rounded-full bg-cyan-400' : 'size-2 rounded-full bg-amber-300'} aria-hidden />
            {localAiReady ? 'Local AI ready' : 'WebGPU required'}
          </p>
        </div>
      </header>

      <main className="mx-auto w-full max-w-[1480px] px-4 py-5 sm:px-7 sm:py-7">
        <TechnicianView
          online={online}
          now={now}
          wallNow={realNow}
          demoTimeActive={demoClock !== null}
        />
      </main>

      <footer className="border-t px-4 py-3 text-center text-xs text-muted-foreground sm:px-7">
        Prototype decision support · Forecasts are not observations · Follow site-approved procedures and the vessel master’s instructions
      </footer>
    </div>
  )
}

export default App
