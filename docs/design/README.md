# ChronoTrace UI design ("Clinical ledger")

The approved design for the doctor interface. Each `.dc.html` file is one screen: the markup shows the
exact layout, spacing, colours and copy, and the `renderVals()` script at the bottom shows the data the
screen displays. The files run only inside the design canvas (they load a `support.js` runtime), so read
them as a reference; don't serve them.

Values that are the trend engine's real demo output: K. Selvam's eGFR, creatinine and HbA1c series, the
six flags, the KDIGO slope and the three medication responses. Illustrative only (take them from the API
when building): potassium, UACR and fasting glucose values, the other three patients, report page/line
numbers and "Demo doctor".

## Screens

| File | Screen | Route |
| --- | --- | --- |
| `Main.dc.html` | Sign in (logo + sign-in card only) | `/login` |
| `Patients.dc.html` | My patients (card grid) | `/patients` |
| `Overview.dc.html` | Patient · Trends overview | `/patients/:code` |
| `System.dc.html` | Body system (Kidney) | `/patients/:code/systems/:system` |
| `Parameter.dc.html` | One parameter (eGFR) | `/patients/:code/parameters/:analyte` |
| `Medications.dc.html` | Medications and lab response | `/patients/:code/medications` |
| `Upload.dc.html` | Add documents and review extracted values | `/patients/:code/documents` |
| `Summary.dc.html` | Summary and PDF | `/patients/:code/summary` |

## Tokens

| Token | Value | Use |
| --- | --- | --- |
| `paper` | `#F4EEE2` | page background (beige); sign-in page adds an 18 px dot grid at 7% ink |
| `paper-2` | `#EDE5D5` | segmented-control track, dividers inside cards |
| `chip` | `#EFE7D6` | condition chips, drug windows on charts |
| `card` | `#FFFDF9` | cards, top bar |
| `line` | `#E3D9C6` | card borders, hairlines |
| `field-line` | `#D9CFBB` | input borders |
| `ink` | `#1D2733` | text, chart lines |
| `ink-2` | `#3F4855` | secondary text on white |
| `ink-3` | `#4A5563` | captions (≥4.5:1 on paper and card) |
| `muted-mark` | `#6A7280` | hollow points, baseline dashes |
| `blue` | `#2F6DA3` | primary buttons, links, "used in trend" points, drug start lines |
| `blue-hover` | `#255C8C` | primary button hover |
| `blue-ink` | `#1F5282` | text on blue tints |
| `blue-tint` | `#E4EEF8` / `#EAF3FB` | "Changed" pills, selected rows, panel headers |
| `blue-line` | `#BFD5EC` / `#9DBFE0` | borders on blue tints, card hover border |
| `focus` | `#D4E4F4` | 3 px focus ring |
| `amber-fill` | `#FBEBD3` | guideline alert cards and pills (the only alarm colour) |
| `amber-line` | `#EBC48E` | their borders |
| `amber-ink` | `#8A4507` | their text |
| `amber-mark` | `#C8741F` | alert triangle, slope line |

Status language: **Guideline alert** (amber triangle), **Changed** (blue dot), **Stable** (hollow grey
dot), **Expected after a drug start** (dashed group, collapsed). Never red/green, never "good"/"bad".

## Type

- Newsreader (serif, 400/500/600, optical sizes): patient names, page titles, card titles, big numbers.
- IBM Plex Sans (400/500/600): all UI text and data; numbers use `font-variant-numeric: tabular-nums`.
- IBM Plex Mono (400/500): patient IDs, report chips (R7), rule IDs, "as printed" text.
- Sizes used: 44/42 page titles, 34 sign-in title, 26/24 section titles, 15–16 body, 13–14 secondary,
  12 uppercase labels (letter-spacing 0.06–0.1em).

## Shape and motion

- Radius: cards 16–20 px, buttons and inputs 10 px, chips and pills fully rounded.
- Shadow: none at rest except large panels (`0 30px 60px -40px rgba(29,39,51,.45)`); clickable cards
  lift 2 px on hover with a blue border.
- Motion: only the new guideline flag after a confirmed upload (one 400 ms fade/slide), respecting
  `prefers-reduced-motion`.

## Signature detail

Every number carries its source: report chips (`R7`, `R1–R3`), and clicking a chart point shows the
report, lab and page with an "Open report" link. Keep this everywhere; it is what the design is about.
