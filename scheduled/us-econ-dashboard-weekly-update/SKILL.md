---
name: us-econ-dashboard-weekly-update
description: Weekly refresh of ISM Manufacturing and Services PMI in the US Economic Dashboard — the only two metrics not available via the FRED API automated pull.
---

You are running the weekly refresh of Max's US Economic Health dashboard at C:\Users\Max\OneDrive\Documents\Cowork\Economic\index.html.

GOAL
Update the two ISM PMI metric cards that cannot be pulled from the FRED API: ISM Manufacturing PMI and ISM Services PMI.

THE 2 METRICS
- ISM Manufacturing PMI (`mfg` card)
- ISM Services PMI (`svc` card)

WORKFLOW
1. Read the current index.html to note each card's existing latest reading date — only update if a newer release is out.
2. For each metric, fetch the latest data from the primary source:
   - ISM Manufacturing PMI: ismworld.org (Report On Business — Manufacturing)
   - ISM Services PMI: ismworld.org (Report On Business — Services)
   Find: the latest PMI value, the period it covers, and the release date.
3. Find 1–3 recent news items (within the last ~10 days) relevant to each metric — prefer Reuters, AP, WSJ, Bloomberg, FT, or CNBC.
4. For each card, edit in place:
   a. Update the `badge-value` and `badge-change` (direction arrow + comparison vs. prior reading) if a newer reading is out.
   b. Update the `reading-box` paragraph with the new period, value, brief context, and source/date in parens.
   c. Add or refresh the `news-box` block inside the `card-footer`, immediately AFTER the `reading-box`:

      <div class="news-box">
        <span class="def-tag">Recent News</span>
        <ul>
          <li><strong>Headline (Source, MMM D YYYY):</strong> 1-sentence takeaway. <a href="URL" target="_blank" rel="noopener">link</a></li>
          ... up to 3 items ...
        </ul>
      </div>

   d. If no new release this week, keep badge/reading-box unchanged but still refresh the news-box.
5. Save the file in place (do NOT create a dated copy — this is a live dashboard).

OUTPUT TO MAX
After the edit pass, post a short summary:
- Whether each PMI had a new release (old → new value, period).
- Any sources that were unreachable / data you couldn't verify.

GUARDRAILS
- Never invent or extrapolate numbers. If you can't confirm a value from ismworld.org, leave the previous value and note it.
- Preserve all existing HTML structure, classes, IDs, scripts, and chart JS data. Only edit badge text, reading-box, and news-box content.
- News items must be from the last ~10 days. Skip older items rather than padding.
- Keep each news bullet to one sentence. No emoji. No editorializing.

Today's date is provided by the environment — use it to judge "recent."
