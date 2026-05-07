name: Update Economic Data

on:
  schedule:
    - cron: '0 21 * * 1-5'
  workflow_dispatch:

env:
  FORCE_JAVASCRIPT_ACTIONS_TO_NODE24: true

jobs:
  fetch:
    runs-on: ubuntu-latest
    permissions:
      contents: write
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'

      - name: Fetch FRED + Alpha Vantage data
        env:
          FRED_API_KEY: ${{ secrets.FRED_API_KEY }}
          AV_API_KEY:   ${{ secrets.AV_API_KEY }}
        run: python3 fetch_data.py

      - uses: stefanzweifel/git-auto-commit-action@v5
        with:
          commit_message: "Data update ${{ github.run_id }}"
          file_pattern: data.json
