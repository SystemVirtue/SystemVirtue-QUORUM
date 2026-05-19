# Benchmarks

The eval runner is scaffolded in `apps/eval-runner`.

Suites to integrate:

- HumanEval+
- MBPP+
- BigCodeBench
- SWE-Bench-Lite
- LiveCodeBench
- MMLU-Pro coding subset
- GPQA-diamond
- SystemVirtue custom 200 OSS bug corpus
- OWASP Top 10 reproduction set plus curated CVEs

Metrics:

- pass@1
- pass@5
- latency p50/p95
- dollar-per-pass equivalent
- inter-member agreement rate
- dissent-correctness correlation
- false-confidence rate
- sycophancy index
- hallucination rate
- risk detection
- test quality
- critique acceptance rate

No benchmark numbers are published until actual runs produce them.
