# OpenRouter Free Model Census

The free model census measures live OpenRouter `:free` model behavior over time. It is intentionally operational rather than glossy: the goal is to capture latency, availability, rate limits, empty outputs, model aliasing, noisy outputs, and cost reports exactly as observed.

## One-Shot Census

```bash
python apps/eval-runner/query_all_free_models.py --concurrency 4 --timeout 60
```

Outputs:

- `benchmarks/reports/openrouter_free_model_census_<timestamp>.json`
- `benchmarks/reports/openrouter_free_model_census_<timestamp>.md`

## Scheduled Census

For 100 one-minute intervals:

```bash
python apps/eval-runner/scheduled_free_model_census.py \
  --iterations 100 \
  --interval-seconds 60 \
  --concurrency 8 \
  --timeout 20 \
  --run-id free_census_100min_$(date -u +%Y%m%dT%H%M%SZ)
```

Outputs under `benchmarks/series/<run-id>/`:

- `manifest.json`: run configuration
- `raw_calls.jsonl`: append-only record of every model call
- `aggregate.json`: current aggregate after each iteration
- `aggregate.md`: human-readable aggregate after each iteration

By default, scheduled runs print one summary line per iteration and store per-call details in `raw_calls.jsonl`. Add `--verbose-probes` only for short debugging runs; printing every model call can create terminal backpressure and distort one-minute cadence.

To resume an interrupted run without duplicating completed iterations:

```bash
python apps/eval-runner/scheduled_free_model_census.py \
  --iterations 100 \
  --interval-seconds 60 \
  --concurrency 8 \
  --timeout 20 \
  --run-id <existing-run-id> \
  --resume
```

The runner refuses to append to an existing non-empty `raw_calls.jsonl` unless `--resume` is provided.

## Collating Partial Runs

To combine multiple scheduled census folders into one aggregate:

```bash
python apps/eval-runner/collate_free_model_census.py \
  benchmarks/series/free_census_partial_a \
  benchmarks/series/free_census_partial_b \
  --run-id collated_free_census
```

The collator writes a merged `raw_calls.jsonl`, `aggregate.json`, and `aggregate.md` under `benchmarks/series/<run-id>/`.

## Exporting Registry Health

To make the orchestrator use observed census availability, latency, rate-limit, timeout, and malformed-output data during free-model selection:

```bash
python apps/eval-runner/export_census_health.py \
  benchmarks/series/<run-id>/aggregate.json
```

This writes `seed/free_model_census_health.json`, which is intentionally git-ignored because it is local live telemetry. When present, the orchestrator registry overlays this snapshot onto live OpenRouter `/models` discovery; when absent, it falls back to seeded defaults.

For selection health, `availability_24h` is exported as usable exact-probe success rate, not raw HTTP-200 rate. The raw HTTP availability is preserved under each model's `source.http_availability_rate`, but empty or instruction-breaking outputs must not make a model look council-ready.

## Guardrails

- Requires `ALLOW_PAID_MODELS=false`.
- Fetches live OpenRouter `/models`.
- Calls only models where OpenRouter reports `prompt=0`, `completion=0`, and the model id ends with `:free`.
- Uses a hard per-call timeout to keep the minute cadence from being held hostage by one slow endpoint.
- Flags any nonzero reported cost.

## Interpreting The Data

Key fields:

- `success_rate`: exact-response success rate, not general intelligence.
- `availability_rate`: HTTP 200 rate, whether or not the output was usable.
- `rate_limited`: model returned HTTP 429.
- `empty_output`: HTTP 200 with no assistant content.
- `instruction_following_failed`: HTTP 200 but failed the exact probe.
- `returned_model_alias_or_variant`: OpenRouter returned a variant id for the requested model.
- `hard_timeout`: the local hard timeout stopped a slow call.
- `success_latency_trimmed_mean_ms`: latency average with tails trimmed.
- `success_latency_outliers_ms`: model-specific IQR outliers.

Use this census to seed model health and selection weights. Treat a single run as a snapshot; prefer the scheduled aggregate for claims.
