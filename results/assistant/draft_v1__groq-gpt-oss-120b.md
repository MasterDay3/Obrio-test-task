# Assistant eval: draft prompt `draft_v1`, model `groq-gpt-oss-120b`

| metric | value |
|---|---|
| tickets | 14 |
| retrieval_hit_rate | 92.9 |
| citation_validity | 97.3 |
| invented_citations | 2 |
| all_tones_present | 100.0 |
| short_within_limit | 100.0 |
| tones_distinct | 100.0 |
| language_match | 100.0 |
| human_flag_accuracy | 100.0 |
| latency_avg_s | 3.62 |
| cost_per_ticket_usd | 0.001389 |

| id | lang | expected → retrieved | citations ok/proposed | tones distinct (max sim) | lang | human exp→act |
|---|---|---|---|---|---|---|
| T01 | en | double-charge → double-charge, refund-policy ✅ | 5/5 | ✅ (0.28) | ✅ | -→- ✅ |
| T03 | en | trial-terms, refund-policy → trial-terms, refund-policy ✅ | 6/6 | ✅ (0.3) | ✅ | -→- ✅ |
| T05 | en | login-magic-link → login-magic-link, account-security ✅ | 6/6 | ✅ (0.41) | ✅ | -→- ✅ |
| T06 | en | expert-conduct → expert-conduct, account-security ✅ | 3/5 | ✅ (0.28) | ✅ | H→H ✅ |
| T09 | en | account-deletion → account-deletion, edit-birth-data ✅ | 6/6 | ✅ (0.44) | ✅ | H→H ✅ |
| T11 | en | reading-disclaimer → reading-disclaimer ✅ | 3/3 | ✅ (0.34) | ✅ | H→H ✅ |
| T18 | uk | double-charge, refund-policy → double-charge, refund-policy ✅ | 5/5 | ✅ (0.17) | ✅ | -→- ✅ |
| T21 | es | edit-birth-data → edit-birth-data, how-horoscopes-work, cancel-android ✅ | 6/6 | ✅ (0.35) | ✅ | -→- ✅ |
| T22 | de | double-charge, cancel-web → double-charge, cancel-web, cancel-android ✅ | 6/6 | ✅ (0.45) | ✅ | -→- ✅ |
| T23 | uk | app-crash → app-crash, edit-birth-data, how-horoscopes-work ✅ | 6/6 | ✅ (0.31) | ✅ | -→- ✅ |
| T24 | en | how-horoscopes-work → how-horoscopes-work, refund-policy, expert-conduct ✅ | 9/9 | ✅ (0.29) | ✅ | -→- ✅ |
| T30 | en | expert-conduct → expert-conduct ✅ | 5/5 | ✅ (0.34) | ✅ | H→H ✅ |
| T40 | en | minor-purchases → minor-purchases, refund-policy ✅ | 6/6 | ✅ (0.3) | ✅ | H→H ✅ |
| T08 | en | (none) → payment-failed, refund-policy ❌ | 0/0 | ✅ (0.29) | ✅ | H→H ✅ |
