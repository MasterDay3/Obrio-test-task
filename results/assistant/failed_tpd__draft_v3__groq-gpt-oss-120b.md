# Assistant eval: draft prompt `draft_v3`, model `groq-gpt-oss-120b`

| metric | value |
|---|---|
| tickets | 14 |
| retrieval_hit_rate | 71.4 |
| citation_validity | None |
| invented_citations | 0 |
| all_tones_present | 0.0 |
| short_within_limit | 0.0 |
| tones_distinct | 0.0 |
| language_match | 100.0 |
| human_flag_accuracy | 42.9 |
| tickets_with_unsupported_numbers | 0 |
| tickets_with_internal_leaks | 0 |
| failed_tickets | 14 |
| latency_avg_s | 10.76 |
| cost_per_ticket_usd | 0.000142 |

| id | lang | expected → retrieved | citations ok/proposed | tones distinct (max sim) | lang | human exp→act |
|---|---|---|---|---|---|---|
| T01 | en | double-charge → payment-failed ❌ | 0/0 | ❌ (1.0) | ✅ | -→H ❌ |
| T03 | en | trial-terms, refund-policy → trial-terms, cancel-web, double-charge ✅ | 0/0 | ❌ (1.0) | ✅ | -→H ❌ |
| T05 | en | login-magic-link → login-magic-link ✅ | 0/0 | ❌ (1.0) | ✅ | -→H ❌ |
| T06 | en | expert-conduct → expert-conduct ✅ | 0/0 | ❌ (1.0) | ✅ | H→H ✅ |
| T09 | en | account-deletion → account-deletion, edit-birth-data ✅ | 0/0 | ❌ (1.0) | ✅ | H→H ✅ |
| T11 | en | reading-disclaimer → reading-disclaimer ✅ | 0/0 | ❌ (1.0) | ✅ | H→H ✅ |
| T18 | uk | double-charge, refund-policy → (none) ❌ | 0/0 | ❌ (1.0) | ✅ | -→H ❌ |
| T21 | es | edit-birth-data → (none) ❌ | 0/0 | ❌ (1.0) | ✅ | -→H ❌ |
| T22 | de | double-charge, cancel-web → double-charge, cancel-web ✅ | 0/0 | ❌ (1.0) | ✅ | -→H ❌ |
| T23 | uk | app-crash → app-crash, edit-birth-data, how-horoscopes-work ✅ | 0/0 | ❌ (1.0) | ✅ | -→H ❌ |
| T24 | en | how-horoscopes-work → how-horoscopes-work, reading-disclaimer, refund-policy ✅ | 0/0 | ❌ (1.0) | ✅ | -→H ❌ |
| T30 | en | expert-conduct → (none) ❌ | 0/0 | ❌ (1.0) | ✅ | H→H ✅ |
| T40 | en | minor-purchases → minor-purchases, refund-policy, payment-failed ✅ | 0/0 | ❌ (1.0) | ✅ | H→H ✅ |
| T08 | en | (none) → (none) ✅ | 0/0 | ❌ (1.0) | ✅ | H→H ✅ |
