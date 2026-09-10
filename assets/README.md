# Product banner

`banner.svg` is the editable source for the README banner. The website social
image is `website/static/img/superforecasting-agent-banner.png`, rendered from
the same source. Both use the product name and the existing forecasting-desk
tagline. These assets do not define the TUI theme.

Regenerate the PNG from the repository root with librsvg:

```sh
rsvg-convert assets/banner.svg -o website/static/img/superforecasting-agent-banner.png
```

The SVG uses Georgia and Arial with generic fallbacks; the PNG fixes the rendered
appearance for social previews. Check the result at desktop and mobile widths
when changing the lettering or copy.
