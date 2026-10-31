import { DayChart } from '@/components/planner/DayChart'
import { clock, confidenceLabel, dateTime, limitNames, longDate, percent } from '@/lib/format'
import type { DayExplanation } from '@/lib/planner'

function Fact({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="min-w-0">
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="mt-0.5 font-display text-lg leading-tight font-semibold tabular-nums">{children}</dd>
    </div>
  )
}

export function DayDetail({
  explanation,
  transitHours,
}: {
  explanation: DayExplanation
  transitHours: number
}) {
  const { day } = explanation
  const window = day.window ?? day.deterministic_window
  const limiting = day.limiting_parameter
  const failures = Object.entries(day.limit_failures).filter(([, count]) => count > 0)

  return (
    <section aria-labelledby="day-title" className="grid gap-4">
      <header className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <h2 id="day-title" className="font-display text-2xl font-semibold">
          {longDate(day.date)}
        </h2>
        <p className="text-sm text-muted-foreground">{confidenceLabel[day.confidence]}</p>
      </header>

      <dl className="grid grid-cols-2 gap-x-6 gap-y-3 sm:grid-cols-4">
        <Fact label="Chance of a window">
          {day.confidence === 'outlook' ? 'Outlook only' : percent(day.probability)}
          {day.members_with_window !== null && (
            <span className="ml-1.5 text-xs font-normal text-muted-foreground">
              {day.members_with_window} of {day.members} members
            </span>
          )}
        </Fact>
        <Fact label={transitHours > 0 ? 'Window incl. transit' : 'Window'}>
          {window ? `${clock(window.start)}–${clock(window.end)}` : 'None found'}
        </Fact>
        <Fact label="Daylight">
          {clock(day.sunrise)}–{clock(day.sunset)}
        </Fact>
        <Fact label="Recompute">
          {day.recompute_at ? dateTime(day.recompute_at) : 'Within DMI horizon'}
        </Fact>
      </dl>

      {limiting && (
        <p className="limiting rounded-md px-3 py-2 text-sm">
          <strong>{limitNames[limiting] ?? limiting}</strong> is what can cancel this day
          {failures.length > 0 && (
            <>
              {' '}
              (members failing:{' '}
              {failures.map(([id, count]) => `${limitNames[id] ?? id} ${count}`).join(', ')})
            </>
          )}
          .
        </p>
      )}
      {day.note && <p className="text-sm text-muted-foreground">{day.note}</p>}

      {explanation.hours.length > 0 ? (
        <>
          <DayChart explanation={explanation} transitHours={transitHours} />
          <p className="text-xs leading-relaxed text-muted-foreground">
            Line: median. Band: 10th–90th percentile of ensemble members. Dashed: limit. Grey: dark.
            Light blue: transit. Blue: work. Orange: over half the members break that limit.
          </p>
        </>
      ) : (
        <p className="text-sm text-muted-foreground">
          No hourly forecast reaches this day. The engine only gives a weekly outlook here.
        </p>
      )}
    </section>
  )
}
