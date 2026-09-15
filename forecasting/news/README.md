# News acquisition

This package owns the curated global starter, bounded public HTTP acquisition,
and article-body parsing. It never creates evidence or changes forecast probabilities.

- `catalog.py`: reviewed publisher RSS endpoints and terminal topics. Keep the
  starter geographically diverse and useful; leave niche feeds in the broader catalog.
- `transport.py`: public URL checks on requests and redirects, verified TLS,
  timeouts and a 2 MiB response limit. Uses the existing URL safety policy;
  DNS preflight has the same documented rebinding limitation as that policy.
- `articles.py`: pure HTML-to-text extraction. Prefer body containers, omit
  hidden/navigation content and label excerpts. Never bypass publisher access gates.

To add a starter source, verify its official feed URL, live entries, publication
metadata and access terms; add a catalog row and record qualification. For a
legacy article layout, use a narrow host-specific selector and a parser fixture
proving unrelated pages do not match. Do not add a scraping dependency per source.

`application/news_desk.py` owns atomic backend subscriptions, legacy-file reading
and additive setup. `protocol/rpc/news.py` defines generated client contracts;
`tui_gateway/news_rpc.py` only adapts requests. The TUI retains rich RSS content
and renders article text in its scrollable reader. Unknown dates remain unknown.
