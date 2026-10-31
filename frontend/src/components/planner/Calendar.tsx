import { cn } from '@/lib/utils'
import { clock, confidenceLabel, dayMonth, limitNames, percent, weekday } from '@/lib/format'
import type { Day } from '@/lib/planner'

const weekdays = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

// Probability is drawn like depth on a sea chart: the deeper the colour, the
// more ensemble members have a workable window.
function depth(probability: number | null) {
  if (probability === null) return 0
  return Math.min(5, Math.floor(probability * 5) + 1)
}

function leadingBlanks(date: string) {
  const day = new Date(`${date}T12:00:00Z`).getUTCDay()
  return (day + 6) % 7
}

export function Calendar({
  days,
  suggested,
  selected,
  onSelect,
}: {
  days: Day[]
  suggested: string[]
  selected?: string
  onSelect: (date: string) => void
}) {
  if (days.length === 0) return null
  const blanks = leadingBlanks(days[0].date)

  return (
    <div>
      <div className="grid grid-cols-7 gap-1.5 sm:gap-2">
        {weekdays.map((name) => (
          <div key={name} className="px-1 text-xs text-muted-foreground">
            {name}
          </div>
        ))}
        {Array.from({ length: blanks }, (_, index) => (
          <div key={`blank-${index}`} aria-hidden />
        ))}
        {days.map((day) => {
          const level = depth(day.probability)
          const outlook = day.confidence === 'outlook'
          const isSuggested = suggested.includes(day.date)
          const limiting = day.limiting_parameter && limitNames[day.limiting_parameter]
          return (
            <button
              key={day.date}
              type="button"
              onClick={() => onSelect(day.date)}
              aria-pressed={selected === day.date}
              aria-label={`${weekday(day.date)} ${dayMonth(day.date)}, ${
                outlook ? 'outlook only' : `${percent(day.probability)} chance of a window`
              }, ${confidenceLabel[day.confidence]}${isSuggested ? ', suggested' : ''}`}
              className={cn(
                'day-tile relative flex aspect-[5/6] min-w-0 flex-col justify-between overflow-hidden rounded-md p-1.5 text-left outline-none sm:aspect-auto sm:h-24 sm:p-2.5',
                'focus-visible:ring-3 focus-visible:ring-ring/60',
                outlook ? 'day-outlook' : `depth-${level}`,
                `conf-${day.confidence}`,
                selected === day.date && 'day-selected',
              )}
            >
              <span className="relative flex items-baseline justify-between gap-1 text-[0.7rem] leading-none sm:text-xs">
                <span className="truncate">{dayMonth(day.date)}</span>
                {isSuggested && <span className="suggested-mark" aria-hidden />}
              </span>
              <span className="relative">
                <span className="block font-display text-xl leading-none font-semibold tabular-nums sm:text-3xl">
                  {outlook ? '~' : percent(day.probability)}
                </span>
                <span className="mt-1 hidden truncate text-[0.7rem] leading-tight sm:block">
                  {outlook
                    ? 'Outlook'
                    : day.window
                      ? `${clock(day.window.start)}–${clock(day.window.end)}`
                      : limiting
                        ? `${limiting} limits`
                        : 'No window'}
                </span>
              </span>
            </button>
          )
        })}
      </div>

      <dl className="mt-3 flex flex-wrap items-center gap-x-5 gap-y-2 text-xs text-muted-foreground">
        <div className="flex items-center gap-2">
          <dt className="flex overflow-hidden rounded-sm">
            {[1, 2, 3, 4, 5].map((level) => (
              <span key={level} className={`depth-${level} block h-3 w-4`} />
            ))}
          </dt>
          <dd>Chance of a work window, 0 to 100%</dd>
        </div>
        <div className="flex items-center gap-2">
          <dt className="depth-3 conf-low block h-3 w-6 rounded-sm" />
          <dd>Hatching: lower confidence</dd>
        </div>
        <div className="flex items-center gap-2">
          <dt className="day-outlook block h-3 w-6 rounded-sm" />
          <dd>Days 16–21, outlook only</dd>
        </div>
        <div className="flex items-center gap-2">
          <dt className="suggested-mark" />
          <dd>Suggested by the engine</dd>
        </div>
      </dl>
    </div>
  )
}
