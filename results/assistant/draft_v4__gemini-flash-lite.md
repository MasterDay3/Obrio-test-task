# Assistant eval: draft prompt `draft_v4`, model `gemini-flash-lite`

| metric | value |
|---|---|
| tickets | 14 |
| retrieval_hit_rate | 92.9 |
| citation_validity | 100.0 |
| invented_citations | 0 |
| all_tones_present | 100.0 |
| short_within_limit | 100.0 |
| tones_distinct | 100.0 |
| language_match | 100.0 |
| human_flag_accuracy | 100.0 |
| tickets_with_unsupported_numbers | 0 |
| tickets_with_internal_leaks | 0 |
| failed_tickets | 0 |
| latency_avg_s | 3.56 |
| cost_per_ticket_usd | 0.002935 |

| id | lang | expected → retrieved | citations ok/proposed | tones distinct (max sim) | lang | human exp→act |
|---|---|---|---|---|---|---|
| T01 | en | double-charge → double-charge, refund-policy ✅ | 3/3 | ✅ (0.32) | ✅ | -→- ✅ |
| T03 | en | trial-terms, refund-policy → trial-terms, refund-policy ✅ | 3/3 | ✅ (0.39) | ✅ | -→- ✅ |
| T05 | en | login-magic-link → login-magic-link, account-security ✅ | 6/6 | ✅ (0.29) | ✅ | -→- ✅ |
| T06 | en | expert-conduct → expert-conduct ✅ | 3/3 | ✅ (0.38) | ✅ | H→H ✅ |
| T09 | en | account-deletion → account-deletion, edit-birth-data ✅ | 3/3 | ✅ (0.28) | ✅ | H→H ✅ |
| T11 | en | reading-disclaimer → reading-disclaimer ✅ | 6/6 | ✅ (0.45) | ✅ | H→H ✅ |
| T18 | uk | double-charge, refund-policy → double-charge, refund-policy ✅ | 3/3 | ✅ (0.36) | ✅ | -→- ✅ |
| T21 | es | edit-birth-data → edit-birth-data, how-horoscopes-work, account-security ✅ | 6/6 | ✅ (0.26) | ✅ | -→- ✅ |
| T22 | de | double-charge, cancel-web → double-charge, refund-policy, trial-terms ✅ | 3/3 | ✅ (0.28) | ✅ | -→- ✅ |
| T23 | uk | app-crash → app-crash, edit-birth-data ✅ | 3/3 | ✅ (0.33) | ✅ | -→- ✅ |
| T24 | en | how-horoscopes-work → how-horoscopes-work, refund-policy ✅ | 6/6 | ✅ (0.51) | ✅ | -→- ✅ |
| T30 | en | expert-conduct → expert-conduct, expert-chat-billing ✅ | 3/3 | ✅ (0.34) | ✅ | H→H ✅ |
| T40 | en | minor-purchases → minor-purchases, refund-policy ✅ | 3/3 | ✅ (0.35) | ✅ | H→H ✅ |
| T08 | en | (none) → payment-failed, refund-policy ❌ | 0/0 | ✅ (0.21) | ✅ | H→H ✅ |
