# UI design and wireframes

The design of the Pharmavique app: wireframes for every screen, the screens of the running app next to them,
and the design system (colors, type, spacing). The app itself lives in [`mobile/`](../mobile/).

All phone screens below are shown at the same size (390 × 844 points). To open the interactive canvas with
clickable flows, serve this folder over HTTP and open `Pharmavique Wireframes.dc.html`:

```bash
cd pharmavique-wireframes && python -m http.server
```

## Folder contents

- `Pharmavique Wireframes (standalone).html`
- `Pharmavique Wireframes.dc.html`
- `PvA.dc.html`
- `PvB1.dc.html`
- `PvB3.dc.html`
- `PvBrand.dc.html`
- `PvC.dc.html`
- `PvComponents.dc.html`
- `PvDrug.dc.html`
- `PvE.dc.html`
- `PvTokens.dc.html`
- `PvWide.dc.html`
- `README.md`
- `support.js`
- `screens/wireframes/`: one PNG per wireframe screen
- `screens/app/`: screenshots of the running app, light and dark

Screens added to the app after these wireframes were drawn have no wireframe yet: the first-launch role
choice (patient, pharmacist, company), the interaction check for the pharmacist, "my medicines" for the
patient, and the contraindications section of the drug page.

All phone screens below are shown at the same size (390 × 844 points). Wireframes live in
this folder; open `Pharmavique Wireframes.dc.html` over HTTP
(for example `python -m http.server`) for the interactive canvas with clickable flows.

## 1. Wireframe and running app, side by side

The running app uses real SFDA data. Light and dark themes follow the design tokens in section 4.

| Screen | Wireframe | App, light | App, dark |
|:---:|:---:|:---:|:---:|
| Home | <img src="screens/wireframes/B1.png" width="200"> | <img src="screens/app/home.png" width="200"> | <img src="screens/app/home-dark.png" width="200"> |
| Search results | <img src="screens/wireframes/B3.png" width="200"> | <img src="screens/app/search.png" width="200"> | <img src="screens/app/search-dark.png" width="200"> |
| Drug page | <img src="screens/wireframes/B8.png" width="200"> | <img src="screens/app/drug.png" width="200"> | <img src="screens/app/drug-dark.png" width="200"> |
| Equivalents and compare | <img src="screens/wireframes/B11.png" width="200"> | <img src="screens/app/drug-same-ingredient.png" width="200"> | <img src="screens/app/drug-same-ingredient-dark.png" width="200"> |
| Assistant | <img src="screens/wireframes/B16.png" width="200"> | <img src="screens/app/assistant.png" width="200"> | <img src="screens/app/assistant-dark.png" width="200"> |
| Voice search | <img src="screens/wireframes/B5.png" width="200"> | <img src="screens/app/voice.png" width="200"> | <img src="screens/app/voice-dark.png" width="200"> |
| Box scan review | <img src="screens/wireframes/B7.png" width="200"> | <img src="screens/app/scan-review.png" width="200"> | <img src="screens/app/scan-review-dark.png" width="200"> |

## 2. Wireframe gallery: patient

| Splash | Introduction | Role choice | Typing with suggestions |
|:---:|:---:|:---:|:---:|
| <img src="screens/wireframes/A1.png" width="200"> | <img src="screens/wireframes/A2.png" width="200"> | <img src="screens/wireframes/A3.png" width="200"> | <img src="screens/wireframes/B4.png" width="200"> |

| Voice search | Box scan | Scan result | Price history |
|:---:|:---:|:---:|:---:|
| <img src="screens/wireframes/B5.png" width="200"> | <img src="screens/wireframes/B6.png" width="200"> | <img src="screens/wireframes/B7.png" width="200"> | <img src="screens/wireframes/B12.png" width="200"> |

| My medication list | Alerts | Assistant | Safety check |
|:---:|:---:|:---:|:---:|
| <img src="screens/wireframes/B14.png" width="200"> | <img src="screens/wireframes/B15.png" width="200"> | <img src="screens/wireframes/B16.png" width="200"> | <img src="screens/wireframes/B20.png" width="200"> |

| Recall detail | Patient safety center | Account | Data and trust |
|:---:|:---:|:---:|:---:|
| <img src="screens/wireframes/B21.png" width="200"> | <img src="screens/wireframes/B22.png" width="200"> | <img src="screens/wireframes/E1.png" width="200"> | <img src="screens/wireframes/E2.png" width="200"> |

## 3. Wireframe gallery: pharmacist

| Prescription capture | Prescription review | Shelf scan | Scan summary |
|:---:|:---:|:---:|:---:|
| <img src="screens/wireframes/C1.png" width="200"> | <img src="screens/wireframes/C2.png" width="200"> | <img src="screens/wireframes/C4.png" width="200"> | <img src="screens/wireframes/C6.png" width="200"> |

| Desktop drug page | Pharmacist workspace (desktop) |
|:---:|:---:|
| <img src="screens/wireframes/B10.png" width="420"> | <img src="screens/wireframes/C7.png" width="420"> |

## 4. Design system

| Token | Light | Dark | Use |
|---|---|---|---|
| `bg` | `#F5F9F8` | `#0F2427` | Canvas |
| `sf` | `#FFFFFF` | `#173236` | Surfaces (cards, bars) |
| `ink` | `#0F2427` | `#E7F1F1` | Primary text |
| `ink2` | `#4B6365` | `#9FB7B8` | Secondary text (WCAG AA on `bg`) |
| `pr` | `#0D4450` | `#3CC8C4` | Brand primary (deep teal) |
| `prs` | `#E4F1F1` | `#14393C` | Primary soft (disclaimer bar, chips) |
| `ok` | `#17703F` | `#74D79B` | Official data |
| `wn` | `#8A5800` | `#F3C455` | Unverified, or needs a pharmacist's check |
| `rd` | `#B3261E` | `#FF9D95` | Safety alert or recall |
| `or` | `#A04600` | `#FFB67F` | Shortage |

- Type: IBM Plex Sans Arabic for Arabic text, Inter for Latin drug names and digits; base size 16, line height 1.7 for Arabic.
- Radius: 8, 12, 16, 24 (sheets), pill. Card elevation: two soft shadows. Touch targets are at least 44 points.
- Semantic colors always come with an icon and a label, never color alone. Layout is right to left.
