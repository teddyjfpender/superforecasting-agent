import { useEffect } from 'react'

import type { FeedShare } from '../protocol/generated.js'

import { $shareItem } from './messagingState.js'

/** The mounted browsing view owns the forwardable selection, never the modal. */
export function useShareItem(title: string, text: string, feed?: FeedShare | null, chartUnavailable?: string) {
  useEffect(() => {
    const item = title ? { title, text, feed, chartUnavailable } : null
    $shareItem.set(item)

    return () => {
      if ($shareItem.get() === item) {
        $shareItem.set(null)
      }
    }
  }, [title, text, feed, chartUnavailable])
}
