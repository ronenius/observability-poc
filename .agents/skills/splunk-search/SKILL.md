---
name: splunk-search
description: Run bounded, read-only Splunk SPL searches through splunkctl and return compact, evidence-backed results without exposing credentials or flooding context.
license: Apache-2.0
allowed-tools:
  - shell
metadata:
  splunk:
    domain: search
    products:
      - splunk-enterprise
      - splunk-cloud-platform
    entities:
      - SPL searches
      - Splunk search jobs
      - search results
      - Splunk targets
    triggers:
      - Splunk Search
      - splunkctl search
      - run a Splunk search
      - query Splunk results
      - incident search evidence
    not-for:
      - production write actions
      - mutating Splunk data
      - secret handling
      - broad raw result dumps
    outcomes:
      - bounded Splunk search execution
      - compact search evidence
      - support-ready search summaries
---

# Splunk Search

> **Source**: [splunk/splunk-agent-skills](https://github.com/splunk/splunk-agent-skills/tree/main/skills/splunk-search)

Use Splunk Search when a user needs current, read-only evidence from Splunk.
Run supported live searches with `splunkctl`, reduce results on the Splunk
server, and return only the counts, states, or small excerpts needed to answer
the request.

## Prerequisites

Live execution requires the separately installed `splunkctl` CLI. Check it
with `command -v splunkctl` before the first live call.

If `splunkctl` is unavailable, stop the live execution path with a clear
dependency message. SPL authoring, explanation, and review may
continue when they do not require live evidence. Offer that non-live help in the
same answer when it can still advance the user's request, and label any query
or conclusion explicitly as unexecuted with no live evidence collected.

Use an already configured target and authentication context. Never install or
configure `splunkctl`, initiate authentication, or ask for passwords, tokens,
cookies, or credential files.

## When to Use

Use this skill for Splunk log investigation, production or staging incident
triage, bounded SPL execution, search-job inspection, and compact search
evidence.

Do not use this skill for changing Splunk configuration, editing knowledge
objects, deleting data, restarting services, creating alerts, modifying
indexes, or handling secrets.

## Workflow Overview

1. Bind the exact target, time window, impact scope, and strongest available
   filters before running a search.
2. Require `splunkctl` on `PATH`. Fail only the live execution path when it is
   absent.
3. Verify the configured target and authenticated identity with
   `splunkctl whoami --output json` or
   `splunkctl server health --output json`.
4. Review the SPL as read-only. Reject commands that write, delete, collect,
   send, script, or otherwise mutate data or configuration.
5. Put explicit `earliest` and `latest` modifiers in the SPL. Prefer `stats`,
   `timechart`, `top`, `fields`, or `table` so Splunk performs the reduction.
6. Use `splunkctl --yes search export` for a fast bounded query. Use a similarly
   confirmed detached search and `splunkctl jobs` only when the search
   genuinely needs longer execution.
7. Parse structured output and return only the evidence needed for the answer.
8. Cancel a detached job when it is no longer needed.
9. When no live command ran, say `not executed; no live evidence collected`
   rather than leaving execution status implicit.

## Commands

- `splunkctl schema --group search --compact` discovers the current search
  surface.
- `splunkctl search --help` and `splunkctl jobs --help` verify exact command
  flags for the installed release.
- `splunkctl whoami --output json` verifies the configured target and identity.
- `splunkctl server health --output json` verifies a bounded server call when
  identity details are unnecessary.
- `splunkctl --yes search export '<read-only SPL with earliest and latest>' --maxout <bounded-count> --output json`
  streams bounded ad hoc results without a persistent job.
- `splunkctl --yes search '<read-only SPL with earliest and latest>' --detach --max-time <seconds> --maxout <bounded-count> --output json`
  submits a managed longer search.
- `splunkctl jobs status <sid> --output json` checks state without fetching
  results.
- `splunkctl jobs show <sid> --output json` retrieves bounded completed results.
- `splunkctl jobs cancel <sid> --output json` cancels an unneeded job.

## Examples

Investigate recent API errors with server-side reduction:

```text
splunkctl --yes search export 'index=app_logs component=api earliest=-30m latest=now | stats count AS total sum(eval(severity="ERROR")) AS error_count by component | sort - error_count' --maxout 20 --output json
```

Inspect a small correlated event sequence only when raw events are necessary:

```text
splunkctl --yes search export 'index=app_logs request_id="abc-123" earliest=-30m latest=now | table _time component severity message | sort 0 _time' --maxout 100 --output json
```
