# Classifier eval summary

| dataset | prompt | model | rules | category_acc | priority_acc | priority_within_1 | pass_rate | human_recall | human_precision | invalid_or_failed | latency_avg_s | latency_p95_s | cost_per_ticket_usd |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| holdout | v3 | gemini-flash-lite | on | 93.3 | 93.3 | 100.0 | 86.7 | 100.0 | 100.0 | 0 | 0.99 | 1.43 | 0.0006783 |
| holdout | v3 | groq-gpt-oss-120b | on | 93.3 | 100.0 | 100.0 | 93.3 | 100.0 | 100.0 | 0 | 1.13 | 1.72 | 0.0004135 |
| holdout | v3 | groq-gpt-oss-20b | on | 93.3 | 86.7 | 100.0 | 86.7 | 100.0 | 100.0 | 0 | 0.72 | 1.21 | 0.0001923 |
| main | v1 | gemini-flash-lite | on | 85.7 | 73.8 | 97.6 | 61.9 | 100.0 | 52.0 | 0 | 0.92 | 1.24 | 0.0003764 |
| main | v1 | groq-gpt-oss-120b | on | 78.6 | 61.9 | 97.6 | 50.0 | 100.0 | 40.6 | 0 | 0.83 | 1.09 | 0.0001909 |
| main | v1 | groq-gpt-oss-20b | on | 76.2 | 42.9 | 95.2 | 33.3 | 100.0 | 54.2 | 2 | 0.73 | 1.5 | 0.0001011 |
| main | v2 | gemini-flash-lite | on | 95.2 | 73.8 | 100.0 | 71.4 | 100.0 | 92.9 | 0 | 0.89 | 1.14 | 0.0005729 |
| main | v2 | groq-gpt-oss-120b | on | 97.6 | 76.2 | 100.0 | 76.2 | 100.0 | 92.9 | 0 | 2.18 | 7.01 | 0.0003071 |
| main | v2 | groq-gpt-oss-20b | on | 92.9 | 83.3 | 100.0 | 81.0 | 100.0 | 100.0 | 0 | 2.81 | 6.62 | 0.0001574 |
| main | v3 | gemini-flash-lite | on | 95.2 | 100.0 | 100.0 | 95.2 | 100.0 | 100.0 | 0 | 0.98 | 1.14 | 0.000713 |
| main | v3 | groq-gpt-oss-120b | on | 97.6 | 95.2 | 100.0 | 95.2 | 100.0 | 86.7 | 0 | 1.05 | 1.41 | 0.0004098 |
| main | v3 | groq-gpt-oss-20b | on | 97.6 | 92.9 | 100.0 | 90.5 | 100.0 | 86.7 | 0 | 0.63 | 1.0 | 0.0001934 |
