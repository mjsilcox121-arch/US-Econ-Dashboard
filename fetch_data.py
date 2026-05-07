name: Update Economic Data

on:
  schedule:
    - cron: '0 21 * * 1-5'   # Mon–Fri at 4pm ET (after market close)
  workflow_dispatch:

env:
  FORCE_JAVASCRIPT_ACTIONS_TO_NODE24: true   # clears the Node 20 warning

jobs:
  fetch:
    runs-on: ubuntu-latest
    permissions:
      contents: write
    steps:
      - uses: actions/checkout@v4
        with:
          token: ${{ secrets.GITHUB_TOKEN }}   # ← gives the workflow push access

      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'

      - name: Fetch FRED + Alpha Vantage data
        env:
          FRED_API_KEY: ${{ secrets.FRED_API_KEY }}
          AV_API_KEY:   ${{ secrets.AV_API_KEY }}
        run: python3 fetch_data.py

      - name: Commit and push data.json
        run: |
          git config user.name  "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          git add data.json
          git diff --staged --quiet && echo "No changes" || \
            (git commit -m "Data update $(date -u +%Y-%m-%d)" && git push)
