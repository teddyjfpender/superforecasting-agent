import { Box, NoSelect, Text } from '@hermes/ink'
import { useStore } from '@nanostores/react'

import { activeNavKey, NAV_TABS, selectNavView } from '../app/navRoutes.js'
import { $overlayState } from '../app/overlayStore.js'
import { $uiState } from '../app/uiStore.js'

// A slim, clickable tab bar across the top of the TUI — browser-style routing
// between the views the app offers. Home is the chat/landing route; Desk,
// Calibration and Agents are the full-screen workspaces; Warnings surfaces the
// open alerts. Each tab toggles the same overlay state the slash commands and
// the `g`-chord hotkeys use (see navRoutes), so clicking and typing stay in sync.

type NavClickEvent = { cellIsBlank?: boolean; stopPropagation?: () => void }

export function NavBar() {
  const overlay = useStore($overlayState)
  const { theme: t } = useStore($uiState)

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
                if (event.cellIsBlank) {
                  return
                }

                event.stopPropagation?.()
                selectNavView(tab.key)
              }}
            >
              {index > 0 ? <Text color={t.color.border}>{'  ·  '}</Text> : null}
              <Text bold={isActive} color={isActive ? t.color.primary : t.color.muted}>
                {tab.label}
              </Text>
            </Box>
          )
        })}
      </Box>
    </NoSelect>
  )
}
