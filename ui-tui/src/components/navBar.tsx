import { Box, NoSelect, Text } from '@hermes/ink'
import { useStore } from '@nanostores/react'

import { $overlayState, patchOverlayState } from '../app/overlayStore.js'
import { $uiState } from '../app/uiStore.js'

// A slim, clickable tab bar across the top of the TUI — browser-style routing
// between the views the app offers. Home is the chat/landing route; Desk,
// Calibration and Agents are the full-screen workspaces; Warnings surfaces the
// open alerts. Each tab toggles the same overlay state the slash commands use,
// so clicking and typing `/forecast desk` etc. stay in sync.

type NavClickEvent = { cellIsBlank?: boolean; stopPropagation?: () => void }

type NavTab = { key: string; label: string }

const NAV_TABS: NavTab[] = [
  { key: 'home', label: 'Home' },
  { key: 'desk', label: 'Desk' },
  { key: 'warnings', label: 'Warnings' },
  { key: 'calibration', label: 'Calibration' },
  { key: 'agents', label: 'Agents' },
  { key: 'help', label: 'Help' }
]

// Clearing every view flag returns to the chat/home route.
const HOME_PATCH = {
  agents: false,
  alerts: false,
  calibration: false,
  forecasts: false,
  forecastsInitialId: null,
  help: false
} as const

export function NavBar() {
  const overlay = useStore($overlayState)
  const { theme: t } = useStore($uiState)

  // Which tab is the active route.
  const active = overlay.forecasts
    ? 'desk'
    : overlay.calibration
      ? 'calibration'
      : overlay.alerts
        ? 'warnings'
        : overlay.agents
          ? 'agents'
          : overlay.help
            ? 'help'
            : 'home'

  const select = (key: string) => {
    switch (key) {
      case 'home':
        return patchOverlayState({ ...HOME_PATCH })

      case 'desk':
        return patchOverlayState({ ...HOME_PATCH, forecasts: true })

      case 'warnings':
        return patchOverlayState({ ...HOME_PATCH, alerts: true })

      case 'calibration':
        return patchOverlayState({ ...HOME_PATCH, calibration: true })

      case 'agents':
        return patchOverlayState({ ...HOME_PATCH, agents: true, agentsInitialHistoryIndex: 0 })

      case 'help':
        return patchOverlayState({ ...HOME_PATCH, help: true })
    }
  }

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
                select(tab.key)
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
