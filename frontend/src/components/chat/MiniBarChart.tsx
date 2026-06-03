/** Inline horizontal bar chart — top regions for the current choropleth measure. */

import type { ChartDataPoint } from '../../types'

interface Props {
  data: ChartDataPoint[]
  measureCode: string
}

function shortName(name: string): string {
  return name.length > 22 ? name.slice(0, 20) + '…' : name
}

/** Extract the unit suffix from a formatted label like "1.234 m³" → "m³", "€ 45.000" → "€", "2,3 km" → "km" */
function extractUnit(label: string): string {
  // Prefix currency symbols
  const prefixMatch = label.match(/^([€$£¥])/)
  if (prefixMatch) return prefixMatch[1]
  // Suffix units: strip leading number/comma/dot/space, take the rest
  const suffixMatch = label.match(/[\d.,\s]+(.+)$/)
  if (suffixMatch) return suffixMatch[1].trim()
  return ''
}

export function MiniBarChart({ data, measureCode }: Props) {
  if (!data.length) return null

  const maxVal  = data[0].value  // already sorted desc
  const unit    = data[0].label ? extractUnit(data[0].label) : ''
  const ROW_H   = 22
  const LABEL_W = 110
  const VALUE_W = 52            // wider to fit formatted labels with units
  const BAR_W   = 150
  const PAD     = 8
  const height  = data.length * ROW_H + PAD * 2

  return (
    <div className="mt-2.5 rounded-xl border border-gray-100 dark:border-gray-700
                    bg-gray-50 dark:bg-gray-800/60 overflow-hidden">
      {/* Header */}
      <div className="px-3 pt-2 pb-1 flex items-center justify-between gap-2">
        <span className="font-display text-[10px] font-medium uppercase tracking-wider"
              style={{ color: '#878787' }}>
          Top {data.length}
        </span>
        <span className="text-[10px] truncate" style={{ color: '#878787' }}>
          {measureCode.replace(/_\d+$/, '').replace(/([A-Z])/g, ' $1').trim()}
          {unit && <span className="ml-1 font-medium" style={{ color: '#271D6C' }}>({unit})</span>}
        </span>
      </div>

      {/* SVG chart */}
      <svg
        width="100%"
        viewBox={`0 0 ${LABEL_W + BAR_W + VALUE_W + PAD * 3} ${height}`}
        className="block"
        preserveAspectRatio="xMidYMid meet"
      >
        {data.map((d, i) => {
          const y   = PAD + i * ROW_H
          const bar = maxVal > 0 ? (d.value / maxVal) * BAR_W : 0
          const cx  = LABEL_W + PAD

          return (
            <g key={d.name}>
              {/* Region name */}
              <text
                x={LABEL_W - 4}
                y={y + ROW_H * 0.65}
                textAnchor="end"
                fill="#878787"
                style={{ fontSize: 9.5, fontFamily: 'Akko Pro, system-ui, sans-serif' }}
              >
                {shortName(d.name)}
              </text>

              {/* Bar background */}
              <rect
                x={cx}
                y={y + 4}
                width={BAR_W}
                height={ROW_H - 8}
                rx={2}
                fill="#E9E9E9"
              />

              {/* Bar fill */}
              {bar > 0 && (
                <rect
                  x={cx}
                  y={y + 4}
                  width={Math.max(bar, 2)}
                  height={ROW_H - 8}
                  rx={2}
                  fill={d.color}
                  opacity={0.88}
                />
              )}

              {/* Value label — use pre-formatted label with unit */}
              <text
                x={cx + BAR_W + 5}
                y={y + ROW_H * 0.65}
                textAnchor="start"
                fill="#091D23"
                style={{ fontSize: 9, fontFamily: 'Akko Pro, system-ui, sans-serif', fontVariantNumeric: 'tabular-nums' }}
              >
                {d.label || String(d.value)}
              </text>
            </g>
          )
        })}
      </svg>
    </div>
  )
}
