import type { Article } from './newsFeedFetch.js'

/** Compare visible content, not object identity or fetch completion order. */
export function sameNewsArticles(a: Article[], b: Article[]): boolean {
  return (
    a.length === b.length &&
    a.every((article, index) => {
      const next = b[index]!

      return (
        article.feedUrl === next.feedUrl &&
        article.link === next.link &&
        article.title === next.title &&
        article.publishedAt === next.publishedAt &&
        article.summary === next.summary &&
        article.content === next.content &&
        article.author === next.author &&
        article.feedTitle === next.feedTitle
      )
    })
  )
}
