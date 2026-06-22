import { Box, Text } from '@hermes/ink'

import type { RenderResult, StyledRow } from '../../lib/viz/index.js'

// Dumb renderer: a RenderResult's StyledRow[] → <Text> lines, one nested <Text>
// per coalesced run (the proven outriderHeader span pattern). No per-pixel React
// nodes; the engine already coalesced same-style cells into runs.

const Row = ({ row }: { row: StyledRow }) => (
  <Text wrap="truncate-end">
    {row.map((run, i) =>
      run.color || run.backgroundColor || run.bold || run.dim ? (
        <Text backgroundColor={run.backgroundColor} bold={run.bold} color={run.color} dimColor={run.dim} key={i}>
          {run.text}
        </Text>
      ) : (
        <Text key={i}>{run.text}</Text>
      )
    )}
  </Text>
)

export function CellCanvas({ result }: { result: RenderResult }) {
  return (
    <Box flexDirection="column" flexShrink={0}>
      {result.rows.map((row, i) => (
        <Row key={i} row={row} />
      ))}
      {result.legend?.length ? (
        <Box flexDirection="column" marginTop={1}>
          {result.legend.map((row, i) => (
            <Row key={i} row={row} />
          ))}
        </Box>
      ) : null}
      {result.axisBottom?.length ? <Row row={result.axisBottom} /> : null}
    </Box>
  )
}
