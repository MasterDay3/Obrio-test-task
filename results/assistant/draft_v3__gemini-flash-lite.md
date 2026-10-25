# Assistant eval: draft prompt `draft_v3`, model `gemini-flash-lite`

| metric | value |
|---|---|
| tickets | 14 |
| retrieval_hit_rate | 92.9 |
| citation_validity | 100.0 |
| invented_citations | 0 |
| all_tones_present | 100.0 |
| short_within_limit | 100.0 |
| tones_distinct | 100.0 |
| language_match | 85.7 |
| human_flag_accuracy | 85.7 |
| tickets_with_unsupported_numbers | 1 |
| tickets_with_internal_leaks | 0 |
| failed_tickets | 0 |
| latency_avg_s | 3.42 |
| cost_per_ticket_usd | 0.002747 |

| id | lang | expected → retrieved | citations ok/proposed | tones distinct (max sim) | lang | human exp→act |
|---|---|---|---|---|---|---|
| T01 | en | double-charge → double-charge, refund-policy ✅ | 6/6 | ✅ (0.3) | ✅ | -→- ✅ |
| T03 | en | trial-terms, refund-policy → trial-terms, refund-policy ✅ | 3/3 | ✅ (0.38) | ✅ | -→- ✅ |
| T05 | en | login-magic-link → login-magic-link, account-security ✅ | 6/6 | ✅ (0.42) | ✅ | -→- ✅ |
| T06 | en | expert-conduct → expert-conduct, expert-chat-billing ✅ | 3/3 | ✅ (0.32) | ✅ | H→H ✅ |
| T09 | en | account-deletion → account-deletion, edit-birth-data ✅ | 3/3 | ✅ (0.33) | ✅ | H→H ✅ |
| T11 | en | reading-disclaimer → reading-disclaimer, how-horoscopes-work, edit-birth-data ✅ | 6/6 | ✅ (0.35) | ✅ | H→H ✅ |
| T18 | uk | double-charge, refund-policy → double-charge, refund-policy ✅ | 3/3 | ✅ (0.28) | ❌ | -→- ✅ |
| T21 | es | edit-birth-data → edit-birth-data, how-horoscopes-work, account-security ✅ | 6/6 | ✅ (0.42) | ✅ | -→- ✅ |
| T22 | de | double-charge, cancel-web → double-charge, refund-policy, cancel-web ✅ | 5/5 | ✅ (0.19) | ✅ | -→- ✅ |
| T23 | uk | app-crash → app-crash ✅ | 3/3 | ✅ (0.38) | ❌ | -→H ❌ |
| T24 | en | how-horoscopes-work → how-horoscopes-work, refund-policy ✅ | 6/6 | ✅ (0.43) | ✅ | -→H ❌ |
| T30 | en | expert-conduct → expert-conduct, expert-chat-billing ✅ | 3/3 | ✅ (0.37) | ✅ | H→H ✅ |
| T40 | en | minor-purchases → minor-purchases, refund-policy ✅ | 3/3 | ✅ (0.44) | ✅ | H→H ✅ |
| T08 | en | (none) → payment-failed, refund-policy ❌ | 0/0 | ✅ (0.35) | ✅ | H→H ✅ |
