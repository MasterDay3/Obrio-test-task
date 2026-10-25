# Assistant eval: draft prompt `draft_v1`, model `gemini-flash-lite`

| metric | value |
|---|---|
| tickets | 14 |
| retrieval_hit_rate | 85.7 |
| citation_validity | 100.0 |
| invented_citations | 0 |
| all_tones_present | 78.6 |
| short_within_limit | 78.6 |
| tones_distinct | 42.9 |
| language_match | 100.0 |
| human_flag_accuracy | 85.7 |
| latency_avg_s | 3.33 |
| cost_per_ticket_usd | 0.00248 |

| id | lang | expected → retrieved | citations ok/proposed | tones distinct (max sim) | lang | human exp→act |
|---|---|---|---|---|---|---|
| T01 | en | double-charge → double-charge, refund-policy ✅ | 3/3 | ✅ (0.54) | ✅ | -→- ✅ |
| T03 | en | trial-terms, refund-policy → trial-terms, refund-policy ✅ | 4/4 | ✅ (0.51) | ✅ | -→- ✅ |
| T05 | en | login-magic-link → login-magic-link, account-security ✅ | 6/6 | ❌ (0.81) | ✅ | -→- ✅ |
| T06 | en | expert-conduct → expert-conduct, reading-disclaimer ✅ | 6/6 | ❌ (0.62) | ✅ | H→H ✅ |
| T09 | en | account-deletion → account-deletion, edit-birth-data ✅ | 3/3 | ❌ (0.77) | ✅ | H→H ✅ |
| T11 | en | reading-disclaimer → reading-disclaimer ✅ | 0/0 | ❌ (1.0) | ✅ | H→H ✅ |
| T18 | uk | double-charge, refund-policy → (none) ❌ | 0/0 | ❌ (1.0) | ✅ | -→H ❌ |
| T21 | es | edit-birth-data → edit-birth-data, how-horoscopes-work, account-security ✅ | 6/6 | ✅ (0.36) | ✅ | -→- ✅ |
| T22 | de | double-charge, cancel-web → double-charge, refund-policy ✅ | 3/3 | ✅ (0.45) | ✅ | -→- ✅ |
| T23 | uk | app-crash → app-crash, how-horoscopes-work, edit-birth-data ✅ | 3/3 | ✅ (0.42) | ✅ | -→- ✅ |
| T24 | en | how-horoscopes-work → how-horoscopes-work, refund-policy ✅ | 6/6 | ✅ (0.47) | ✅ | -→- ✅ |
| T30 | en | expert-conduct → expert-conduct, expert-chat-billing ✅ | 6/6 | ❌ (0.62) | ✅ | H→H ✅ |
| T40 | en | minor-purchases → minor-purchases, refund-policy ✅ | 0/0 | ❌ (1.0) | ✅ | H→H ✅ |
| T08 | en | (none) → cancel-ios, refund-policy ❌ | 0/0 | ❌ (0.83) | ✅ | H→- ❌ |
