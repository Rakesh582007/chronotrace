# Sources for `analytes.yaml`

Where each field in the analyte dictionary comes from, and how far it has been checked. The file is used for decision support. Anything marked **unverified** must not be shown to a judge or clinician as a cited value until it has been checked.

## Verification status (26 Sep 2026)

| Field | Status | How it was checked |
| --- | --- | --- |
| LOINC codes and names | **Verified** | All 23 codes (20 primary, plus 18262-6 direct LDL, 3094-0 BUN and the unused 59261-8) looked up in the NLM Clinical Tables LOINC API (`clinicaltables.nlm.nih.gov/api/loinc_items/v3`). `loinc_name` is the LOINC long common name returned there. The validator also checks every code's mod-10 check digit. |
| Unit conversion factors | Derived | From molar masses and standard definitions (see below). Checked by round-trip tests in `tests/test_analytes.py`. |
| eGFR equation | Verified against paper | CKD-EPI 2021 coefficients from Inker et al., *N Engl J Med* 2021;385:1737-49. Test values match a hand calculation of the equation. |
| Reference ranges | Partly sourced | Guideline cut-offs where one exists (ADA, KDIGO, NCEP ATP III, WHO). Other ranges are typical Indian lab ranges and are assay- and lab-specific. Each entry names its source. |
| RCV: CVi, HbA1c | **Verified** | Median CVi 1.7% (IQR 1.3–2.2) in healthy subjects, systematic review of 111 studies, [PLOS ONE 2023](https://journals.plos.org/plosone/article?id=10.1371%2Fjournal.pone.0289085). Diabetic cohorts show about 8% CVi, which includes true glycaemic change, so the healthy CVi is used as the noise estimate. |
| RCV: CVi, UACR | **Unverified (no meta-analysis exists)** | The EFLM systematic review ([Aslan et al., *Clin Chim Acta* 2025;566:120032](https://www.sciencedirect.com/science/article/abs/pii/S000989812402285X), online Nov 2024) found no studies eligible for meta-analysis of urine albumin or ACR. The 31% CVi comes from older individual studies. |
| RCV: CVi, other analytes | **Unverified** | Values are recalled from the EFLM Biological Variation Database (biologicalvariation.eu). The site is a JavaScript app and could not be read from this environment. Check each CVi there before the demo. |
| RCV: CVa (analytical) | Assumed | Typical analytical CV for each assay type. Should be replaced by the lab's own internal quality control (IQC) CV where known. |

## Reference change value (RCV)

Two-sided 95% RCV for two results from the same patient:

```
RCV% = 1.96 × √2 × √(CVi² + CVa²)
```

The validator recomputes this from `cv_i` and `cv_a` and fails if `percent` does not match within 0.1 percentage points.

Special cases:

- **Postprandial glucose**: `not_established`. There is no biological variation data for post-meal glucose because meal content and timing are not standardised. Step 6 should use slope over 3+ reports only.
- **eGFR**: derived from creatinine. Its RCV is propagated from the creatinine RCV through the equation's −1.200 exponent: `1 − (1 + RCV_creat)^−1.2` ≈ 15.4%. This is not an independently published RCV.
- **UACR (87%)**: no meta-analysed CVi exists (see table above), so this RCV is a rough estimate. It stays `unverified` until a BIVAC-compliant estimate is published.
- **UACR and triglycerides (56%)**: CVi is large, so the symmetric formula understates how far a value must *fall* to be significant. Step 6 should consider the log-normal (asymmetric) RCV for these.

To verify an RCV: open the analyte in the EFLM database, copy the meta-analysis CVi, set `cv_i`, recompute `percent`, change `status` to `verified` and put the database URL and access date in `source`.

## Reference range sources

| Source | Used for |
| --- | --- |
| American Diabetes Association, *Standards of Care in Diabetes 2025*, section 2 | HbA1c, fasting glucose |
| KDIGO 2024 Clinical Practice Guideline for CKD | eGFR categories, UACR categories |
| NCEP ATP III (2002) | Total cholesterol, LDL, HDL, triglycerides |
| WHO haemoglobin thresholds for anaemia | Haemoglobin lower limits |
| Typical Indian lab ranges (lab-specific) | Creatinine, urea, sodium, potassium, TSH, free T4, ALT, AST, haemoglobin upper limits, platelets, WBC, postprandial glucose |

Reference ranges are context only. Flags come from the patient's own baseline and the RCV (`docs/decisions.md` #2, #3). The range printed on each source report is kept alongside the value in later steps.

## Unit conversion factors

`canonical = reported × factor + offset`

| Analyte | Conversion | Basis |
| --- | --- | --- |
| Glucose | mmol/L × 18.016 → mg/dL | Molar mass 180.16 g/mol |
| Creatinine | µmol/L × 0.011310 → mg/dL | 1 mg/dL = 88.42 µmol/L |
| Urea | mmol/L × 6.006 → mg/dL | Molar mass 60.06 g/mol |
| Urea from BUN | BUN mg/dL × 2.1437 → urea mg/dL | 60.06 / 28.02 (two N atoms) |
| HbA1c | IFCC mmol/mol × 0.0915 + 2.15 → NGSP % | IFCC–NGSP master equation |
| UACR | mg/mmol × 8.84 → mg/g | Creatinine molar mass 113.12 g/mol |
| Free T4 | pmol/L × 0.07770 → ng/dL | 1 ng/dL = 12.87 pmol/L |
| Cholesterol, LDL, HDL | mmol/L × 38.67 → mg/dL | Cholesterol molar mass 386.65 g/mol |
| Triglycerides | mmol/L × 88.57 → mg/dL | Triolein molar mass ≈ 885.7 g/mol |
| Haemoglobin | g/L × 0.1; mmol/L (monomer) × 1.611 → g/dL | Hb monomer 16.11 kDa |
| ALT, AST | µkat/L × 60 → U/L | 1 µkat = 60 µmol/min |
| Platelets, WBC | lakh/cumm × 100; /cumm × 0.001 → 10³/µL | 1 lakh = 100,000; 1 cumm = 1 µL |

## Synonyms

Synonyms are spellings seen on Indian lab reports (e.g. SGPT, FBS, PPBS, TLC, "S. Creatinine"). They were written from general familiarity with Indian report formats, not collected from a specific set of reports. Step 9 (real-report evaluation) should add any names that fail to match. The validator ensures no synonym points to two analytes. Short generic names such as `Cholesterol` or `Urea` rely on the matcher trying longer names first (for example "LDL Cholesterol" before "Cholesterol").
