import { stringWidth } from '@superforecasting/ink'

export interface MarketColumn {
  align: 'left' | 'right'
  key: string
  label: string
  w: number
}

/** Keep numeric cells stable; names receive the surplus, trends stay compact. */
export function marketColumns(available: number, hasVolume: boolean) {
  const columns: MarketColumn[] = [
    { key: 'sym', label: 'SYMBOL', align: 'left', w: 9 },
    { key: 'name', label: 'NAME', align: 'left', w: available < 54 ? 12 : 18 },
    { key: 'last', label: 'LAST', align: 'right', w: available < 54 ? 9 : 12 },
    { key: 'chg', label: 'CHG', align: 'right', w: available < 54 ? 9 : 11 },
    { key: 'pct', label: 'CHG%', align: 'right', w: 10 },
    { key: 'vol', label: 'VOL', align: 'right', w: 10 }
  ]

  const keep = new Set<string>()
  let used = 2 // selection marker

  for (const key of ['name', 'last', 'chg', 'pct', 'sym', ...(hasVolume ? ['vol'] : [])]) {
    const column = columns.find(item => item.key === key)!

    if (used + column.w + 1 <= available) {
      keep.add(key)
      used += column.w + 1
    }
  }

  const kept = columns.filter(column => keep.has(column.key))
  const remaining = Math.max(0, available - used)
  const trendWidth = remaining >= 12 ? 12 : 0
  const name = kept.find(column => column.key === 'name')

  if (name) {
    name.w += remaining - trendWidth
  }

  return { columns: kept, trendWidth }
}

/** A width-budgeted topic window, with the active topic always visible. */
export function marketTopicWindow(topics: readonly string[], active: number, available: number) {
  if (!topics.length) {
    return { start: 0, end: 0 }
  }

  let start = Math.min(Math.max(0, active), topics.length - 1)
  let end = start + 1
  let used = stringWidth(topics[start])

  while (end - start < 9) {
    const left = start > 0 ? stringWidth(topics[start - 1]) + 5 : Infinity
    const right = end < topics.length ? stringWidth(topics[end]) + 5 : Infinity
    const preferLeft = active - start < end - active - 1

    if ((preferLeft && used + left <= available) || (used + right > available && used + left <= available)) {
      start -= 1
      used += left
    } else if (used + right <= available) {
      end += 1
      used += right
    } else {
      break
    }
  }

  return { start, end }
}
