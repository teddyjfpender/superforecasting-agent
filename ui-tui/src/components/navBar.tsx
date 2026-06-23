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
  { key: 'markets', label: 'Markets' },
  { key: 'news', label: 'News' },
  { key: 'messaging', label: 'Messaging' },
  { key: 'calendar', label: 'Calendar' },
  { key: 'warnings', label: 'Warnings' },
  { key: 'calibration', label: 'Calibration' },
  { key: 'obsidian', label: 'Docs' },
  { key: 'agents', label: 'Agents' },
  { key: 'demoViz', label: 'Demo Vis' },
  { key: 'hooks', label: 'Hooks' },
  { key: 'help', label: 'Help' }
]

// Clearing every view flag returns to the chat/home route.
const HOME_PATCH = {
  agents: false,
  alerts: false,
  calendar: false,
  calibration: false,
  demoViz: false,
  forecasts: false,
  forecastsInitialId: null,
  help: false,
  hooks: false,
  markets: false,
  messaging: false,
  news: false,
  obsidian: false
} as const

export function NavBar() {
  const overlay = useStore($overlayState)
  const { theme: t } = useStore($uiState)

  // Which tab is the active route.
  const active = overlay.forecasts
    ? 'desk'
    : overlay.markets
      ? 'markets'
      : overlay.news
        ? 'news'
        : overlay.messaging
          ? 'messaging'
          : overlay.calendar
            ? 'calendar'
            : overlay.calibration
              ? 'calibration'
              : overlay.alerts
                ? 'warnings'
                : overlay.obsidian
                  ? 'obsidian'
                  : overlay.agents
                    ? 'agents'
                    : overlay.demoViz
                      ? 'demoViz'
                      : overlay.hooks
                        ? 'hooks'
                        : overlay.help
                          ? 'help'
                          : 'home'

  const select = (key: string) => {
    switch (key) {
      case 'home':
        return patchOverlayState({ ...HOME_PATCH })

      case 'desk':
        return patchOverlayState({ ...HOME_PATCH, forecasts: true })

      case 'markets':
        return patchOverlayState({ ...HOME_PATCH, markets: true })

      case 'news':
        return patchOverlayState({ ...HOME_PATCH, news: true })

      case 'messaging':
        return patchOverlayState({ ...HOME_PATCH, messaging: true })

      case 'calendar':
        return patchOverlayState({ ...HOME_PATCH, calendar: true })

      case 'warnings':
        return patchOverlayState({ ...HOME_PATCH, alerts: true })

      case 'calibration':
        return patchOverlayState({ ...HOME_PATCH, calibration: true })

      case 'obsidian':
        return patchOverlayState({ ...HOME_PATCH, obsidian: true })

      case 'agents':
        return patchOverlayState({ ...HOME_PATCH, agents: true, agentsInitialHistoryIndex: 0 })

      case 'demoViz':
        return patchOverlayState({ ...HOME_PATCH, demoViz: true })

      case 'hooks':
        return patchOverlayState({ ...HOME_PATCH, hooks: true })

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
