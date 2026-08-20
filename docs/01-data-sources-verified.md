# Data Sources — Verified by Live Probing

Every claim below was produced by an actual HTTP request on **2026-08-19**, not read from documentation. Values are the real responses received. Re-run the probe commands to confirm before the defence.

Environment note: probes ran from a **non-Ukrainian IP**. Two access findings depend on that (see §6).

---

## 1. UN Comtrade — preview API (no authentication)

**Base:** `https://comtradeapi.un.org/public/v1/preview/C/{freq}/HS`
`freq` = `A` (annual) or `M` (monthly). Ukraine reporter code = **804**.

### Verified calls

```bash
# Ukraine imports of HS 0902 (tea) from China (156), 2023
curl "https://comtradeapi.un.org/public/v1/preview/C/A/HS?reporterCode=804&period=2023&partnerCode=156&cmdCode=0902&flowCode=M"
```
Returned: `netWgt` = 1 463 697.405 kg, `cifvalue` = 4 844 676.22 USD, `primaryValue` = 4 844 676.22, `classificationCode` = `H6` (HS2022).

```bash
# Ukraine imports of chapter 08 (fruit & nuts) from World, 2024
curl "...?reporterCode=804&period=2024&partnerCode=0&cmdCode=08&flowCode=M"
```
Returned: `primaryValue` = **866 716 677.2 USD**, and `netWgt` = **0.0** — see gotcha G3.

```bash
# Ukraine imports of HS 0806 (grapes), 2024, all partners (partnerCode omitted)
curl "...?reporterCode=804&period=2024&cmdCode=0806&flowCode=M"
```
Returned 46 rows. Top partners by value: **792 (Türkiye) 28 876 282.93 USD / 21 385 004 kg**, **699 (India) 8 651 222.01**, **498 (Moldova) 6 806 764.53**.

### Annual coverage for Ukraine as reporter (record counts, HS 0902 ← China)

| Year | Records |
|---|---|
| 2019 | 14 |
| 2020 | 20 |
| 2021 | 17 |
| 2022 | 19 |
| 2023 | 1 |
| 2024 | 2 |
| 2025 | **0** |

Ukraine reports through 2024. **2025 is not reported yet** — the latest complete annual year is 2024.

### Mirror flows (partner reports exports to Ukraine) — verified working

`reporterCode={partner}&partnerCode=804&flowCode=X`, period 2024, HS 0902:

| Reporter | Records | Value USD |
|---|---|---|
| Poland (616) | 1 | 5 090 248.0 |
| China (156) | 1 | 3 024 113.0 |
| Türkiye (792) | 16 | 40 299.0 |
| Germany (276) | 12 | 427 278.366 |

This enables a **mirror-gap** indicator (Ukraine-reported imports vs partner-reported exports).

### Monthly data — verified working

`/C/M/HS?...&period=202401,202406,202412` returned 400 records for one HS code — close to the 500 cap, so monthly queries must be narrow.

### Gotchas (all observed, not assumed)

- **G1 — Rate limit ≈ 1 request/second.** A tight loop produced `{"statusCode": 429, "message": "Rate limit is exceeded. Try again in 1 seconds."}` with HTTP 429. A naive client silently reads `count: None`. **Must implement a 1 req/s throttle plus 429 retry with backoff.**
- **G2 — All descriptive fields come back `null`.** `reporterISO`, `reporterDesc`, `partnerISO`, `partnerDesc`, `cmdDesc`, `flowDesc`, `qtyUnitAbbr` are all null on the preview endpoint. Only numeric codes are returned. **Reference tables must be joined locally** (see §4).
- **G3 — `netWgt` is 0 at aggregate levels.** Chapter-level (HS2) queries return weight 0. Unit price (USD/kg) is only computable at HS4/HS6 leaf level.
- **G4 — Duplicate rows.** The same partner appears more than once per query (different `customsCode` / `mosCode` / `motCode` dimensions). **Deduplication is required** before computing shares or rankings.
- **G5 — 500 records per call maximum** on the free preview endpoint.
- **G6 — Annual lag.** Latest annual year is ~1 year behind the current date.

---

## 2. World Bank Indicators API (no authentication)

**Base:** `https://api.worldbank.org/v2/country/{ISO3;ISO3}/indicator/{code}?date=YYYY:YYYY&format=json&per_page=N`

Verified indicators and latest available values:

| Indicator code | Meaning | Latest data | Sample values |
|---|---|---|---|
| `LP.LPI.OVRL.XQ` | LPI overall (1–5) | **2022** | UKR 2.7 · POL 3.6 · CHN 3.7 · ESP 3.9 · TUR 3.4 · IND 3.4 · EGY 3.1 · MDA 2.5 |
| `LP.LPI.INFR.XQ` | LPI: trade & transport infrastructure quality | 2022 | UKR 2.4 · POL 3.5 · CHN 4.0 |
| `LP.LPI.CUST.XQ` | LPI: customs clearance efficiency | 2022 | UKR 2.4 · POL 3.4 · CHN 3.3 |
| `LP.LPI.TIME.XQ` | LPI: shipments arrive within expected time | 2022 | UKR 3.1 · POL 3.9 · ESP 4.2 |
| `LP.LPI.TRAC.XQ` | LPI: ability to track and trace | 2022 | UKR 2.6 · POL 3.8 · ESP 4.1 |
| `IS.SHP.GOOD.TU` | Container port traffic (TEU) | **2024** for most | CHN 299 703 800 · ESP 18 114 517 · IND 23 898 000 · TUR 13 507 070 · POL 3 270 784 · **UKR only 2021: 1 022 376** |
| `TM.TAX.MRCH.SM.AR.ZS` | Tariff rate, applied, simple mean, all products (%) | 2022 | UKR 2.09 · POL 1.95 · CHN 5.36 · IND 10.06 · TUR 7.48 |
| `TM.TAX.MRCH.WM.AR.ZS` | Tariff rate, applied, weighted mean (%) | 2022 | UKR 1.86 · CHN 2.18 · IND 4.59 |
| `NE.IMP.GNFS.ZS` | Imports of goods and services (% of GDP) | **2024** | MDA 57.3 · POL 48.2 · TUR 27.0 · IND 23.9 · CHN 17.5 |

**Not available:** `IC.IMP.CSBC.CD` (cost to import) returned no data — the Doing Business cost/time-to-import series is discontinued.

Gotchas:

- **LPI is not an annual series.** Latest is 2022 for every country tested. Treat LPI as a **structural constant**, not a trend.
- Ukraine's container port traffic is stale (2021) — do not compare it against partners' 2024 values without labelling the year.
- Response shape is `[metadata, [rows]]`; rows carry `value: null` for missing years. Filter nulls before use.

---

## 3. WITS TRAINS — applied tariffs (no authentication)

**Base:** `https://wits.worldbank.org/API/V1/SDMX/V21/datasource/TRN/reporter/{rep}/partner/{partner}/product/{hs6}/year/{year}/datatype/reported?format=JSON`

Verified for Ukraine (reporter 804), partner `000` (= MFN / world):

| HS6 | Product | Year | Rate |
|---|---|---|---|
| 080610 | Grapes, fresh | 2022 | **10** |
| 090210 | Green tea | 2022 | **10** |
| 020230 | Beef, boneless, frozen | 2022 | **15** |
| 330499 | Cosmetics/skin care | 2022 | **6.5** |
| 080610 | Grapes, fresh | 2018, 2020, 2021, 2022, 2023 | 10 in every year |

Gotchas:

- **W1 — Default Python `urllib` User-Agent is blocked (HTTP 403).** Requests must send a browser-like `User-Agent`. This was reproduced: identical URLs returned 200 via curl and 403 via `python-urllib`.
- **W2 — Slow and occasionally times out.** Some calls exceeded 45 s. **Caching is mandatory**; this cannot be a hot path.
- **W3 — Preferential rates by partner are not available** for the combinations tested: partner `918` (EU), `156` (China), `792` (Türkiye) all returned **HTTP 404**. Only MFN (`000`) works. Consequence: **FTA preferences (e.g. the EU DCFTA, where many rates are 0%) are NOT in the data.** The tool must present the rate as `duty_basis: MFN` and flag that a preference may apply.
- Response format is SDMX-JSON — the rate is buried in `dataSets[0].series[key].observations`. Requires a dedicated parser, not a simple field read.

---

## 4. Comtrade reference files (no authentication, downloadable)

All returned HTTP 200 and are suitable for vendoring into the repository:

| File | Size | Contents |
|---|---|---|
| `https://comtradeapi.un.org/files/v1/app/reference/Reporters.json` | 80.8 KB | Reporter codes with `reporterCodeIsoAlpha2/3`, names, effective dates |
| `https://comtradeapi.un.org/files/v1/app/reference/partnerAreas.json` | 96.3 KB | Partner area codes and names |
| `https://comtradeapi.un.org/files/v1/app/reference/H6.json` | 1.75 MB | **Full HS2022 classification** — id, text, parent, `isLeaf`, `aggrlevel`, `standardUnitAbbr` |

These solve gotcha G2 (null descriptions) and enable HS-code validation and product-name search **offline**. `H6.json` matches the `classificationCode: "H6"` returned by the trade calls.

---

## 5. data.gov.ua CKAN API (no authentication)

Works: `https://data.gov.ua/api/3/action/package_search?fq=organization:state-customs-service&rows=60` → **32 datasets** for the State Customs Service.

**Important correction to an earlier assumption.** The two datasets that sounded most useful are *not* usable data:

| Dataset | Reality after download |
|---|---|
| «Знеособлена аналітична інформація» (`analyticalinfo.csv`, 3.2 KB) | **A link catalogue, not data.** 8 rows with columns `uid,title,acceptedDate,issuedDate,type,url,creatorName,publisherName,publisherId`. Each row points to a *news post* on customs.gov.ua, e.g. monthly turnover announcements for Jan–Jul 2026. |
| «Ставки ввізного та вивізного мита» (`dutyrates.csv`, 3.8 KB) | **A link catalogue of legal acts.** 6 rows pointing to downloadable files on customs.gov.ua. Row 1 = «Ставки ввізного мита» (Закон 2697-IX «Про Митний тариф України»); rows 2–6 are *export* duties on narrow categories (livestock, hides, oilseeds, ferrous scrap, gas). |

So: **there is no granular UKTZED-level export/import operations CSV on data.gov.ua.** The tariff data we actually use comes from WITS (§3), not from here.

The link catalogue *is* still useful as the discovery path to the monthly turnover news posts — which is exactly what the Playwright scrape targets.

---

## 6. Access restrictions observed

| Target | Result from probe environment | Consequence |
|---|---|---|
| `customs.gov.ua/web/content/...` (direct file download) | **HTTP 403**, Akamai edge (`errors.edgesuite.net` reference) | Cannot be a runtime dependency from arbitrary networks. Confirmed accessible from the developer's Ukrainian connection. Playwright runs a real browser locally, which is the supported path. Any needed file must be **vendored into the repo manually**, not fetched at runtime. |
| `wits.worldbank.org` with default `python-urllib` UA | HTTP 403 | Set a browser `User-Agent`. |

**Do not** attempt to bypass bot protection with copied session cookies or Akamai tokens: those are secrets, the assignment forbids committing secrets, and it is not a legitimate access path. Playwright with a real local browser is the intended mechanism.

---

## 7. Consequences for design

| Finding | Design requirement it creates |
|---|---|
| G1 rate limit | Token-bucket throttle at 1 req/s + retry with backoff on 429; surfaced as a distinct `RATE_LIMITED` error, never as an empty result |
| G2 null descriptions | Vendored reference files (§4) + a local join/validation layer |
| G3 zero weight at HS2 | Unit price only at HS4/HS6; refuse or flag at HS2 |
| G4 duplicate rows | Explicit deduplication before shares/rankings; document the dedup key |
| G5 500-record cap | Narrow queries; paginate or aggregate deliberately; log when truncation occurs |
| G6 + 2025 missing | Data-vintage label on every output; the "latest year" is resolved at runtime, not hardcoded |
| LPI static at 2022 | Present as structural factor with an explicit "as of 2022" label |
| W1 UA blocking | Explicit `User-Agent` header in the HTTP client |
| W2 slow/timeouts | Mandatory cache + fixtures; generous timeouts; graceful degradation |
| W3 MFN only | `duty_basis: "MFN"` in output + `fta_preference_possible` flag; never claim the effective paid rate |
| §6 customs 403 | Playwright (local browser) is the only sanctioned access path; nothing fetched from customs.gov.ua by the Python server |
| No freight-rate source anywhere | Transport cost must be **modelled and labelled `estimated`**, never presented as a market rate |

---

## 8. Reproducing these probes

Probe scripts used during this investigation are throwaway; the repository will contain the permanent equivalents under `scripts/` and the recorded responses under `fixtures/`. Minimum smoke test for the defence:

```bash
# 1. Comtrade reachable, no key
curl -s "https://comtradeapi.un.org/public/v1/preview/C/A/HS?reporterCode=804&period=2024&cmdCode=0806&flowCode=M" | head -c 300

# 2. World Bank reachable, no key
curl -s "https://api.worldbank.org/v2/country/UKR;TUR/indicator/LP.LPI.OVRL.XQ?date=2022&format=json"

# 3. WITS reachable, needs UA header
curl -s -A "Mozilla/5.0" "https://wits.worldbank.org/API/V1/SDMX/V21/datasource/TRN/reporter/804/partner/000/product/080610/year/2022/datatype/reported?format=JSON" | head -c 300
```
