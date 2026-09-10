/** Keep one terminal's byte cursor across bounded WebSocket reconnects. */
export function connectPty(options: {
  url: string;
  onData: (data: string | Uint8Array) => void;
  onStatus: (message: string | null) => void;
  onSocket: (socket: WebSocket | null) => void;
  onReady: (socket: WebSocket) => void;
}) {
  let socket: WebSocket | null = null;
  let stopped = false;
  let cursor = 0;
  let attempts = 0;
  let retry: ReturnType<typeof setTimeout> | undefined;
  let opening: ReturnType<typeof setTimeout> | undefined;

  function connect() {
    if (stopped) return;
    const url = new URL(options.url);
    url.searchParams.set("cursor", String(cursor));
    const current = new WebSocket(url.toString());
    current.binaryType = "arraybuffer";
    socket = current;
    options.onSocket(current);
    opening = setTimeout(() => current.close(), 4000);

    current.onopen = () => {
      if (stopped || current !== socket) return;
      clearTimeout(opening);
      options.onStatus(null);
      options.onReady(current);
    };
    current.onmessage = (event) => {
      if (stopped || current !== socket) return;
      if (typeof event.data === "string") {
        options.onData(event.data);
      } else {
        const bytes = new Uint8Array(event.data as ArrayBuffer);
        cursor += bytes.byteLength;
        attempts = 0;
        options.onData(bytes);
      }
    };
    current.onclose = (event) => {
      if (stopped || current !== socket) return;
      clearTimeout(opening);
      socket = null;
      options.onSocket(null);
      const terminalErrors: Record<number, string> = {
        1000: "Session ended. Open Forecast Sessions to resume saved work.",
        1001: "Dashboard stopped. Reload to reconnect.",
        1011: "Forecast Desk could not start. Check the terminal message and retry.",
        4400: "Invalid terminal connection. Reload the page to reconnect.",
        4401: "Session authentication expired. Reload the page to reconnect.",
        4403: "Forecast Desk is only reachable from localhost.",
        4410: "Terminal replay is unavailable. Open Forecast Sessions to resume saved work.",
      };
      if (terminalErrors[event.code]) {
        stopped = true;
        options.onStatus(terminalErrors[event.code]);
        return;
      }
      attempts += 1;
      if (attempts > 8) {
        stopped = true;
        options.onStatus("Could not reconnect. Reload or open Forecast Sessions to resume saved work.");
        return;
      }
      options.onStatus(`Connection lost. Reconnecting (${attempts}/8)… Input is paused.`);
      retry = setTimeout(connect, Math.min(250 * 2 ** (attempts - 1), 2000));
    };
  }

  connect();
  return {
    send(data: string) {
      if (socket?.readyState !== WebSocket.OPEN) return false;
      socket.send(data);
      return true;
    },
    close() {
      stopped = true;
      clearTimeout(retry);
      clearTimeout(opening);
      socket?.close(1000);
      socket = null;
      options.onSocket(null);
    },
  };
}
