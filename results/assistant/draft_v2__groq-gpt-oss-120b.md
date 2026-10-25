# Assistant eval: draft prompt `draft_v2`, model `groq-gpt-oss-120b`

| metric | value |
|---|---|
| tickets | 14 |
| retrieval_hit_rate | 85.7 |
| citation_validity | 94.4 |
| invented_citations | 3 |
| all_tones_present | 85.7 |
| short_within_limit | 85.7 |
| tones_distinct | 85.7 |
| language_match | 85.7 |
| human_flag_accuracy | 100.0 |
| latency_avg_s | 9.5 |
| cost_per_ticket_usd | 0.001594 |

| id | lang | expected → retrieved | citations ok/proposed | tones distinct (max sim) | lang | human exp→act |
|---|---|---|---|---|---|---|
| T01 | en | double-charge → double-charge, refund-policy ✅ | 3/3 | ✅ (0.29) | ✅ | -→- ✅ |
| T03 | en | trial-terms, refund-policy → trial-terms, refund-policy, double-charge ✅ | 6/6 | ✅ (0.39) | ✅ | -→- ✅ |
| T05 | en | login-magic-link → login-magic-link, account-security ✅ | 6/6 | ✅ (0.32) | ✅ | -→- ✅ |
| T06 | en | expert-conduct → expert-conduct, account-security ✅ | 3/6 | ✅ (0.39) | ✅ | H→H ✅ |
| T09 | en | account-deletion → account-deletion, edit-birth-data ✅ | 3/3 | ✅ (0.33) | ✅ | H→H ✅ |
| T11 | en | reading-disclaimer → reading-disclaimer ✅ | 3/3 | ✅ (0.35) | ✅ | H→H ✅ |
| T18 | uk | double-charge, refund-policy → double-charge, refund-policy ✅ | 3/3 | ✅ (0.36) | ❌ | -→- ✅ |
| T21 | es | edit-birth-data → edit-birth-data, how-horoscopes-work, cancel-android ✅ | 6/6 | ✅ (0.25) | ✅ | -→- ✅ |
| T22 | de | double-charge, cancel-web → double-charge, cancel-web, cancel-android ✅ | 6/6 | ✅ (0.25) | ✅ | -→- ✅ |
| T23 | uk | app-crash → app-crash, edit-birth-data, how-horoscopes-work ✅ | 3/3 | ✅ (0.41) | ❌ | -→- ✅ |
| T24 | en | how-horoscopes-work → how-horoscopes-work, refund-policy, expert-conduct ✅ | 9/9 | ✅ (0.38) | ✅ | -→- ✅ |
| T30 | en | expert-conduct → (none) ❌ | 0/0 | ❌ (1.0) | ✅ | H→H ✅ |
| T40 | en | minor-purchases → minor-purchases, refund-policy ✅ | 0/0 | ❌ (1.0) | ✅ | H→H ✅ |
| T08 | en | (none) → payment-failed, refund-policy ❌ | 0/0 | ✅ (0.27) | ✅ | H→H ✅ |
