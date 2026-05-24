export const runtimeEnvValue = (name: string, env: NodeJS.ProcessEnv = process.env) => {
  for (const key of [`SUPERFORECASTING_AGENT_${name}`, `FORECAST_${name}`, `HERMES_${name}`]) {
    const value = env[key]?.trim()

    if (value) {
      return value
    }
  }

  return ''
}

export const runtimeEnvEnabled = (name: string, env: NodeJS.ProcessEnv = process.env) =>
  runtimeEnvValue(name, env) === '1'
