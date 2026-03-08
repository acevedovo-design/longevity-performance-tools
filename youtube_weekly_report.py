#!/usr/bin/env python3
"""Generate a weekly YouTube channel performance CSV report.

This script uses YouTube Data API v3 to:
1. Fetch all videos from a channel uploads playlist.
2. Sum total views/likes/comments across all channel videos.
3. Track snapshot history in a local state file.
4. Produce a weekly CSV report from snapshot-to-snapshot deltas.

Note: Weekly growth values are only meaningful when this script is run regularly
(e.g. once per week via cron/GitHub Actions).
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen

API_BASE_URL = "https://www.googleapis.com/youtube/v3"
RFC3339_ZULU = "%Y-%m-%dT%H:%M:%SZ"


def to_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def parse_rfc3339(timestamp: str) -> datetime:
    return datetime.strptime(timestamp, RFC3339_ZULU).replace(tzinfo=timezone.utc)


def week_start(date: datetime) -> datetime:
    return (date - timedelta(days=date.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0
    )


def api_get(endpoint: str, params: Dict[str, str], api_key: str) -> Dict[str, Any]:
    query = dict(params)
    query["key"] = api_key
    url = f"{API_BASE_URL}/{endpoint}?{urlencode(query)}"

    try:
        with urlopen(url) as response:  # nosec: B310 (trusted Google API endpoint)
            payload = response.read().decode("utf-8")
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"YouTube API HTTP {exc.code}: {body}") from exc
    except URLError as exc:
        raise RuntimeError(f"YouTube API request failed: {exc}") from exc

    data = json.loads(payload)
    if "error" in data:
        raise RuntimeError(f"YouTube API error: {json.dumps(data['error'])}")
    return data


def get_channel_details(channel_id: str, api_key: str) -> Dict[str, Any]:
    response = api_get(
        "channels",
        {
            "part": "contentDetails,statistics,snippet",
            "id": channel_id,
            "maxResults": "1",
        },
        api_key,
    )
    items = response.get("items", [])
    if not items:
        raise ValueError(f"No channel found for ID: {channel_id}")
    return items[0]


def chunked(values: List[str], size: int) -> Iterable[List[str]]:
    for i in range(0, len(values), size):
        yield values[i : i + size]


def get_all_video_ids(uploads_playlist_id: str, api_key: str) -> List[str]:
    video_ids: List[str] = []
    page_token = None

    while True:
        params = {
            "part": "contentDetails",
            "playlistId": uploads_playlist_id,
            "maxResults": "50",
        }
        if page_token:
            params["pageToken"] = page_token

        response = api_get("playlistItems", params, api_key)
        for item in response.get("items", []):
            video_id = item.get("contentDetails", {}).get("videoId")
            if video_id:
                video_ids.append(video_id)

        page_token = response.get("nextPageToken")
        if not page_token:
            break

    return video_ids


def get_video_details(video_ids: List[str], api_key: str) -> List[Dict[str, Any]]:
    if not video_ids:
        return []

    records: List[Dict[str, Any]] = []
    for chunk in chunked(video_ids, 50):
        response = api_get(
            "videos",
            {
                "part": "statistics",
                "id": ",".join(chunk),
                "maxResults": "50",
            },
            api_key,
        )
        records.extend(response.get("items", []))
    return records


def summarize_video_totals(video_records: List[Dict[str, Any]]) -> Dict[str, int]:
    totals = {"videos": len(video_records), "views": 0, "likes": 0, "comments": 0}
    for record in video_records:
        stats = record.get("statistics", {})
        totals["views"] += to_int(stats.get("viewCount"))
        totals["likes"] += to_int(stats.get("likeCount"))
        totals["comments"] += to_int(stats.get("commentCount"))
    return totals


def load_state(state_path: Path) -> Dict[str, Any]:
    if not state_path.exists():
        return {"snapshots": []}

    with state_path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)

    snapshots = data.get("snapshots", [])
    if not isinstance(snapshots, list):
        snapshots = []
    return {"snapshots": snapshots}


def save_state(state_path: Path, state: Dict[str, Any]) -> None:
    state_path.parent.mkdir(parents=True, exist_ok=True)
    with state_path.open("w", encoding="utf-8") as handle:
        json.dump(state, handle, indent=2)


def append_snapshot(state: Dict[str, Any], snapshot: Dict[str, Any], max_snapshots: int) -> None:
    snapshots = state.setdefault("snapshots", [])
    snapshots.append(snapshot)
    if max_snapshots > 0 and len(snapshots) > max_snapshots:
        del snapshots[:-max_snapshots]


def build_weekly_rows(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    snapshots = state.get("snapshots", [])
    if len(snapshots) < 2:
        return []

    rows: List[Dict[str, Any]] = []
    for prev, curr in zip(snapshots, snapshots[1:]):
        curr_time = parse_rfc3339(curr["captured_at_utc"])
        start = week_start(curr_time)
        end = start + timedelta(days=6)

        row = {
            "week_start_utc": start.date().isoformat(),
            "week_end_utc": end.date().isoformat(),
            "videos_tracked": to_int(curr.get("videos_tracked")),
            "views": to_int(curr.get("total_views")) - to_int(prev.get("total_views")),
            "likes": to_int(curr.get("total_likes")) - to_int(prev.get("total_likes")),
            "comments": to_int(curr.get("total_comments")) - to_int(prev.get("total_comments")),
            "subscriber_growth": to_int(curr.get("subscriber_count")) - to_int(prev.get("subscriber_count")),
            "captured_at_utc": curr["captured_at_utc"],
        }
        rows.append(row)

    return rows


def write_csv_report(
    output_path: Path,
    channel_id: str,
    channel_title: str,
    weekly_rows: List[Dict[str, Any]],
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "channel_id",
                "channel_title",
                "week_start_utc",
                "week_end_utc",
                "videos_tracked",
                "weekly_views",
                "weekly_likes",
                "weekly_comments",
                "weekly_subscriber_growth",
                "snapshot_captured_at_utc",
            ]
        )

        for row in weekly_rows:
            writer.writerow(
                [
                    channel_id,
                    channel_title,
                    row["week_start_utc"],
                    row["week_end_utc"],
                    row["videos_tracked"],
                    row["views"],
                    row["likes"],
                    row["comments"],
                    row["subscriber_growth"],
                    row["captured_at_utc"],
                ]
            )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Retrieve all video statistics for a channel and generate a weekly CSV report "
            "for views, likes, comments, and subscriber growth."
        )
    )
    parser.add_argument("--api-key", required=True, help="YouTube Data API v3 key")
    parser.add_argument("--channel-id", required=True, help="YouTube channel ID")
    parser.add_argument(
        "--output",
        default="youtube_weekly_report.csv",
        help="Output CSV path (default: youtube_weekly_report.csv)",
    )
    parser.add_argument(
        "--state-file",
        default=".youtube_report_state.json",
        help="Path to snapshot state JSON file (default: .youtube_report_state.json)",
    )
    parser.add_argument(
        "--max-snapshots",
        type=int,
        default=104,
        help="Maximum snapshots to keep in state file (default: 104, ~2 years weekly)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    try:
        channel = get_channel_details(args.channel_id, args.api_key)
        uploads_playlist_id = channel["contentDetails"]["relatedPlaylists"]["uploads"]
        channel_title = channel.get("snippet", {}).get("title", "")
        subscriber_count = to_int(channel.get("statistics", {}).get("subscriberCount"))

        video_ids = get_all_video_ids(uploads_playlist_id, args.api_key)
        video_records = get_video_details(video_ids, args.api_key)
        totals = summarize_video_totals(video_records)

        captured_at_utc = datetime.now(timezone.utc).strftime(RFC3339_ZULU)
        snapshot = {
            "captured_at_utc": captured_at_utc,
            "videos_tracked": totals["videos"],
            "total_views": totals["views"],
            "total_likes": totals["likes"],
            "total_comments": totals["comments"],
            "subscriber_count": subscriber_count,
        }

        state_path = Path(args.state_file)
        state = load_state(state_path)
        append_snapshot(state, snapshot, args.max_snapshots)
        save_state(state_path, state)

        weekly_rows = build_weekly_rows(state)
        write_csv_report(Path(args.output), args.channel_id, channel_title, weekly_rows)

    except Exception as exc:  # broad exception to provide clean CLI errors
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(f"Saved snapshot to: {args.state_file}")
    print(f"Report saved to: {args.output}")
    if not weekly_rows:
        print("Report currently has no data rows. Run the script again after another period (e.g. next week).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
