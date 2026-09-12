import { execFileSync } from 'node:child_process'
import { existsSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

import { describe, expect, it } from 'vitest'

import { SLASH_COMMANDS } from '../app/slash/registry.js'

type CommandRoute = 'fallback' | 'local' | 'native'

interface CommandRegistryLoad {
  error?: string
  names: string[]
  native: string[]
  terminal: string[]
}

const NATIVE_MUTATING_COMMANDS = new Set(['browser', 'busy', 'fast', 'reload-mcp', 'rollback', 'stop'])

const MUTATING_COMMANDS = [
  'background',
  'branch',
  'browser',
  'busy',
  'clear',
  'compress',
  'fast',
  'model',
  'new',
  'queue',
  'reasoning',
  'reload-mcp',
  'retry',
  'rollback',
  'steer',
  'stop',
  'style',
  'title',
  'tools',
  'undo',
  'verbose',
  'voice',
  'yolo'
] as const

const loadCommandRegistryNames = (): CommandRegistryLoad => {
  const here = dirname(fileURLToPath(import.meta.url))
  const root = resolve(here, '../../..')
  const venvPython = resolve(root, '.venv/bin/python')

  try {
    const catalog = JSON.parse(
      execFileSync(
        process.env.PYTHON ?? (existsSync(venvPython) ? venvPython : 'python3'),
        [
          '-c',
          'import json; from superforecasting_agent.application.command_catalog import COMMAND_REGISTRY; from tui_gateway.command_routes import NATIVE_COMMANDS, terminal_command_names; print(json.dumps({"names": [c.name for c in COMMAND_REGISTRY if not c.gateway_only], "native": sorted(NATIVE_COMMANDS), "terminal": sorted(terminal_command_names())}))'
        ],
        { cwd: root, encoding: 'utf8' }
      )
    ) as CommandRegistryLoad

    return catalog
  } catch (error) {
    return {
      error: error instanceof Error ? error.message : String(error),
      names: [],
      native: [],
      terminal: []
    }
  }
}

const commandRegistry = loadCommandRegistryNames()
const registryIt = it

const LOCAL_COMMAND_NAMES = new Set(
  SLASH_COMMANDS.flatMap(command => [command.name, ...(command.aliases ?? [])].map(name => name.toLowerCase()))
)

const classifyRoute = (name: string): CommandRoute => {
  const normalized = name.toLowerCase()

  if (NATIVE_MUTATING_COMMANDS.has(normalized)) {
    return 'native'
  }

  if (LOCAL_COMMAND_NAMES.has(normalized)) {
    return 'local'
  }

  return commandRegistry.native.includes(normalized) ? 'native' : 'fallback'
}

describe('slash parity matrix', () => {
  it('loads the shared ownership catalog and covers every terminal command', () => {
    expect(commandRegistry.error).toBeUndefined()
    expect(commandRegistry.names.length).toBeGreaterThan(0)

    for (const name of commandRegistry.terminal) {
      expect(LOCAL_COMMAND_NAMES.has(name), `terminal handler missing: /${name}`).toBe(true)
    }

    for (const name of commandRegistry.names) {
      expect(classifyRoute(name), `command has no owner: /${name}`).not.toBe('fallback')
    }
  })

  registryIt('classifies each command registry command as local/native/fallback', () => {
    const routes = Object.fromEntries(commandRegistry.names.map(name => [name, classifyRoute(name)]))

    expect(routes['model']).toBe('local')
    expect(routes['browser']).toBe('native')
    expect(routes['reload-mcp']).toBe('native')
    expect(routes['rollback']).toBe('native')
    expect(routes['stop']).toBe('native')
  })

  registryIt('keeps every mutating command off slash-worker fallback', () => {
    const routes = Object.fromEntries(commandRegistry.names.map(name => [name, classifyRoute(name)]))

    for (const name of MUTATING_COMMANDS) {
      expect(routes[name], `missing command in registry: ${name}`).toBeDefined()
      expect(routes[name], `mutating command must not fallback: ${name}`).not.toBe('fallback')
    }
  })
})
