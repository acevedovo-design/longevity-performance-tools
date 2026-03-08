# YouTube Weekly Performance Report Tool

This repository contains a Python CLI that connects to the YouTube Data API v3, retrieves statistics for all videos on a channel, and exports a weekly CSV report.

## What the tool reports

Each run takes a **full snapshot** of a channel's totals:
- Total views across all channel videos
- Total likes across all channel videos
- Total comments across all channel videos
- Current subscriber count

The script stores snapshots in a local JSON state file and generates weekly report rows by calculating deltas between snapshots.

> Best practice: run this once per week on a schedule (cron/GitHub Actions).

## Requirements

- Python 3.10+
- A YouTube Data API v3 key
- A YouTube channel ID

## Usage

```bash
python3 youtube_weekly_report.py \
  --api-key "YOUR_API_KEY" \
  --channel-id "YOUR_CHANNEL_ID" \
  --output "reports/youtube_weekly_report.csv" \
  --state-file ".youtube_report_state.json"
```

## CSV columns

- `channel_id`
- `channel_title`
- `week_start_utc`
- `week_end_utc`
- `videos_tracked`
- `weekly_views`
- `weekly_likes`
- `weekly_comments`
- `weekly_subscriber_growth`
- `snapshot_captured_at_utc`

## Notes

- The first run creates a baseline snapshot and produces a CSV with headers only.
- Starting from the second run, the CSV includes weekly growth rows based on snapshot-to-snapshot differences.
- Use `--max-snapshots` to control state history retention (default: `104`).
