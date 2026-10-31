import type { ForecastHour } from '@/lib/weather'
import { TIME_ZONE } from '@/lib/format'

export type TechnicianTask = {
  id: string
  time: string
  durationMinutes: number
  title: string
  area: string
  weatherWatch: string
}

export const technicianTasks: TechnicianTask[] = [
  {
    id: 'transfer',
    time: '07:30',
    durationMinutes: 45,
    title: 'Vessel transfer & turbine access',
    area: 'Access',
    weatherWatch: 'Wave height, period and vessel motion',
  },
  {
    id: 'walkdown',
    time: '08:30',
    durationMinutes: 30,
    title: 'Turbine condition walkdown',
    area: 'Tower',
    weatherWatch: 'Wind, rain and visibility on exposed areas',
  },
  {
    id: 'drivetrain',
    time: '09:15',
    durationMinutes: 90,
    title: 'Drivetrain & nacelle inspection',
    area: 'Nacelle',
    weatherWatch: 'Wind limits for work at height',
  },
  {
    id: 'hydraulics',
    time: '11:15',
    durationMinutes: 75,
    title: 'Hydraulic and cooling-system service',
    area: 'Nacelle',
    weatherWatch: 'Wind and safe access; follow task-specific procedures',
  },
  {
    id: 'sensors',
    time: '13:00',
    durationMinutes: 60,
    title: 'Control & condition-monitoring checks',
    area: 'Nacelle',
    weatherWatch: 'Stable access; check alarms and work permits',
  },
  {
    id: 'return',
    time: '15:00',
    durationMinutes: 45,
    title: 'Return transfer & close-out',
    area: 'Access',
    weatherWatch: 'Reassess sea state and vessel transfer conditions',
  },
]

function localDate(timestamp: string) {
  return new Intl.DateTimeFormat('en-CA', { timeZone: TIME_ZONE }).format(new Date(timestamp))
}

function localMinute(timestamp: string) {
  const parts = new Intl.DateTimeFormat('en-GB', {
    timeZone: TIME_ZONE,
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23',
  }).formatToParts(new Date(timestamp))
  return Number(parts.find((part) => part.type === 'hour')?.value) * 60
    + Number(parts.find((part) => part.type === 'minute')?.value)
}

export function taskForecastHours(
  task: TechnicianTask,
  date: string,
  forecastHours: ForecastHour[],
) {
  const [startHour, startMinute] = task.time.split(':').map(Number)
  const start = startHour * 60 + startMinute
  const end = start + task.durationMinutes
  return forecastHours.filter((hour) => {
    if (localDate(hour.time) !== date) return false
    const pointStart = localMinute(hour.time)
    return pointStart < end && pointStart + 60 > start
  })
}

export function formatTaskForecast(hour: ForecastHour) {
  const readings = [
    hour.wind_speed_kn === null ? null : `10 m wind ${hour.wind_speed_kn.toFixed(0)} kn`,
    hour.wind_gusts_kn === null ? null : `gusts ${hour.wind_gusts_kn.toFixed(0)} kn`,
    hour.wave_height_m === null ? null : `waves ${hour.wave_height_m.toFixed(1)} m`,
    hour.wave_period_s === null ? null : `wave period ${hour.wave_period_s.toFixed(0)} s`,
    hour.visibility_m === null ? null : `visibility ${(hour.visibility_m / 1000).toFixed(1)} km`,
    hour.precipitation_probability_pct === null
      ? null
      : `precipitation chance ${hour.precipitation_probability_pct.toFixed(0)}%`,
  ].filter((reading): reading is string => reading !== null)
  const time = new Intl.DateTimeFormat('en-GB', {
    timeZone: TIME_ZONE,
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date(hour.time))
  return `${time}: ${readings.length ? readings.join(', ') : 'forecast readings unavailable'}`
}

export function taskWindowLabel(task: TechnicianTask) {
  const end = Number(task.time.slice(0, 2)) * 60
    + Number(task.time.slice(3, 5))
    + task.durationMinutes
  return `${task.time}–${String(Math.floor(end / 60) % 24).padStart(2, '0')}:${String(end % 60).padStart(2, '0')}`
}
