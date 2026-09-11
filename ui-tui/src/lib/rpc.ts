import type { CommandDispatchResponse } from '../gatewayTypes.js'

export type RpcResult = Record<string, any>

export const asRpcResult = <T extends RpcResult = RpcResult>(value: unknown): T | null =>
  !value || typeof value !== 'object' || Array.isArray(value) ? null : (value as T)

export const asCommandDispatch = (value: unknown): CommandDispatchResponse | null => {
  const o = asRpcResult(value)

  if (!o || typeof o.type !== 'string') {
    return null
  }

  const t = o.type

  if (t === 'exec' || t === 'plugin') {
    return { type: t, output: typeof o.output === 'string' ? o.output : undefined }
  }

  if (t === 'alias' && typeof o.target === 'string') {
    return { type: 'alias', target: o.target }
  }

  if (t === 'skill' && typeof o.name === 'string') {
    return { type: 'skill', name: o.name, message: typeof o.message === 'string' ? o.message : undefined }
  }

  if (t === 'send' && typeof o.message === 'string') {
    return {
      type: 'send',
      message: o.message,
      notice: typeof o.notice === 'string' ? o.notice : undefined
    }
  }

  return null
}

export const rpcErrorMessage = (err: unknown) =>
  err instanceof Error && err.message ? err.message : typeof err === 'string' && err.trim() ? err : 'request failed'

export class GatewayRpcError extends Error {
  constructor(
    message: string,
    readonly code: number | null,
    readonly data?: unknown
  ) {
    super(message)
    this.name = 'GatewayRpcError'
  }
}

export function isCommandHandoff(error: unknown): boolean {
  if (!(error instanceof GatewayRpcError)) {
    return false
  }

  // A host without the legacy method has not executed the command.
  if (error.code === -32601) {
    return true
  }

  if (error.code !== 4018) {
    return false
  }

  const data = asRpcResult(error.data)

  if (error.data !== undefined) {
    return data?.dispatch === 'command.dispatch' && data.execution_started === false
  }

  // Older hosts use the same pre-execution handoffs without structured data.
  return /^(configured command:|pending-input command:|skill command:|snapshot restore mutates live config\/state;).*use command\.dispatch/.test(
    error.message
  )
}
