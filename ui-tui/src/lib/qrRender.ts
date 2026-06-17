import QRCode from 'qrcode'

// Render a QR code as half-block terminal lines (two module rows per text row),
// with a quiet-zone margin. Rendered with a dark foreground on a light
// background (see the Messaging setup modal) so it scans the normal way up.

export const QR_MARGIN = 2

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
