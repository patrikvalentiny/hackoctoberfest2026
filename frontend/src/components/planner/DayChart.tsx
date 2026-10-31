import { useEffect, useRef } from 'react'
import { LineChart } from 'echarts/charts'
import {
  GridComponent,
  MarkAreaComponent,
  MarkLineComponent,
  TooltipComponent,
} from 'echarts/components'
import * as echarts from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import type { EChartsCoreOption } from 'echarts/core'
import { clock } from '@/lib/format'
import type { DayExplanation, HourValue, Limit } from '@/lib/planner'

echarts.use([LineChart, GridComponent, MarkAreaComponent, MarkLineComponent, TooltipComponent, CanvasRenderer])

function token(name: string) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim()
}

function spread(value: HourValue) {
  if (!value) return { low: null, mid: null, high: null }
  if ('value' in value) return { low: null, mid: value.value, high: null }
  return { low: value.p10, mid: value.median, high: value.p90 }
}

// Visibility is in metres; show kilometres so the chart reads like the limits.
function scale(limit: Limit) {
  return limit.unit === 'm' && limit.variable === 'visibility_m' ? 0.001 : 1
}

function unit(limit: Limit) {
  return scale(limit) === 1 ? limit.unit : 'km'
}

function round(value: number | null, factor: number) {
  return value === null ? null : Math.round(value * factor * 100) / 100
}

function niceMax(value: number) {
  const step = value > 20 ? 10 : value > 5 ? 5 : 0.5
  return Math.ceil(value / step) * step
}

function hourIndex(categories: string[], utc: string, roundUp: boolean) {
  const date = new Date(utc)
  if (roundUp && date.getUTCMinutes() > 0) date.setUTCHours(date.getUTCHours() + 1, 0, 0, 0)
  const label = clock(date.toISOString())
  const index = categories.indexOf(label)
  if (index !== -1) return index
  return roundUp ? categories.length - 1 : 0
}

function buildOption(explanation: DayExplanation, transitHours: number): EChartsCoreOption {
  const { hours, limits, day } = explanation
  const categories = hours.map((hour) => clock(hour.time))
  const ink = token('--foreground')
  const muted = token('--muted-foreground')
  const grid = token('--border')
  const deep = token('--depth-5')
  const shoal = token('--depth-2')
  const signal = token('--signal')
  const night = token('--night')
  const rows = limits.length
  const top = 8
  const gap = 34
  const rowHeight = `${(100 - top - 8 - gap * 0.18 * (rows - 1)) / rows}%`

  const window = day.window ?? day.deterministic_window
  const nightAreas: [{ xAxis: number }, { xAxis: number }][] = []
  let start: number | null = null
  hours.forEach((hour, index) => {
    if (!hour.daylight && start === null) start = index
    if ((hour.daylight || index === hours.length - 1) && start !== null) {
      nightAreas.push([{ xAxis: start }, { xAxis: index }])
      start = null
    }
  })

  const windowAreas: [Record<string, unknown>, Record<string, unknown>][] = []
  if (window) {
    const from = hourIndex(categories, window.start.utc, false)
    const to = hourIndex(categories, window.end.utc, true)
    const transit = Math.round(transitHours)
    const workFrom = Math.min(from + transit, to)
    const workTo = Math.max(to - transit, workFrom)
    if (transit > 0) {
      windowAreas.push([
        { xAxis: from, itemStyle: { color: shoal, opacity: 0.55 }, name: 'Transit' },
        { xAxis: workFrom },
      ])
      windowAreas.push([
        { xAxis: workTo, itemStyle: { color: shoal, opacity: 0.55 }, name: 'Transit' },
        { xAxis: to },
      ])
    }
    windowAreas.push([
      { xAxis: workFrom, itemStyle: { color: deep, opacity: 0.16 }, name: 'Work window' },
      { xAxis: workTo },
    ])
  }

  const series: unknown[] = []
  limits.forEach((limit, row) => {
    const factor = scale(limit)
    const values = hours.map((hour) => spread(hour.variables[limit.variable] ?? null))
    const failing: [Record<string, unknown>, Record<string, unknown>][] = []
    hours.forEach((hour, index) => {
      if ((hour.members_failing[limit.id] ?? 0) * 2 > day.members) {
        failing.push([
          { xAxis: index, itemStyle: { color: signal, opacity: 0.14 } },
          { xAxis: Math.min(index + 1, categories.length - 1) },
        ])
      }
    })
    const axis = { xAxisIndex: row, yAxisIndex: row }

    series.push({
      ...axis,
      name: `${limit.id}-low`,
      type: 'line',
      data: values.map((value) => round(value.low, factor)),
      stack: limit.id,
      lineStyle: { opacity: 0 },
      symbol: 'none',
      silent: true,
      tooltip: { show: false },
    })
    series.push({
      ...axis,
      name: `${limit.id}-band`,
      type: 'line',
      data: values.map((value) =>
        value.low === null || value.high === null ? null : round(value.high - value.low, factor),
      ),
      stack: limit.id,
      lineStyle: { opacity: 0 },
      areaStyle: { color: deep, opacity: 0.18 },
      symbol: 'none',
      silent: true,
      tooltip: { show: false },
    })
    series.push({
      ...axis,
      name: limit.label,
      type: 'line',
      data: values.map((value) => round(value.mid, factor)),
      lineStyle: { color: deep, width: 2 },
      itemStyle: { color: deep },
      symbol: 'none',
      markArea: {
        silent: true,
        label: { show: false },
        data: [
          ...nightAreas.map(([a, b]) => [
            { ...a, itemStyle: { color: night, opacity: 1 } },
            b,
          ]),
          ...windowAreas,
          ...failing,
        ],
      },
      markLine: {
        silent: true,
        symbol: 'none',
        lineStyle: { color: signal, type: 'dashed', width: 1.5 },
        label: {
          color: signal,
          position: 'insideEndTop',
          formatter: `${limit.comparison === 'max' ? 'max' : 'min'} ${round(limit.value, factor)} ${unit(limit)}`,
        },
        data: [{ yAxis: round(limit.value, factor) }],
      },
    })
  })

  return {
    animation: false,
    textStyle: { fontFamily: token('--font-sans') || 'sans-serif', color: ink },
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'line', link: [{ xAxisIndex: 'all' }] },
      formatter: (items: { dataIndex: number }[]) => {
        const index = items[0]?.dataIndex
        if (index === undefined) return ''
        const hour = hours[index]
        const lines = limits.map((limit) => {
          const value = spread(hour.variables[limit.variable] ?? null)
          const factor = scale(limit)
          const range =
            value.low !== null && value.high !== null
              ? ` (${round(value.low, factor)}–${round(value.high, factor)})`
              : ''
          const failing = hour.members_failing[limit.id] ?? 0
          return `${limit.label}: <b>${round(value.mid, factor) ?? '–'} ${unit(limit)}</b>${range}<br/><span style="color:${muted}">${failing} of ${day.members} members over the limit</span>`
        })
        return `<b>${categories[index]}</b>${hour.daylight ? '' : ', dark'}<br/>${lines.join('<br/>')}`
      },
    },
    axisPointer: { link: [{ xAxisIndex: 'all' }] },
    grid: limits.map((_, row) => ({
      left: 48,
      right: 16,
      top: `${top + row * (100 - top) / rows}%`,
      height: rowHeight,
    })),
    xAxis: limits.map((_, row) => ({
      type: 'category',
      gridIndex: row,
      data: categories,
      boundaryGap: false,
      axisLine: { lineStyle: { color: grid } },
      axisTick: { show: false },
      axisLabel: { show: row === rows - 1, color: muted, interval: 2 },
    })),
    yAxis: limits.map((limit, row) => ({
      type: 'value',
      gridIndex: row,
      name: `${limit.label} (${unit(limit)})`,
      nameLocation: 'end',
      nameGap: 8,
      nameTextStyle: { align: 'left', color: ink, fontWeight: 600 },
      splitNumber: 2,
      splitLine: { lineStyle: { color: grid } },
      axisLabel: { color: muted },
      max: (extent: { max: number }) =>
        niceMax(Math.max(extent.max, limit.value * scale(limit)) * 1.15),
      min: 0,
    })),
    series,
  }
}

export function DayChart({
  explanation,
  transitHours,
}: {
  explanation: DayExplanation
  transitHours: number
}) {
  const element = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!element.current) return
    const chart = echarts.init(element.current)
    const draw = () => chart.setOption(buildOption(explanation, transitHours), true)
    draw()
    const observer = new ResizeObserver(() => chart.resize())
    observer.observe(element.current)
    const scheme = window.matchMedia('(prefers-color-scheme: dark)')
    scheme.addEventListener('change', draw)
    return () => {
      observer.disconnect()
      scheme.removeEventListener('change', draw)
      chart.dispose()
    }
  }, [explanation, transitHours])

  return (
    <div
      ref={element}
      className="h-[26rem] w-full"
      role="img"
      aria-label="Hourly forecast against each limit, with daylight, transit and the work window"
    />
  )
}
