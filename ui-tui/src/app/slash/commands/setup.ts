import { withInkSuspended } from '@hermes/ink'

import { forecastCommandDisplayName, launchForecastCommand } from '../../../lib/externalCli.js'
import { runExternalSetup } from '../../setupHandoff.js'
import type { SlashCommand } from '../types.js'

export const setupCommands: SlashCommand[] = [
  {
    help: 'run full setup wizard (launches `superforecasting-agent setup`)',
    name: 'setup',
    run: (arg, ctx) =>
      void runExternalSetup({
        args: ['setup', ...arg.split(/\s+/).filter(Boolean)],
        commandName: forecastCommandDisplayName(),
        ctx,
        done: 'setup complete — starting session…',
        launcher: launchForecastCommand,
        suspend: withInkSuspended
      })
  }
]
