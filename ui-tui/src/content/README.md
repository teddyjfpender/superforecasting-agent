# Terminal copy and catalogs

Contains interface copy, keymaps, setup text and presentation catalogs.

## Ownership and boundaries

Use canonical product language and keep instructions consistent with registered commands and actual capabilities.

## Start here

These are entry points and representative modules, not an exhaustive inventory.

| File                                       | Responsibility    |
| ------------------------------------------ | ----------------- |
| [auth.ts](auth.ts)                         | auth.             |
| [bernardAnimation.ts](bernardAnimation.ts) | bernardAnimation. |
| [charms.ts](charms.ts)                     | charms.           |
| [faces.ts](faces.ts)                       | faces.            |
| [fortunes.ts](fortunes.ts)                 | fortunes.         |
| [gatewayLost.ts](gatewayLost.ts)           | gatewayLost.      |
| [hotkeys.ts](hotkeys.ts)                   | hotkeys.          |
| [keymaps.ts](keymaps.ts)                   | keymaps.          |

## News sources

[`newsFeeds.json`](newsFeeds.json) owns the Add Feed discovery catalog.
[`newsFeedCatalog.ts`](newsFeedCatalog.ts) is generated; never edit it directly.
The original catalog was imported from the CC0
[awesome-rss-feeds collection](https://github.com/plenaryapp/awesome-rss-feeds)
plus a forecasting supplement. New additions are reviewed publisher feeds;
see the [qualification record](../../../docs/verification/news-catalog.md).

To add a feed:

1. Add `category`, `title`, `url`, and `description` to the JSON. Prefer the
   publisher's HTTPS endpoint, a precise topic and an existing category where it fits.
2. Verify a bounded fetch through `forecasting.news.transport.fetch_public_text`
   and parsing through `ui-tui/src/lib/newsFeedFetch.ts`: useful titles, article
   links, real publication dates and the intended language/topic. Check the newest
   past publication (not just the first item); reject stale feeds and distinguish
   future events from released news. Confirm subject-filter IDs against the
   publisher directory, and label multilingual or issuer-supplied material.
   Record the date and result. Do not substitute scraping proxies for inaccessible feeds.
3. Mention subscription requirements in the description. Public RSS does not
   imply full-text access, redistribution rights or a licensed real-time wire.
4. Run `python3 scripts/gen-news-catalog.py`, then the checks below. Generation
   is offline; `python3 scripts/gen-news-catalog.py --check` detects stale output.
   Search synonyms live in `../lib/newsFeedSearch.ts`.

Catalog additions are opt-in through **News → Add Feed**; they do not silently
subscribe existing profiles. The smaller setup starter is owned separately by
`forecasting/news/catalog.py`. Do not add every discovery feed to that starter.

## Working in this directory

From the repository root, run:

```sh
npm --prefix ui-tui run type-check
npm --prefix ui-tui run lint
npm --prefix ui-tui test
```

For input, resize or shutdown changes, also run the relevant installed-terminal
verification on the affected native platform; renderer tests do not establish
ConPTY or PTY behavior.

Update this guide when entry points or ownership change. See the
[ownership map](../../../docs/architecture/ownership-map.md)
and [engineering backlog](../../../TODO.md) for cross-package context.

[↑ Parent directory](../README.md)
