import QRCode from 'qrcode'

// Render a QR code as half-block terminal lines (two module rows per text row),
// with a quiet-zone margin. Rendered with a dark foreground on a light
// background (see the Messaging setup modal) so it scans the normal way up.

export const QR_MARGIN = 4

export const qrLines = (text: string): string[] => {
  const qr = QRCode.create(text || ' ', { errorCorrectionLevel: 'M' })
  const size = qr.modules.size
  const data = qr.modules.data

  const dark = (r: number, c: number): boolean =>
    r >= 0 && c >= 0 && r < size && c < size ? Boolean(data[r * size + c]) : false

  const lines: string[] = []

  for (let r = -QR_MARGIN; r < size + QR_MARGIN; r += 2) {
    let line = ''

    for (let c = -QR_MARGIN; c < size + QR_MARGIN; c++) {
      const top = dark(r, c)
      const bottom = dark(r + 1, c)
      line += top && bottom ? '█' : top ? '▀' : bottom ? '▄' : ' '
    }

    lines.push(line)
  }

  return lines
}

/** Signal dialog chrome consumes eight rows and six columns inside its border. */
export const signalQrLayout = (lines: string[], cols: number, rows: number) => {
  const qrWidth = lines[0]?.length ?? 0
  const minCols = qrWidth + (cols < 100 && qrWidth + 8 < 100 ? 8 : 12)
  const minRows = lines.length + 10
  const width = cols < 100 ? Math.max(40, cols - 2) : Math.max(48, Math.min(cols - 6, Math.max(100, qrWidth + 6)))
  const height = Math.max(8, Math.min(rows - 2, Math.max(36, lines.length + 8)))

  return {
    width,
    height,
    minCols,
    minRows,
    fits: qrWidth <= Math.min(cols, width) - 6 && lines.length + 8 <= Math.min(rows, height)
  }
}
