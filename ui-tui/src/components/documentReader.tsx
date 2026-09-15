import { Box, ScrollBox, type ScrollBoxHandle, Text } from '@superforecasting/ink'
import { useEffect, useRef } from 'react'

import { renderLatex } from '../lib/latexRender.js'
import type { Theme } from '../theme.js'

import { Md } from './markdown.js'

export function DocumentReader({
  identity,
  content,
  kind,
  width,
  height,
  t,
  page,
  onWikiLink
}: {
  identity: string
  content: string
  kind: 'markdown' | 'latex'
  width: number
  height: number
  t: Theme
  page: number
  onWikiLink?: (target: string) => void
}) {
  const scroll = useRef<ScrollBoxHandle>(null)
  const previous = useRef(page)
  const lastIdentity = useRef(identity)
  useEffect(() => {
    if (lastIdentity.current !== identity) {
      scroll.current?.scrollTo(0)
      lastIdentity.current = identity
    } else {
      scroll.current?.scrollBy((page - previous.current) * Math.max(1, height - 2))
    }

    previous.current = page
  }, [page, height, identity])
  const body = content.replace(/^---\r?\n[\s\S]*?\r?\n---(?:\r?\n|$)/, '')

  return (
    <ScrollBox
      decstbm={false}
      flexDirection="column"
      flexShrink={0}
      followContent={false}
      height={height}
      overflow="hidden"
      ref={scroll}
    >
      <Box flexDirection="column" flexShrink={0} width={width}>
        {kind === 'markdown' ? (
          <Md cols={width} compact onWikiLink={onWikiLink} t={t} text={body} />
        ) : (
          renderLatex(body).map((block, index) => (
            <Text
              bold={block.kind === 'heading'}
              color={block.kind === 'heading' ? t.color.accent : t.color.text}
              key={index}
            >
              {block.text || ' '}
            </Text>
          ))
        )}
      </Box>
    </ScrollBox>
  )
}
