import { useStore } from '@nanostores/react'
import { Box, NoSelect, Text } from '@superforecasting/ink'
import { useEffect, useState } from 'react'

import { activeNavKey, canOpenGlobalOverlay, NAV_TABS, selectNavView } from '../app/navRoutes.js'
import { $globalModal, $overlayState } from '../app/overlayStore.js'
import { $uiState } from '../app/uiStore.js'
import { openQuickMessage } from '../lib/messagingState.js'
import { signalUnread, signalVersion, subscribeSignal } from '../lib/signalLive.js'

// A slim, clickable tab bar across the top of the TUI — browser-style routing
// between the views the app offers. Home is the chat/landing route; Desk,
// Calibration and Agents are the full-screen workspaces; Warnings surfaces the
// open alerts. Each tab toggles the same overlay state the slash commands and
// the `g`-chord hotkeys use (see navRoutes), so clicking and typing stay in sync.

type NavClickEvent = { cellIsBlank?: boolean; stopPropagation?: () => void }

export function NavBar() {
  const overlay = useStore($overlayState)
  const blocked = useStore($globalModal)
  const { theme: t } = useStore($uiState)

  const [, setVersion] = useState(signalVersion())
  useEffect(() => subscribeSignal(() => setVersion(signalVersion())), [])
  const unread = signalUnread().size
  const active = activeNavKey(overlay)

  return (
    <NoSelect flexShrink={0} paddingX={1}>
      <Box>
        {NAV_TABS.map((tab, index) => {
          const isActive = tab.key === active

          return (
            <Box
              key={tab.key}
              onClick={(event: NavClickEvent) => {
                if (blocked || event.cellIsBlank) {
                  return
                }

                event.stopPropagation?.()
                selectNavView(tab.key)
              }}
            >
              {index > 0 ? <Text color={t.color.border}>{'  ·  '}</Text> : null}
              <Text bold={isActive} color={isActive ? t.color.primary : t.color.muted}>
                {tab.label}
                {tab.key === 'messaging' && unread > 0 ? ` (${unread})` : ''}
              </Text>
            </Box>
          )
        })}
        <Box
          marginLeft={2}
          onClick={() => {
            if (!blocked && canOpenGlobalOverlay(overlay)) {
              openQuickMessage()
            }
          }}
        >
          <Text color={t.color.accent}>[⌥m Message]</Text>
        </Box>
      </Box>
    </NoSelect>
  )
}
