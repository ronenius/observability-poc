---
name: spl
license: Apache-2.0
description: Write, validate, and optimize Splunk Search Processing Language (SPL) queries. Covers index/sourcetype filtering, streaming vs transforming commands, `stats` / `eventstats` / `streamstats` / `timechart` aggregations, `eval` functions and conditionals, regex field extraction (`rex`), JSON/XML parsing (`spath`), latency percentiles (`perc95`, `p99`), error rate calculations, avoiding slow `transaction`/`join` antipatterns, `tstats` acceleration, time range constraints (`earliest`/`latest`), and performance tuning for high-volume log data. Use when writing Splunk searches, fixing slow dashboards, extracting fields from logs, calculating metrics from events, debugging SPL syntax errors, or optimizing queries for Splunk Enterprise and Splunk Cloud.
---

# Splunk Search Processing Language (SPL) Query Patterns

> **Docs**: https://docs.splunk.com/Documentation/Splunk/latest/SearchReference/WhatsInThisManual

SPL chains commands using pipes (`|`) to retrieve, filter, extract, and transform log and metric events.

**Golden rules for fast SPL:**
1. **Filter as far left as possible:** Always specify `index=... sourcetype=...` and specific keywords before the first pipe. Splunk filters through indexed lexicon on indexers.
2. **Always bound time:** Specify explicit `earliest=` and `latest=` in search terms or job parameters to avoid scanning full indexes.
3. **Avoid leading wildcards:** `*error` disables index lookups; use `error*` or exact terms.
4. **Prefer `stats` over `transaction` / `join`:** `stats` is distributed across indexers and uses significantly less memory.
5. **Prune fields early:** Drop unused payload with `| fields + field1, field2, field3` before heavy processing.

---

## Prerequisites

- A Splunk Enterprise or Splunk Cloud search head endpoint (`https://<host>:8089` for REST API, or `splunkctl` CLI)
- The SPL pattern library in [`references/patterns.md`](references/patterns.md)

---

## Common Workflows

### 1. Write + validate a search query

```bash
# 0. Point at your Splunk Search Head REST API
SPLUNK_HOST=https://localhost:8089
AUTH="admin:changeme"

# 1. Sketch the query — for "5xx error rate per service over the last 15 minutes":
SEARCH='search index=app_logs sourcetype=api earliest=-15m latest=now
| eval is_error=if(status>=500, 1, 0)
| stats count as total sum(is_error) as errors by service
| eval error_rate_pct=round((errors / if(total>0, total, 1)) * 100, 2)
| sort - error_rate_pct'

# 2. Execute as a bounded oneshot search via curl:
curl -k -u "$AUTH" "$SPLUNK_HOST/services/search/jobs/oneshot" \
  -d output_mode=json \
  --data-urlencode "search=$SEARCH" | jq '.results[]'

# Alternatively, using splunkctl CLI:
# splunkctl --yes search export "$SEARCH" --maxout 20 --output json
```

### 2. Common patterns to copy

**Request rate and error percentage by service:**

```spl
index=prod_logs sourcetype=access_log earliest=-1h latest=now
| eval is_error=if(status>=500, 1, 0)
| stats count as total_requests sum(is_error) as total_errors by service
| eval error_pct=round((total_errors / if(total_requests>0, total_requests, 1)) * 100, 2)
| sort - error_pct
```

**p95 and p99 latency by endpoint:**

```spl
index=app_logs sourcetype=microservice earliest=-4h latest=now
| stats count perc50(duration_ms) as p50 perc95(duration_ms) as p95 perc99(duration_ms) as p99 by endpoint
| where count > 100
| sort - p95
```

**Timechart trend (requests per minute by HTTP status class):**

```spl
index=edge_logs sourcetype=nginx earliest=-24h latest=now
| eval status_class=case(status>=200 AND status<300, "2xx", status>=400 AND status<500, "4xx", status>=500, "5xx", true(), "other")
| timechart span=5m count by status_class
```

**Session correlation without `transaction` (high performance):**

```spl
index=app_logs sourcetype=auth earliest=-2h latest=now
| stats min(_time) as start_time max(_time) as end_time range(_time) as duration_sec values(action) as actions values(status) as statuses count by session_id
| where count > 1
| eval start_time=strftime(start_time, "%Y-%m-%d %H:%M:%S"), end_time=strftime(end_time, "%Y-%m-%d %H:%M:%S")
| sort - duration_sec
```

Full library (JSON extraction, regex parsing, subsearches, lookups, `tstats`, eventstats): [`references/patterns.md`](references/patterns.md).

---

## Performance Rules & Best Practices

1. **Indexer-Side Reduction**:
   - `stats`, `chart`, and `timechart` are transforming commands that push aggregation work down to indexers before returning small summary payloads to the search head.
   - Centralized commands (like `dedup`, `sort`, `transaction`, `head`) pull raw events to the search head before processing. Push filtering (`where`, `search`) and reduction (`stats`) before them.

2. **Replace `join` with `stats`:**
   ```spl
   # AVOID (Memory limit on subsearch results, slow):
   index=auth | join user_id [ search index=payments ]

   # PREFER (Unified scan aggregated by key):
   (index=auth OR index=payments)
   | stats values(auth_status) as auth_status values(amount) as amount by user_id
   ```

3. **Fast Metric and Count Acceleration with `tstats`:**
   When searching indexed fields or accelerated data models:
   ```spl
   | tstats count where index=firewall by sourcetype, action
   ```

---

## Common Bugs & Gotchas

- **Leading wildcard `*error`:** Forces full lexicon scan on indexers. Replace with `error*` or exact keywords.
- **Unbounded search:** Forgetting `earliest=` / `latest=` searches all data from epoch 0.
- **Case sensitivity:** Splunk keywords and operators (`AND`, `OR`, `NOT`, `AS`, `BY`) must be UPPERCASE. Field names are case-sensitive; search terms are case-insensitive.
- **Divide by zero:** Always guard denominator: `errors / if(total>0, total, 1)`.
- **Missing `spath` on JSON:** Searching `message.userId="123"` may fail if JSON is not parsed. Use `| spath path=userId output=user_id` or index extraction.

---

## Resources

- [Splunk Search Reference](https://docs.splunk.com/Documentation/Splunk/latest/SearchReference/WhatsInThisManual)
- [Splunk Search Optimization Guide](https://help.splunk.com/en/splunk-enterprise/search/search-manual/10.4/optimize-searches/about-search-optimization)
- [Splunk Quick Tips for Optimization](https://help.splunk.com/en/splunk-enterprise/search/search-manual/10.4/optimize-searches/quick-tips-for-optimization)
