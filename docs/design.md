# Design

This document is the design brief and token plan for the DataPilot web app. The tokens it describes live in one file, `frontend/src/styles/_tokens.scss`; this page explains why they have the values they have.

## Brief

DataPilot is a measuring instrument, not a marketing site. Operations and finance analysts open it to read numbers, compare them, and get back to their work. The interface stays neutral and steady so the figures can stand out. It should be dense in the way a well-made spreadsheet is dense: a tight grid, clear rules between things, and no screen that feels crowded.

Three consequences follow from that brief:

- Numbers are the most important thing on any screen. They get the best typographic treatment and the strongest contrast.
- The interface explains itself in plain words. Nothing is decorative unless it also carries information.
- One element is allowed to be memorable: the query receipt in Ask your data. Everything around it stays quiet so it can be.

## Principles

1. **Numbers first.** Figures are tabular, right-aligned in tables, use a true minus sign (U+2212), and show their units in a quieter color.
2. **Structure comes from rules and space, not boxes and shadows.** Content sits on flat sheets separated by 1 px rules. Shadows exist only for things that float above the page.
3. **Color carries meaning.** Cobalt means "you can act here". Green and red mean "this went up or down" and appear only on changes, always with a sign. The one other use of red is an error, which always comes with a written message. Everything else is neutral.
4. **Dense, not cramped.** A 14 px body size, 32 px table rows and a 4 px grid fit a lot on screen without crowding it.
5. **Say exactly what happened.** Sentence case everywhere. Buttons name their action ("Log in", not "Continue"). Errors say what went wrong and what to do next.
6. **One memorable element.** The query receipt is the product's signature. It is the only place with ornamental detail.

## Color

Five neutral base colors, one signal color, two semantic colors for changes, and a categorical palette for charts. Every text pair below meets WCAG AA; the ratios are measured against the background named in the role.

| Token | Light | Dark | Role |
| --- | --- | --- | --- |
| Paper | `#F3F5F8` | `#171C24` | App background. A cool grey, so the page never reads as cream or as black. |
| Sheet | `#FFFFFF` | `#1E242E` | Surfaces that hold data: tables, forms, charts. In the dark theme a sheet is lighter than the paper, so depth comes from lightness instead of shadow. |
| Rule | `#D3D9E1` | `#323A47` | Hairlines and dividers. Decorative, so it does not need 3:1. |
| Graphite | `#525C6B` | `#9AA4B3` | Secondary text, units, labels, placeholders. 6.2:1 on light paper, 6.8:1 on dark paper. |
| Ink | `#121821` | `#E6EAF0` | Primary text and every number. 16.3:1 and 14.2:1. |
| Cobalt (signal) | `#2B3FBF` | `#93A2FF` | The only color for links, primary buttons, the active page and keyboard focus. 7.5:1 and 7.2:1. |
| Up | `#13714B` | `#4FC48D` | Positive changes only. |
| Down | `#B42F28` | `#FF7F73` | Negative changes only. |

Derived values, defined next to the base colors in the token file:

| Token | Light | Dark | Why it exists |
| --- | --- | --- | --- |
| Control border | `#808A98` | `#717B8A` | Input and button borders must reach 3:1 against the sheet (WCAG 1.4.11). The rule color is too light for that. 3.5:1 and 3.6:1. |
| Cobalt tint | `#E8EBFA` | `#262E45` | Hover and selected backgrounds. Cobalt text on it stays at 6.9:1 and 5.7:1. |
| Text on cobalt | `#FFFFFF` | `#171C24` | Labels on primary buttons. 8.2:1 and 7.2:1. |
| Error | `#B42F28` | `#FF7F73` | Invalid fields and failed requests. It shares the down color's value but has its own token, so the two can diverge, and it always comes with a written message. |

Up and down colors are never the only signal. A change is always written with its sign ("+4.2%", "−1.8%"), so it reads correctly in grayscale and for colorblind readers.

### Chart palette

The categorical palette starts from the signal color and adds hues that stay distinct from each other and from the up and down colors. Green and red are left out on purpose, so a line on a chart is never mistaken for a change indicator.

| Order | Name | Light | Dark |
| --- | --- | --- | --- |
| 1 | Cobalt | `#2B3FBF` | `#93A2FF` |
| 2 | Ochre | `#99650A` | `#E0A93E` |
| 3 | Steel | `#1C6F8C` | `#5EB8D6` |
| 4 | Plum | `#86398A` | `#D68AD9` |
| 5 | Graphite | `#525C6B` | `#9AA4B3` |

Stage 9 adds the sequential scale for the cohort heatmap, derived from cobalt.

## Typeface

**IBM Plex Sans** for the interface and **IBM Plex Mono** for SQL and the query receipt, self-hosted through `@fontsource` (Latin subset; Sans in 400, 500 and 600, Mono in 400 and 500). No font is requested from a third party.

Why Plex:

- **Its figures are tabular by default.** All ten digits in Plex Sans have the same advance width (600 units), so every column of numbers lines up without anyone remembering to add `font-variant-numeric: tabular-nums`. For an app whose hero is numbers, that removes a whole class of mistakes.
- **It was designed for technical work.** IBM drew it for engineering and data products. It is a neutral grotesque with a few distinctive details (the angled cuts on the stroke ends of letters like `t` and `r`), so it has character without calling attention to itself.
- **Sans and Mono were drawn together.** The receipt can switch to Mono for SQL and metadata without introducing a second voice.
- **It is open source** (SIL Open Font License) and has a true minus sign.

Rejected: Inter and Roboto (the defaults the brief asks us to avoid), system fonts alone (tabular figures and the minus sign vary by platform), and Source Sans 3 with Source Code Pro (good, but its figures are proportional by default, so every data cell would need `tnum` switched on).

### Type scale

| Token | Size / line height | Weight | Use |
| --- | --- | --- | --- |
| `caption` | 12 / 16 | 400 | Footnotes, axis labels, timestamps |
| `table` | 13 / 18 | 400 | Table cells, dense lists |
| `body` | 14 / 20 | 400 | Default text, form fields, buttons (500) |
| `lead` | 16 / 24 | 400 | Introductory sentences, empty-state text |
| `section` | 20 / 28 | 600 | Section titles |
| `page` | 28 / 34 | 600 | Page titles |
| `figure` | 40 / 44 | 600 | KPI figures and other hero numbers |

The steps are small at the bottom, where most of the interface lives, and larger at the top, where a few numbers need to dominate. Labels use weight 500 rather than capitals or letter spacing.

## Spacing and radius

Spacing is a 4 px grid: `2, 4, 8, 12, 16, 24, 32, 48, 64` px (`--space-half` and `--space-1` to `--space-8`). Table rows are 32 px tall. Page gutters are 24 px on desktop and 16 px at phone widths.

Radius reflects hierarchy: a container is rounder than what it contains.

| Token | Value | Use |
| --- | --- | --- |
| `--radius-none` | 0 | Table cells, joined edges |
| `--radius-control` | 3 px | Inputs, buttons, chips |
| `--radius-sheet` | 6 px | Sheets and panels |
| `--radius-overlay` | 8 px | Menus, toasts, dialogs |
| `--radius-round` | 999 px | Status dots only |

There is one shadow token, `--shadow-overlay`, used only by menus and toasts. Sheets have a 1 px rule instead.

## Motion and focus

- State changes (hover, open, close) take 120 ms with an ease-out curve. Layout never animates.
- With `prefers-reduced-motion: reduce`, every transition and animation is turned off.
- Keyboard focus is a 2 px cobalt outline with a 2 px offset on `:focus-visible`, on every interactive element. It is never removed.

## Themes

Light and dark themes share every token name; only the values change. The app follows the system preference until the user picks a theme with the header button, and then remembers the choice. "Match system theme" in the user menu goes back to following the system.

The dark theme is not an inversion. It is the same instrument at night: a blue-slate paper, sheets one step lighter, and a softened cobalt that keeps its meaning without glowing.

## Layout

A top bar, not a sidebar: three destinations do not justify a permanent column, and a top bar leaves the full width for tables and charts. Content is capped at 1440 px.

```
Desktop
┌────────────────────────────────────────────────────────────────────┐
│ DataPilot    Dashboard   Orders   Ask                  [◐]  [DH ▾] │
│              ━━━━━━━━━  2 px cobalt rule under the active page     │
├────────────────────────────────────────────────────────────────────┤
│ Page title                                       Page actions      │
│ One line of context in graphite                                    │
│ ┌ sheet: 1 px rule, 6 px radius, no shadow ──────────────────────┐ │
│ │ Tables, charts, receipts                                       │ │
│ └────────────────────────────────────────────────────────────────┘ │
└────────────────────────────────────────────────────────────────────┘

375 px
┌─────────────────────────────────┐
│ DataPilot              [◐] [DH] │
├──────────┬───────────┬──────────┤
│Dashboard │  Orders   │   Ask    │
├──────────┴───────────┴──────────┤
│ Page title                      │
│ ...                             │
```

At phone widths the navigation becomes a second row of three equal tabs instead of a menu button, so no destination is hidden behind a tap.

## Interface copy

- Sentence case for every label, title and button.
- Buttons name their action: "Log in", "Create account", "Log out", "Load more".
- Errors say what happened and what to do: "Email or password is incorrect." rather than "Error 401".
- Loading, empty and error states use specific words: "No orders match these filters." with a way to clear them.

## The query receipt (Stage 10)

Each answer in Ask your data is presented as a query receipt: the question, the explanation, the SQL, the model that answered, the row count and the time, then the results. It is set in Plex Mono for SQL and metadata, ruled like a printed slip, with a perforated top edge.

Keep the printed-slip details (the perforated edge, the ruling) subtle and functional, so the receipt reads as crafted rather than decorative. The ruling separates the receipt's sections; the edge marks where one answer ends and the next begins. If a detail stops doing a job, it goes.

## Checked against generic tells

The roadmap lists patterns that make an interface look templated. The first draft of this plan had several of them; this is what changed and why.

| First draft | Tell | Revised to |
| --- | --- | --- |
| Dark theme on `#0E1014` with a lime focus color | Near-black background with a single acid accent | Blue-slate paper (`#171C24`) with a softened cobalt. It reads as the same product at night. |
| Signal color `#2563EB` | A framework's default blue | Cobalt `#2B3FBF`: deeper and more violet, and clearly apart from the steel chart color. |
| Background `#FAF7F2` | Warm cream | Cool grey `#F3F5F8`. |
| KPI tiles as rounded cards with a soft shadow | Identical rounded cards with the same shadow everywhere | One sheet split by vertical rules. Shadows only on overlays. |
| Section labels like "ORDERS · LAST 30 DAYS" | All-caps eyebrow labels and middle-dot metadata | Sentence-case labels in graphite; metadata as labelled fields. |
| Login as a split screen with a gradient panel | Gradient washes | One plain form column with a single line about what the product does. |
| "Continue →" | Arrows appended to button labels | "Log in", "Create account". |
