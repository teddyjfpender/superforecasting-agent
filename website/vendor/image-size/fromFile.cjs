'use strict'

const { createReadStream } = require('node:fs')

async function imageSizeFromFile(filePath) {
  const { imageDimensionsFromStream } = await import('image-dimensions')
  const result = await imageDimensionsFromStream(ReadableStream.from(createReadStream(filePath)))

  if (!result) {
    throw new TypeError(`Unsupported or invalid image: ${filePath}`)
  }

  return result
}

module.exports = { imageSizeFromFile }
