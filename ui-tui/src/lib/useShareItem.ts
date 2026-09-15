import { useEffect } from 'react'

import { $shareItem } from './messagingState.js'

/** The mounted browsing view owns the forwardable selection, never the modal. */
export function useShareItem(title: string, text: string) {
  useEffect(() => {
    const item = title ? { title, text } : null
    $shareItem.set(item)

    return () => {
      if ($shareItem.get() === item) {
        $shareItem.set(null)
      }
    }
  }, [title, text])
}
