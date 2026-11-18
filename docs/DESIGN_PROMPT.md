# Prompt for Claude Design: Pharmavique wireframes

Copy everything below the line into Claude Design.

---

You are designing **wireframes** (low to mid fidelity, with a light visual direction) for **Pharmavique (فارماڤيك)**, an **Arabic-first, right-to-left** drug-information product for Saudi Arabia. It ships as a **responsive website** and as a **mobile app that is a thin native shell around the same web app (WebView / PWA style)**. So design **one responsive web app, mobile first**, that also works as a full website on desktop. Do not design anything that needs native-only controls.

## 1. What the product is

A drug-intelligence platform built on **official Saudi Food and Drug Authority (SFDA) registry data**: about 9,100 registered drugs, each with prices, active ingredients, strengths, dosage forms, companies, and official safety bulletins. It answers factual questions fast: "What is this drug? What is in it? What does it cost? Which other registered products contain the same ingredient?"

It is **not** a medical advice product. This is the most important design constraint (section 4).

## 2. Users: three roles of equal importance

1. **Patient / consumer** ("مريض"): wants to know what a drug is, its active ingredient, its price, and what else exists with the same ingredient. Low medical literacy, often on a phone, often anxious. Needs plain language, big text, few steps.
2. **Pharmacist** ("صيدلي"): fast, dense, trust-oriented. Looks up by name, photographs a prescription or a shelf, compares price and ingredient, sees safety alerts and shortages. Wants speed and keyboard-friendly tables on desktop.
3. **Pharma company** ("شركة أدوية"): portfolio of its own products, competitor products per active ingredient, market map, gaps (ingredients with few products), price changes. Desktop-heavy, charts and tables.

The three roles share one core (search, drug page, equivalents). Role-specific areas sit on top. Design a **role chooser at first launch** (can be changed later in the profile) and show the role's home screen accordingly.

## 3. Platform and layout rules

- **Language: Arabic only for the UI** (Modern Standard Arabic, simple and neutral, Saudi-friendly). Layout is **RTL**: mirror everything (back arrows point right, progress goes right to left, drawers slide from the right, table first column on the right). Drug names stay as written in the data: Arabic trade name and English trade name both shown, English in LTR runs inside RTL text. Numbers: show **Western digits (0-9)** for prices, strengths and register numbers (the data uses them), with the unit after the number in Arabic (ريال، ملجم). Keep an easy path to add English later (do not hard-code layouts to Arabic string lengths).
- **Mobile first (360-430 px wide)**: bottom tab bar with 4 items (الرئيسية، بحث، المسح الضوئي، حسابي), thumb-reachable primary actions, minimum touch target 44 px, safe-area padding for notches and the home indicator, no hover-only interactions, no fixed elements that fight the on-screen keyboard.
- **Tablet (768 px)** and **desktop (1280+ px)**: the bottom bar becomes a right-side navigation rail; drug page becomes two columns; tables get more columns; the company area uses a dashboard layout.
- Provide each key screen at **mobile** and **desktop** widths. Tablet only for the drug page.
- **Light and dark** themes, both RTL. Calm, clinical, trustworthy: lots of whitespace, one primary color (a deep teal or green family, not alarm red), semantic colors reserved for status (official = green check, unverified = amber, safety alert = red used sparingly, shortage = orange). Never rely on color alone: always add an icon and a text label. WCAG AA contrast.
- **Typography**: a clean Arabic UI typeface (for example IBM Plex Sans Arabic, Cairo, Tajawal or Noto Kufi Arabic) with a Latin companion for English drug names. Generous line height for Arabic. Base size 16 px on mobile, support dynamic text scaling to 200 percent without breaking.
- The mobile app wrapper needs: pull to refresh, offline banner when there is no connection ("لا يوجد اتصال، تظهر آخر نتائج محفوظة"), camera and microphone permission explainers (a screen shown **before** the system prompt), and a splash/launch screen.

## 4. Safety and content rules (these shape the UI, apply them everywhere)

1. **Never medical advice.** No dosing, no "take", "stop" or "switch", no "better than", no recommendations. Wording is always factual: "يحتوي على نفس المادة الفعالة" not "بديل مناسب". Every drug page and every result list carries a persistent short disclaimer: "معلومات للاطلاع فقط وليست نصيحة طبية. استشر الصيدلي أو الطبيب قبل أي تغيير في دواء." Design it as a compact, always visible bar or footer, not a hidden link.
2. **Equivalence is cautious.** Three tiers, always labeled:
   - **"نفس المادة الفعالة والتركيز والشكل"** (same active ingredients, same strength, same dosage form family). Even here the label never says "مطابق" or "بديل آمن".
   - **"محتمل ويحتاج مراجعة الصيدلي"** (possible, needs a pharmacist check): shown when anything is uncertain (different strength unit, different form, missing data). Use an amber badge.
   - Different ingredient sets are **not shown** as equivalents.
3. **Trust and provenance on every record.** Each drug shows a small badge: "بيانات رسمية من هيئة الغذاء والدواء" with the **source link and the date it was fetched**. Data that is not official shows "غير موثّق" in amber. Add an "عن البيانات" bottom sheet or popover explaining source, last update, and limits.
4. **Prices**: show the amount with the label **"ريال سعودي (افتراضي)"** and an info icon explaining: "العملة غير مذكورة في المصدر الرسمي وتم اعتمادها كريال سعودي". Never present a price as a pharmacy's selling price or as stock availability. We have **no inventory data**: never imply "available at this pharmacy".
5. **Images**: SFDA has no product pictures. Many drugs have a real box photo from pharmacy sites; most (hospital infusions, local generics) do not. Design both cases: a real photo with a small "صورة مرجعية" tag, and a **clearly marked placeholder** by dosage form (tablet, capsule, syrup, injection, cream, drops, inhaler...) with the text "صورة توضيحية للشكل الدوائي، وليست علبة الدواء". The placeholder must never look like a real product photo.
6. **AI features always show their work**: what was read (the extracted text), a confidence level per item, and a **confirm or edit step before anything is looked up**. Low confidence is flagged, never silently accepted. Photos are deleted after processing: say so in plain words ("لا نحتفظ بصورتك بعد المعالجة").
7. **Assistant answers only from our data**, with a citation chip under each statement linking to the drug record. If nothing is found it says so ("لم أجد هذا في بياناتنا"). A medical-advice question gets a polite redirect: "هذا سؤال للصيدلي أو الطبيب".
8. **Look-alike sound-alike names**: when a name resembles another registered name, show a small neutral note "يوجد اسم مشابه، تأكد من الاسم والتركيز".
9. Health data is sensitive: minimal collection, no ads, no tracking banners in the wireframes, a visible privacy summary in the profile.

## 5. Real data to use in the wireframes (do not invent other fields)

A drug record has: Arabic trade name and English trade name; **register number** (such as 2209260577); active ingredients each with strength and unit; dosage form (Arabic and English); route (Arabic and English); ATC code(s); marketing company and country; manufacturers and countries; package type and size; shelf life (months); storage conditions; legal status (prescription or not); marketing status (marketed or not); authorization status (valid); distribution site (hospital, pharmacy, ...); price and currency; provenance (source, link, fetched at, trust level).

Realistic examples to use as sample content:

- **بانادول 500 ملجم** / PANADOL 500 mg film-coated tablet; ingredient PARACETAMOL; form: قرص مغلف; company: Haleon Ireland Limited.
- **بانادول اكسترا** / PANADOL EXTRA TAB; ingredients PARACETAMOL + CAFFEINE.
- **بيندولينت** / Bindolent; ingredient BENDAMUSTINE HYDROCHLORIDE 100 mg; form: مسحوق لتحضير محلول للحقن; route: استخدام في الوريد; ATC L01AA09; company Seacross Pharmaceuticals Ltd (United Kingdom); manufacturer Sichuan Huiyu Pharmaceutical Company Limited (China); package: vial; shelf life 36 months; storage: يحفظ في درجة حرارة الغرفة (بحيث لا تتجاوز 30 مئوية); legal status: بوصفة طبية; price 831.50.
- Search results show: Arabic name, English name, ingredients, form, company, and a small match hint. A search result row never shows a made-up "rating".

Also available from other official SFDA lists (design a place for each):
- **Safety labeling updates** (scientific name, trade name, updated section of the leaflet, month).
- **Safety alerts and recalls** (title, date, type such as "Signal" or "Recall").
- **Drug shortage list** (generic name, availability status in Arabic such as "غير متوفر"). Matching to a specific product is by generic name only, so word it as "مدرج في قائمة النواقص الرسمية باسم المادة العلمية" and mark it **"احتمال، يحتاج مراجعة"** when the match is not exact.
- **New approvals** (request type, trade name, scientific name, strength, form, date).
- **Drug companies** (name, address, registration number, status, drug type, production line, country).
- **Licensed pharmacies directory** (name, phone, address text, region). **There are no coordinates and no stock data**: the map shows nearest licensed pharmacies only and never says a pharmacy has a drug.

## 6. Screens to wireframe

For each screen: mobile frame first, then desktop where noted. Include **empty, loading, error, and no-result states** for the ones marked (S).

### A. Onboarding and shell
1. Splash and launch screen.
2. Three-slide intro (what it is, what it never does, privacy) with skip.
3. Role chooser (patient, pharmacist, company), changeable later.
4. Permission explainers (camera, microphone, location), each with "ليس الآن".
5. App shell: bottom tabs (mobile), side rail (desktop), top bar with search, disclaimer bar, offline banner.

### B. Shared core (all roles)
6. **Home** per role (patient: big search + scan + voice + recent; pharmacist: search + prescription scan + shelf scan + alerts feed + recent; company: dashboard summary).
7. **Search** (S): one box that accepts Arabic or English, with spelling tolerance. Show: recent searches, suggestions as you type, filters (dosage form, company, legal status: prescription or not, marketing status), sort (relevance, price). A "did you mean" line for misspellings. Result rows as in section 5. Input methods next to the box: **camera** (box or prescription), **microphone** (voice), keyboard. Results count and the disclaimer bar.
8. **Voice search**: listening state with waveform, transcript shown and **editable** before searching, retry; note it understands Saudi and Egyptian dialects.
9. **Box scan**: camera view with a framing guide, tips ("وجّه الكاميرا للاسم والتركيز"), flash, gallery import; then a **confirmation screen**: extracted name, strength, form with confidence per field, edit fields, "ابحث" button, "لا نحتفظ بصورتك" line.
10. **Drug page** (S, mobile, tablet, desktop). Sections in this order:
    - Header: Arabic name large, English name below, register number, trust badge (official) with date, marketing and authorization status chips.
    - Image area (real photo or marked placeholder).
    - "المادة الفعالة" card: each ingredient with strength and unit.
    - Key facts grid: dosage form, route, package, ATC (with a tap-for-meaning popover), legal status, distribution site, shelf life, storage.
    - **Price card**: amount, "ريال سعودي (افتراضي)" with info icon, last change date, small price-history sparkline linking to the history screen.
    - **Alerts block** (only when present): safety labeling updates, safety alerts, shortage entry with the "احتمال" wording. Each item shows the official title, date, and "المصدر" link. No advice text.
    - **Same ingredient** section: the equivalents list with the two tier badges, sorted by price (cheapest first, with a sort toggle), each row showing name, strength, form, company, price, and the tier badge. A "قارن" checkbox on rows.
    - Company and manufacturers.
    - Look-alike name note when relevant.
    - Footer: "عن البيانات" (source, fetched at, trust level), disclaimer, "أبلغ عن خطأ في البيانات".
    - Sticky actions: save to my list, compare, share.
11. **Compare** (2 to 4 drugs side by side): rows for ingredients, strength, form, route, company, price, status; differences highlighted with an icon and text; horizontal scroll with a sticky first column (RTL aware) on mobile.
12. **Price history** for one drug: line chart with date range tabs, table below, a note that the currency is an assumption.
13. **Not found** and **low-confidence** states with helpful next steps.
14. **My list** (saved drugs): grouped list, a **shared-ingredient notice** when two saved drugs contain the same active ingredient ("تحتوي على نفس المادة الفعالة، راجع الصيدلي"), notification toggle per drug (price change, status change, new safety alert).
15. **Notifications / alerts feed**: price change, status change, new safety bulletin, shortage added or removed, each linking to the drug.
16. **Assistant (chat)**: message list with the user's question, the answer, **citation chips** linking to drug pages, a "المصدر: بياناتنا الرسمية" line, suggested questions ("ما سعر بانادول 500؟"، "ما المواد الفعالة في بانادول اكسترا؟"), refusal message for advice questions, "لم أجد هذا في بياناتنا" state, typing and error states.
17. **Pharmacies near me**: location explainer, map with licensed pharmacy pins, list below with name, region, address text and call button, a banner "نعرض الصيدليات المرخصة فقط ولا نعرف ما يتوفر لديها".

### C. Pharmacist
18. **Prescription scan**: camera with guide, multi-page, then a **review table**: one row per extracted drug name with the raw text crop, the matched product candidates (top 3), confidence, edit and confirm per row; low confidence rows highlighted; then a result sheet per confirmed drug (price, ingredient, same-ingredient list, alerts). Nothing is looked up before confirmation.
19. **Shelf scan**: one photo of a shelf, detected boxes drawn on the photo, each with name and confidence, a **confirmation grid**, similar-name highlights, then "حفظ كقائمة الرف". No stock counts, no availability claims.
20. **Shelf list**: the confirmed items with price and active alerts (safety, shortage) on each, search within the list.
21. **Price and ingredient quick lookup** (a compact desktop view with a keyboard-focused search and a dense results table).

### D. Pharma company
22. **Company dashboard** (desktop first, with a mobile summary): my portfolio count, recent price or status changes of my products, competitor movements, new approvals in my ingredients.
23. **My portfolio**: table of the company's products with ingredient, strength, form, price, status, filters and export.
24. **Market map per active ingredient**: all registered products for one ingredient, grouped by company, with price range, number of products per strength and form; a small visualization (bars or a treemap).
25. **Gap discovery**: ingredients or strength-form combinations with few registered products, with a plain explanation, never a recommendation to launch.
26. **Competitor view** for a company or an ingredient, with a comparison table.
27. **Change report**: a weekly summary of changes (price, new drugs, authorization or marketing status), filterable, exportable (CSV).
28. **Company profile page** (from the official companies list): registration number, status, address, production lines, country, products.

### E. Account and trust
29. **Profile and settings**: role, notification preferences, language (Arabic now, English later, shown as disabled "قريبًا"), appearance (light, dark, system), text size.
30. **Privacy and data**: what we store, deletion of saved data, "لا نحتفظ بصور الوصفات أو العلب".
31. **About the data and limits**: sources, update dates, trust levels, what the product does not do (no dosing, no advice, no stock, no interaction checking).
32. **Report a data issue** form.
33. **Sign in / create account** (phone number or email, one-time code; no passwords shown in the wireframes), with a guest mode where search and drug pages work without an account and saving, alerts, scanning history and company tools need one.

## 7. Flows to show as connected frames

1. Patient: Home, voice or typed search, results, drug page, same-ingredient list, compare, save.
2. Patient: box scan, confirmation, drug page.
3. Pharmacist: prescription scan, review table, per-drug result, shelf list.
4. Pharmacist: shelf scan, confirmation grid, shelf list with alerts.
5. Company: dashboard, ingredient market map, gap discovery, change report export.
6. Assistant: question, cited answer, open the cited drug page; and the advice-question redirect.

## 8. Components to define once and reuse

Search box with input-method buttons; result row; drug card; trust badge (official, unverified); tier badge (same ingredient, possible needs pharmacist check); alert chip (safety, shortage, recall); price block with currency note; ingredient chip; image with placeholder variant; citation chip; confidence meter; confirmation row (edit, confirm); disclaimer bar; offline banner; empty, loading and error states; bottom sheet; data table with sticky first column (RTL); chart cards; permission explainer card.

## 9. Output wanted

- A **wireframe set** for the screens above (mobile and desktop where stated), grayscale structure with the light visual direction applied to colors, type and components, labeled with the screen numbers used here.
- A **component sheet** and a small **design-token sheet** (colors for light and dark, type scale, spacing, radius, elevation).
- The **six flows** wired as clickable prototypes if possible.
- All UI text in **Arabic**, using the example strings above where they apply. Keep Arabic copy short and plain.
- Annotate every place where a safety rule from section 4 shapes the layout.
- Do not add features not listed here (no interaction checker, no dosing, no reminders, no ads, no social features, no e-commerce checkout, no stock or "available near you" claims).
