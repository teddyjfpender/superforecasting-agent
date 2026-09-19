/** Typed local RPC provider. Unregistered calls fail instead of returning fake success. */
import type { RpcArgs, RpcMethod, RpcMethods } from '../protocol/generated.js'

type Handler<M extends RpcMethod> = (
  params: RpcMethods[M]['params']
) => RpcMethods[M]['result'] | Promise<RpcMethods[M]['result']>

export class RpcFixtures {
  private handlers = new Map<RpcMethod, (params: unknown) => unknown>()

  handle<M extends RpcMethod>(method: M, handler: Handler<NoInfer<M>>): this {
    // The registration key binds the erased callback to M. request's public
    // signature guarantees the corresponding parameters; this is not a wire parser.
    this.handlers.set(method, params => handler(params as RpcMethods[M]['params']))

    return this
  }

  async request<M extends RpcMethod>(method: M, ...args: RpcArgs<M>): Promise<RpcMethods[M]['result']> {
    const handler = this.handlers.get(method)

    if (!handler) {
      throw new Error(`Unregistered fixture RPC: ${method}`)
    }

    // Registration above preserves the method/result association in the map.
    return await handler(args[0] ?? {}) as RpcMethods[M]['result']
  }
}
