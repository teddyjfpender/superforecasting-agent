import assert from 'node:assert/strict'
import { mkdtemp, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import test from 'node:test'
import { fileURLToPath } from 'node:url'

import { imageSizeFromFile } from 'image-size/fromFile'

test('reads a valid documentation PNG', async () => {
  const path = fileURLToPath(new URL('../static/img/favicon-16x16.png', import.meta.url))
  const size = await imageSizeFromFile(path)

  assert.deepEqual({ height: size.height, width: size.width }, { height: 16, width: 16 })
})

const maliciousImages = {
  heif: Buffer.from([
    0, 0, 0, 16, 0x66, 0x74, 0x79, 0x70, 0x61, 0x76, 0x69, 0x66, 0, 0, 0, 0,
    0, 0, 0, 36, 0x6d, 0x65, 0x74, 0x61, 0, 0, 0, 0,
    0, 0, 0, 8, 0x69, 0x70, 0x72, 0x70,
    0, 0, 0, 20, 0x69, 0x70, 0x63, 0x6f,
    0, 0, 0, 0, 0x69, 0x73, 0x70, 0x65, 0, 0, 0, 0, 0, 0, 0, 0
  ]),
  icns: Buffer.from([
    0x69, 0x63, 0x6e, 0x73, 0, 0, 0, 16,
    0x69, 0x73, 0x33, 0x32, 0, 0, 0, 0
  ]),
  jxl: Buffer.from([0, 0, 0, 0, 0x4a, 0x58, 0x4c, 0x20])
}

for (const [type, bytes] of Object.entries(maliciousImages)) {
  test(`rejects zero-length ${type} boxes`, async () => {
    const dir = await mkdtemp(join(tmpdir(), 'sfa-image-size-'))
    const path = join(dir, `malicious.${type}`)

    try {
      await writeFile(path, bytes)
      await assert.rejects(imageSizeFromFile(path), /unsupported|invalid/i)
    } finally {
      await rm(dir, { force: true, recursive: true })
    }
  })
}
