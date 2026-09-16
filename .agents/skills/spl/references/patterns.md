# Splunk Search Processing Language (SPL) Pattern Library

## 1. Filtering & Initial Retrieval

```spl
# Exact term & field matching (Left of first pipe)
index=web_logs sourcetype=access_combined status=500 host="web-prod-*"

# Boolean logic (Operators MUST be uppercase)
index=app_logs (env="production" OR env="staging") NOT log_level="DEBUG"

# Time bounds (Relative and absolute)
earliest=-15m latest=now
earliest=@d latest=now                    # From midnight today
earliest="10/12/2026:00:00:00" latest="10/12/2026:12:00:00"

# Pruning unused fields early to minimize memory
| fields + _time, host, service, status, duration_ms
```

---

## 2. Statistical Aggregations (`stats`)

```spl
# Basic counting and distinct count
| stats count, dc(user) as unique_users, dc(ip) as unique_ips by service

# Summary statistics on numeric fields
| stats count, avg(latency) as avg_lat, min(latency) as min_lat, max(latency) as max_lat by endpoint

# Percentiles (p50, p90, p95, p99)
| stats count, perc50(duration) as p50, perc95(duration) as p95, perc99(duration) as p99 by endpoint

# Collecting distinct values
| stats values(status) as distinct_statuses, list(event_id) as recent_ids by session_id
```

---

## 3. Time Series & Charting (`timechart` and `chart`)

```spl
# Request rate over time in 5-minute buckets
index=web_logs | timechart span=5m count by status

# Request rate per second over time (span=1m divided by 60)
index=web_logs | timechart span=1m eval(count/60) as rps by service

# Median and p95 latency trend
index=app_logs | timechart span=10m median(duration_ms) as p50, perc95(duration_ms) as p95

# Fill missing intervals with zero
index=web_logs | timechart span=1h count | fillnull value=0

# Cross-tabulation table (Status by Service)
index=web_logs | chart count over service by status
```

---

## 4. Windowed & Cumulative Stats (`eventstats` and `streamstats`)

```spl
# Calculate percentage of total without a subsearch (eventstats preserves raw events)
index=web_logs
| stats count as endpoint_count by endpoint
| eventstats sum(endpoint_count) as grand_total
| eval pct_of_total=round((endpoint_count / grand_total) * 100, 2)
| sort - pct_of_total

# Running count or cumulative sum per host
index=app_logs
| sort 0 _time
| streamstats count as event_sequence by host

# Moving average of latency over the last 5 events
index=app_logs
| sort 0 _time
| streamstats window=5 avg(duration_ms) as moving_avg_lat by endpoint
```

---

## 5. Eval Functions & Conditionals

```spl
# Case statements
| eval tier=case(
    latency < 100, "fast",
    latency < 500, "acceptable",
    latency >= 500, "slow",
    true(), "unknown"
  )

# If conditions
| eval error_flag=if(status>=500, 1, 0)

# Coalesce (first non-null value)
| eval effective_user=coalesce(authenticated_user, header_user, "anonymous")

# String matching and regex in eval
| eval is_admin=if(match(uri, "^/admin/.*"), "yes", "no")

# Date formatting and epoch math
| eval formatted_time=strftime(_time, "%Y-%m-%d %H:%M:%S")
| eval age_seconds=now() - _time
```

---

## 6. Parsing & Field Extraction (`rex` and `spath`)

```spl
# Extracting fields with Regular Expressions
| rex field=_raw "user=(?<username>[^\s,]+)\s+action=(?<action>\w+)"

# Extracting error code and message
| rex field=_raw "ERROR\s+\[(?<err_code>[A-Z0-9_-]+)\]:\s+(?<err_msg>.*)"

# Parsing JSON payload from raw log
| spath input=_raw
| spath input=message path=user.id output=user_id
| spath input=message path=items{} output=items_array

# Handling multi-value fields
| mvexpand items_array
```

---

## 7. Ratios, Rates, and SLA Monitoring

```spl
# 5xx error percentage with zero-guard
index=api_logs earliest=-1h
| eval is_5xx=if(status>=500, 1, 0)
| stats count as total_reqs, sum(is_5xx) as errors_5xx by service
| eval error_rate=round((errors_5xx / if(total_reqs>0, total_reqs, 1)) * 100, 3)
| where error_rate > 1.0
| sort - error_rate

# Success SLA compliance (99.9% availability target)
index=api_logs earliest=-30d
| eval success=if(status<500, 1, 0)
| stats count as total, sum(success) as success_count by service
| eval availability_pct=round((success_count / total) * 100, 3)
| eval meets_slo=if(availability_pct >= 99.9, "PASS", "FAIL")
```

---

## 8. High-Performance Sessionization (Replacing `transaction`)

```spl
# SLOW (Antipattern - memory intensive, single-threaded on search head):
# index=web_logs | transaction session_id maxpause=30m

# FAST (Best practice - distributed across indexers):
index=web_logs earliest=-2h latest=now
| stats min(_time) as first_seen,
        max(_time) as last_seen,
        range(_time) as duration_seconds,
        count as event_count,
        values(action) as actions,
        values(status) as statuses
  by session_id
| eval session_duration=tostring(duration_seconds, "duration")
| sort - duration_seconds
```

---

## 9. Subsearches and Lookups

```spl
# Subsearch: Filter by IP addresses that generated alerts
index=web_logs [ search index=security_alerts severity=high earliest=-24h | fields client_ip | rename client_ip as ip | dedup ip ]
| stats count by ip, uri

# Lookup enrichment
index=auth_logs
| lookup user_directory.csv username OUTPUT department, title, manager
| stats count by department, action

# Output to lookup table (admin only)
# | stats count by ip | outputlookup known_bad_ips.csv
```

---

## 10. Fast Accelerated Searches with `tstats`

```spl
# Fast event count from tsidx metadata (skips raw event decompression)
| tstats count where index=firewall by sourcetype

# Grouping by indexed fields
| tstats count where index=web_logs by host, status

# Aggregating accelerated Data Models (e.g. CIM Network_Traffic)
| tstats summariesonly=t count, sum(All_Traffic.bytes) as total_bytes
  from datamodel=Network_Traffic.All_Traffic
  by All_Traffic.src, All_Traffic.dest
```

---

## 11. Top, Rare, and Outlier Analysis

```spl
# Top 10 slowest endpoints
index=app_logs
| top limit=10 endpoint by service

# Detecting anomalous volume (using predict)
index=web_logs
| timechart span=15m count
| predict count as predicted algorithm=LLP future_timespan=0
| eval difference=abs(count - predicted)
| where difference > (predicted * 0.5)
```
