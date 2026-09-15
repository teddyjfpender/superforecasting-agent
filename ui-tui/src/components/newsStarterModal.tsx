import { Box, Text } from '@superforecasting/ink'

import { normalizeFeedUrl } from '../lib/newsFeedStore.js'
import type { NewsSubscription } from '../protocol/generated.js'
import type { Theme } from '../theme.js'

import { ModalOverlay } from './modalOverlay.js'

export function NewsStarterModal({
  feeds,
  existing,
  choice,
  busy,
  cols,
  rows,
  t,
  onChoose,
  onApply
}: {
  feeds: NewsSubscription[]
  existing: Set<string>
  choice: number
  busy: boolean
  cols: number
  rows: number
  t: Theme
  onChoose: (choice: number) => void
  onApply: () => void
}) {
  const missing = feeds.filter(feed => !existing.has(normalizeFeedUrl(feed.url))).length
  const categories = [...new Set(feeds.map(feed => feed.category))]

  return (
    <ModalOverlay cols={cols} maxHeight={24} maxWidth={100} rows={rows} t={t}>
      <Box flexDirection="column" flexGrow={1} minHeight={0}>
        <Text bold color={t.color.primary}>
          Start your news desk
        </Text>
        <Box marginTop={1}>
          <Text wrap="wrap">
            {missing} new feeds ({feeds.length - missing} already subscribed) across {categories.join(', ')}.
          </Text>
        </Box>
        <Box marginTop={1}>
          <Text color={t.color.muted}>
            Adds missing feeds and preserves your subscriptions. Publisher access terms apply; paid wire access is not
            included.
          </Text>
        </Box>
        <Box marginTop={1}>
          <Text bold color={choice === 0 ? t.color.accent : t.color.text} onClick={() => onChoose(0)}>
            {choice === 0 ? '▸ ' : '  '}Load global starter
          </Text>
        </Box>
        {!existing.size ? (
          <Text color={choice === 1 ? t.color.accent : t.color.text} onClick={() => onChoose(1)}>
            {choice === 1 ? '▸ ' : '  '}Start empty
          </Text>
        ) : null}
        <Box flexGrow={1} />
        <Box flexShrink={0} justifyContent="space-between">
          <Text color={t.color.muted}>↑↓ Choose · Esc Cancel</Text>
          <Text bold color={t.color.accent} onClick={onApply}>
            {busy ? 'Saving…' : 'Enter Apply selection'}
          </Text>
        </Box>
      </Box>
    </ModalOverlay>
  )
}
