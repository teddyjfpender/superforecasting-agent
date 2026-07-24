import { spawn } from 'node:child_process'

export interface LaunchResult {
  code: null | number
  error?: string
}

const configuredForecastBin = () =>
  process.env.SUPERFORECASTING_AGENT_BIN?.trim() ||
  process.env.FORECAST_BIN?.trim() ||
  process.env.HERMES_BIN?.trim()

const resolveForecastBins = () => {
  const configured = configuredForecastBin()

  return configured ? [configured] : ['superforecasting-agent', 'hermes']
}

export const forecastCommandDisplayName = () => resolveForecastBins()[0]

const launchOne = (bin: string, args: string[]): Promise<LaunchResult> =>
  new Promise(resolve => {
    const child = spawn(bin, args, { stdio: 'inherit' })

    child.on('error', err => {
      const code = (err as NodeJS.ErrnoException).code
      resolve({ code: null, error: err.message, ...(code ? { errorCode: code } : {}) } as LaunchResult & { errorCode?: string })
    })
    child.on('exit', code => resolve({ code }))
  })

export const launchForecastCommand = async (args: string[]): Promise<LaunchResult> => {
  let last: (LaunchResult & { errorCode?: string }) | null = null

  for (const bin of resolveForecastBins()) {
    const result = await launchOne(bin, args) as LaunchResult & { errorCode?: string }
    last = result

    if (result.errorCode === 'ENOENT') {continue}

    return result
  }

  return last ?? { code: null, error: 'no forecast CLI binary found' }
}

export const launchHermesCommand = launchForecastCommand
