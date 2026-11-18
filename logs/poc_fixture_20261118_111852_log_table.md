# Control-Level Pipeline Log Table

- **Target:** `fixtures/poc_fixture.html`
- **VLM Model:** `gemini-3.5-flash-lite` (`runs=3`, `temperature=0.0`, `seed=42`)
- **Timestamp:** `20261118_111852`

| Control ID | Control Text / Tag | `axe-core` Result | Rule-Based Baseline | Model Label (Majority Vote) | Confidence | Rationale | Resolved Outcome (VLM + axe) | Resolved Outcome (Baseline + axe) |
| :--- | :--- | :--- | :--- | :--- | :---: | :--- | :--- | :--- |
| `ctrl_001` | Browse Product Catalog | `none` | `none` | **none** (3/3) | 1.00 | The evaluated control is a standard navigation button with neutral language and normal visual prominence, falling under none of the deceptive patterns. | **Normal** | Normal |
| `ctrl_002` | 2. Accessibility-Only Control (Missing Button Name) | `button-name` | `none` | **none** (3/3) | 1.00 | The inspected element is a standard interface component used for testing accessibility issues rather than implementing any deceptive dark patterns such as confirmshaming or preselected marketing consent. | **Accessibility-only** | Accessibility-only |
| `ctrl_003` | on | `none` | `preselected_marketing_consent` | **preselected_marketing_consent** (3/3) | 1.00 | The control is pre-selected (checked=true) upon load and directly relates to promotional/marketing communications based on its accompanying label text, satisfying the criteria for preselected_marketing_consent. | **Deceptive pattern-only** | Deceptive pattern-only |
| `ctrl_004` | Claim My 25% Discount | `none` | `none` | **none** (3/3) | 1.00 | The evaluated control is the primary accept button ('Claim My 25% Discount'). While the dialog contains confirmshaming in its decline link, the target control itself is the normal acceptance action and does not exhibit deceptive patterns. | **Normal** | Normal |
| `ctrl_005` | No thanks, I prefer paying full price and missing out | `color-contrast` | `confirmshaming` | **confirmshaming** (3/3) | 1.00 | The control pairs an acceptance option with a decline option whose wording uses guilt-inducing and emotionally loaded language, fulfilling the criteria for confirmshaming. | **Overlap** | Overlap |
| `ctrl_006` | on | `label` | `preselected_marketing_consent` | **preselected_marketing_consent** (3/3) | 1.00 | The control is a checkbox that is checked by default on page load and its associated label contains explicit promotional and marketing terminology, fitting the definition of preselected marketing consent. | **Overlap** | Overlap |
