/** Compiled by the normal TUI type gate. Never invoked: no gateway is started. */
import type { GatewayClient } from '../gatewayClient.js'

export function rpcContractExamples(gateway: GatewayClient) {
  const result: Promise<{ path: string; placeholder: string; lines: number }> = gateway.request('paste.collapse', {
    text: 'hello'
  })

  // @ts-expect-error Unknown methods cannot claim an arbitrary return type.
  gateway.request<{ anything: string }>('invented.method', {})
  // @ts-expect-error Required parameters cannot be omitted.
  gateway.request('paste.collapse')
  // @ts-expect-error Parameter types come from Python.
  gateway.request('paste.collapse', { text: 3 })
  // @ts-expect-error Method parameters cannot be mixed.
  gateway.request('paste.collapse', { session_id: 's' })
  // @ts-expect-error Prompt answers have a method-specific result shape.
  gateway.replyPrompt('sudo', 'srq-one', { answer: 'wrong' })

  // @ts-expect-error Methods with no parameters do not accept arbitrary fields.
  gateway.request('plugins.list', {typo: true})

  return result
}
