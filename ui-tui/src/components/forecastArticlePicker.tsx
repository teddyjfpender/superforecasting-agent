import { useStore } from '@nanostores/react'
import { Box, ScrollBox, type ScrollBoxHandle, Text, useInput } from '@superforecasting/ink'
import { useEffect, useMemo, useRef, useState } from 'react'

import { $globalModal } from '../app/overlayStore.js'
import type { GatewayClient } from '../gatewayClient.js'
import { filterRanked } from '../lib/fuzzyRank.js'
import type {
  ForecastArticleAttachResponse,
  ForecastArticleClaim,
  ForecastQuestionChoice
} from '../protocol/generated.js'
import type { Theme } from '../theme.js'

import { ModalOverlay } from './modalOverlay.js'
import { TextInput } from './textInput.js'

export function ForecastArticlePicker({
  gw,
  article,
  cols,
  rows,
  onClose,
  onAttached,
  t
}: {
  gw: GatewayClient
  article: ForecastArticleClaim
  cols: number
  rows: number
  onClose: () => void
  onAttached: (result: ForecastArticleAttachResponse) => void
  t: Theme
}) {
  const blocked = useStore($globalModal)
  const [questions, setQuestions] = useState<ForecastQuestionChoice[]>([])
  const [query, setQuery] = useState('')
  const [selected, setSelected] = useState(0)
  const [review, setReview] = useState<ForecastQuestionChoice | null>(null)
  const [prepare, setPrepare] = useState(false)
  const [busy, setBusy] = useState(false)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const alive = useRef(true)
  const saving = useRef(false)
  const scroll = useRef<ScrollBoxHandle>(null)

  const matches = useMemo(
    () =>
      filterRanked(questions, query, [
        { get: question => question.title, weight: 5 },
        { get: question => question.domain, weight: 2 },
        { get: question => question.id, weight: 1 }
      ]),
    [questions, query]
  )

  const index = Math.min(selected, Math.max(0, matches.length - 1))
  const contentRows = Math.max(3, Math.min(rows - 2, 30) - 10)
  const start = Math.max(0, index - Math.floor(contentRows / 2))

  useEffect(() => {
    alive.current = true
    void gw
      .request('forecast.question.choices', {})
      .then(result => {
        if (alive.current) {setQuestions(result.questions)}
      })
      .catch((cause: unknown) => {
        if (alive.current) {setError(cause instanceof Error ? cause.message : String(cause))}
      })
      .finally(() => {
        if (alive.current) {setLoading(false)}
      })

    return () => {
      alive.current = false
    }
  }, [gw])

  const attach = async () => {
    if (!review || saving.current) {return}
    saving.current = true
    setBusy(true)
    setError('')

    try {
      const result = await gw.request('forecast.article.attach', {
        question_id: review.id,
        article,
        prepare_update: prepare
      })

      if (alive.current) {onAttached(result)}
    } catch (cause) {
      if (alive.current) {setError(cause instanceof Error ? cause.message : String(cause))}
    } finally {
      saving.current = false

      if (alive.current) {setBusy(false)}
    }
  }

  useInput(
    (input, key, event) => {
      if (review || key.upArrow || key.downArrow || key.escape || key.return || key.pageUp || key.pageDown) {
        ;(event as unknown as { stopImmediatePropagation?: () => void }).stopImmediatePropagation?.()
      }

      if (busy) {return}

      if (key.escape) {
        if (review) {setReview(null)}
        else {onClose()}

        return
      }

      if (review) {
        if (key.tab || key.leftArrow || key.rightArrow) {setPrepare(value => !value)}

        if (key.pageUp || key.pageDown) {scroll.current?.scrollBy(key.pageUp ? -5 : 5)}

        if (key.return) {void attach()}

        return
      }

      if (key.upArrow) {setSelected(value => Math.max(0, value - 1))}

      if (key.downArrow) {setSelected(value => Math.min(matches.length - 1, value + 1))}

      if (key.return && matches[index]) {setReview(matches[index])}
    },
    { isActive: !blocked }
  )

  return (
    <ModalOverlay
      cols={cols}
      footerHint={
        review ? '[Tab Action] [Enter Attach] [PgUp/Dn Read] [Esc Back]' : '[↑↓ Select] [Enter Review] [Esc Close]'
      }
      maxHeight={30}
      maxWidth={100}
      rows={rows}
      t={t}
      title={review ? 'ATTACH ARTICLE · REVIEW' : 'ATTACH ARTICLE · FIND FORECAST'}
      verticalMargin={2}
    >
      <Box flexDirection="column" flexGrow={1} minHeight={0}>
        <Text bold color={t.color.primary} wrap="truncate-end">
          {article.title}
        </Text>
        {review ? (
          <>
            <Text color={t.color.accent} wrap="truncate-end">
              To: {review.title}
            </Text>
            <ScrollBox decstbm={false} flexDirection="column" followContent={false} height={contentRows} ref={scroll}>
              <Text color={t.color.muted}>
                {article.publisher} · {article.published_at ?? 'Publication time unknown'}
              </Text>
              <Text color={t.color.muted}>{article.url}</Text>
              <Text color={t.color.primary}>
                {article.content || 'No extracted text. Only the headline and source link will be attached.'}
              </Text>
              <Text color={t.color.muted}>
                Selected source claim; not independently verified. Attaching does not change probability.
              </Text>
            </ScrollBox>
            <Text color={t.color.accent}>
              {busy
                ? 'Attaching…'
                : prepare
                  ? '  Attach evidence    › Attach + update interview'
                  : '› Attach evidence      Attach + update interview'}
            </Text>
          </>
        ) : (
          <>
            <Box>
              <Text color={t.color.accent}>Search: </Text>
              <TextInput
                columns={Math.max(20, Math.min(cols - 18, 85))}
                focus={!blocked && !busy}
                immediateChange
                onChange={value => {
                  setQuery(value)
                  setSelected(0)
                }}
                placeholder="Question, topic or ID"
                value={query}
              />
            </Box>
            <Box flexDirection="column" height={contentRows} overflow="hidden">
              {matches.slice(start, start + contentRows).map((question, offset) => (
                <Box
                  key={question.id}
                  onClick={() => {
                    if (!blocked) {setReview(question)}
                  }}
                >
                  <Text color={start + offset === index ? t.color.accent : t.color.primary} wrap="truncate-end">
                    {start + offset === index ? '› ' : '  '}
                    {question.title}
                  </Text>
                </Box>
              ))}
              {!matches.length ? (
                <Text color={t.color.muted}>
                  {loading ? 'Loading forecasts…' : 'No matching active forecasts. Create one in the Desk first.'}
                </Text>
              ) : null}
            </Box>
            <Text color={t.color.muted}>{matches.length} matching forecasts · Confirm target before attaching</Text>
          </>
        )}
        {error ? (
          <Text color={t.color.error} wrap="truncate-end">
            {error}
          </Text>
        ) : null}
      </Box>
    </ModalOverlay>
  )
}
