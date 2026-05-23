export const tuiEnvValue = (name: string, env: NodeJS.ProcessEnv = process.env) => {
  for (const key of [`SUPERFORECASTING_AGENT_TUI_${name}`, `FORECAST_TUI_${name}`, `HERMES_TUI_${name}`]) {
    const value = env[key]?.trim()

    if (value) {
      return value
    }
  }

  return ''
}
