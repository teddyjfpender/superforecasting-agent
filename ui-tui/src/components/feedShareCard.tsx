import { Box, Text } from '@superforecasting/ink'

import { feedChartLines } from '../lib/feedShareChart.js'
import type { FeedShare } from '../protocol/generated.js'
import type { Theme } from '../theme.js'

/** A sender-supplied snapshot, never automatically fetched or trusted as evidence. */
export function FeedShareCard({
  share,
  width,
  t,
  compact = false,
  chartHeight = 5
}: {
  share: FeedShare
  width: number
  t: Theme
  compact?: boolean
  chartHeight?: number
}) {
  return (
    <Box flexDirection="column" flexShrink={0} width={Math.max(12, width)}>
      {share.feeds.map(feed => (
        <Box flexDirection="column" flexShrink={0} key={`${feed.provider}:${feed.symbol}`}>
          <Text bold color={t.color.accent} wrap="truncate-end">
            {feed.name}
          </Text>
          <Text color={t.color.text} wrap="truncate-end">
            {feed.points.at(-1)?.value ?? '—'} {feed.unit} · {feed.provider}:{feed.symbol}
          </Text>
          {!compact && (
            <Text color={t.color.muted} wrap="truncate-end">
              Shared snapshot · {feed.kind} · {feed.revision_policy}
            </Text>
          )}
          {feedChartLines(feed.points, share.presentation, Math.max(4, width - 2), chartHeight).map(
            (line, i, lines) => (
              <Text color={i === 0 || i === lines.length - 1 ? t.color.muted : t.color.accent} key={i}>
                {line}
              </Text>
            )
          )}
          <Text color={t.color.muted} wrap="truncate-end">
            {feed.points[0]?.start} → {feed.points.at(-1)?.end} · {feed.points.length} observations
          </Text>
          {!compact && (
            <Text color={t.color.muted} wrap="truncate-end">
              {feed.retrieved_at ? `Retrieved ${feed.retrieved_at}` : 'Retrieval time unknown'}
            </Text>
          )}
          {!compact && feed.source_url ? (
            <Text color={t.color.muted} wrap="truncate-end">
              {feed.source_url}
            </Text>
          ) : null}
        </Box>
      ))}
    </Box>
  )
}
