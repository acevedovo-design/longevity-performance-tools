import requests
import csv
import os
from datetime import datetime

API_KEY = os.environ["API_KEY"]
CHANNEL_ID = os.environ["CHANNEL_ID"]

BASE_URL = "https://www.googleapis.com/youtube/v3"

def get_uploads_playlist():
    url = f"{BASE_URL}/channels"
    params = {
        "part": "contentDetails",
        "id": CHANNEL_ID,
        "key": API_KEY
    }
    r = requests.get(url, params=params).json()
    return r["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]

def get_all_videos(playlist_id):
    videos = []
    next_page = None

    while True:
        url = f"{BASE_URL}/playlistItems"
        params = {
            "part": "snippet",
            "playlistId": playlist_id,
            "maxResults": 50,
            "pageToken": next_page,
            "key": API_KEY
        }

        r = requests.get(url, params=params).json()

        for item in r["items"]:
            videos.append({
                "video_id": item["snippet"]["resourceId"]["videoId"],
                "title": item["snippet"]["title"],
                "published_at": item["snippet"]["publishedAt"]
            })

        next_page = r.get("nextPageToken")
        if not next_page:
            break

    return videos

def get_video_stats(video_ids):
    stats = []

    for i in range(0, len(video_ids), 50):
        chunk = video_ids[i:i+50]

        url = f"{BASE_URL}/videos"
        params = {
            "part": "statistics",
            "id": ",".join(chunk),
            "key": API_KEY
        }

        r = requests.get(url, params=params).json()

        for item in r["items"]:
            s = item["statistics"]

            stats.append({
                "video_id": item["id"],
                "views": s.get("viewCount", 0),
                "likes": s.get("likeCount", 0),
                "comments": s.get("commentCount", 0)
            })

    return stats

def main():

    playlist = get_uploads_playlist()
    videos = get_all_videos(playlist)

    ids = [v["video_id"] for v in videos]
    stats = get_video_stats(ids)

    stats_lookup = {s["video_id"]: s for s in stats}

    os.makedirs("reports", exist_ok=True)

    output_file = "reports/youtube_video_report.csv"

    with open(output_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)

        writer.writerow([
            "snapshot_date",
            "video_id",
            "title",
            "published_at",
            "total_views",
            "total_likes",
            "total_comments"
        ])

        today = datetime.utcnow().isoformat()

        for v in videos:
            s = stats_lookup.get(v["video_id"], {})

            writer.writerow([
                today,
                v["video_id"],
                v["title"],
                v["published_at"],
                s.get("views", 0),
                s.get("likes", 0),
                s.get("comments", 0)
            ])

    print("Video report saved to reports/youtube_video_report.csv")

if __name__ == "__main__":
    main()
  
