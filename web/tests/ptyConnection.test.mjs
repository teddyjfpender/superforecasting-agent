import assert from 'node:assert/strict';
import { test } from 'node:test';
import { connectPty } from '../src/lib/ptyConnection.ts';

function fixture(t) {
  t.mock.timers.enable({ apis: ['setTimeout'] });
  const sockets = [];
  class Socket {
    static OPEN = 1;
    readyState = 0;
    sent = [];
    constructor(url) { this.url = url; sockets.push(this); }
    open() { this.readyState = 1; this.onopen?.(); }
    send(data) { this.sent.push(data); }
    bytes(text) { this.onmessage?.({ data: new TextEncoder().encode(text).buffer }); }
    close(code = 1006) { this.readyState = 3; this.onclose?.({ code }); }
  }
  const original = globalThis.WebSocket;
  globalThis.WebSocket = Socket;
  t.after(() => { globalThis.WebSocket = original; });
  const data = [], statuses = [];
  const connection = connectPty({
    url: 'ws://localhost/api/pty?channel=fixture',
    onData: chunk => data.push(new TextDecoder().decode(chunk)),
    onStatus: value => statuses.push(value),
    onSocket: () => {},
    onReady: socket => socket.send('resize'),
  });
  t.after(() => connection.close());
  return { sockets, data, statuses, connection };
}

test('reconnect preserves byte offsets, output and resize; stale callbacks are ignored', t => {
  const { sockets, data, connection } = fixture(t);
  sockets[0].open();
  sockets[0].bytes('é');
  sockets[0].close();
  assert.equal(connection.send('paused input'), false);
  t.mock.timers.tick(250);
  assert.equal(new URL(sockets[1].url).searchParams.get('cursor'), '2');
  assert.equal(new URL(sockets[1].url).searchParams.get('reconnect'), '1');
  sockets[1].open();
  sockets[0].bytes('stale');
  sockets[0].close();
  sockets[1].bytes('z');
  assert.deepEqual(data, ['é', 'z']);
  assert.deepEqual(sockets[1].sent, ['resize']);
  assert.equal(connection.send('next input'), true);
});

test('unmount cancels retries and explicitly closes the terminal', t => {
  const { sockets, connection } = fixture(t);
  sockets[0].close();
  connection.close();
  t.mock.timers.tick(10000);
  assert.equal(sockets.length, 1);
});

for (const code of [1000, 1001, 1011, 4400, 4401, 4403, 4410]) {
  test(`terminal close ${code} offers recovery without retrying`, t => {
    const { sockets, statuses } = fixture(t);
    sockets[0].close(code);
    t.mock.timers.tick(10000);
    assert.equal(sockets.length, 1);
    assert.ok(statuses.at(-1));
  });
}

test('reconnect attempts are bounded even if each handshake opens', t => {
  const { sockets, statuses } = fixture(t);
  for (let i = 0; i < 9; i++) {
    sockets[i].open();
    sockets[i].close();
    t.mock.timers.tick(Math.min(250 * 2 ** i, 2000));
  }
  assert.equal(sockets.length, 9);
  assert.match(statuses.at(-1), /Could not reconnect/);
});

test('a stalled handshake closes and retries', t => {
  const { sockets } = fixture(t);
  t.mock.timers.tick(4000);
  assert.equal(sockets[0].readyState, 3);
  t.mock.timers.tick(250);
  assert.equal(sockets.length, 2);
  assert.equal(new URL(sockets[1].url).searchParams.get('reconnect'), '0');
});

test('an opened terminal with no output still requires the original session', t => {
  const { sockets } = fixture(t);
  sockets[0].open();
  sockets[0].close();
  t.mock.timers.tick(250);
  const url = new URL(sockets[1].url);
  assert.equal(url.searchParams.get('cursor'), '0');
  assert.equal(url.searchParams.get('reconnect'), '1');
});
