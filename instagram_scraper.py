import instaloader
import json
import os
from datetime import datetime
from collections import Counter
import time
import requests

# ─────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────
YOUR_USERNAME   = "shrey_.070"
YOUR_PASSWORD   = "saxena.home"
TARGET_USERNAME = "sharma091_123"

DATA_DIR   = "data"
OUTPUT_DIR = os.path.join(DATA_DIR, f"instagram_data_{TARGET_USERNAME}")
os.makedirs(OUTPUT_DIR, exist_ok=True)

# ─────────────────────────────────────────
# SESSION HANDLING
# ─────────────────────────────────────────
L = instaloader.Instaloader()
L.context.user_agent = "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1"

def login_or_load_session(loader, username, password, force_login=False):
    session_file = f"session-{username}"
    if force_login and os.path.exists(session_file):
        os.remove(session_file)
        print(f"[*] Session expired. Removed {session_file}")

    try:
        if not os.path.exists(session_file): raise FileNotFoundError
        loader.load_session_from_file(username, filename=session_file)
        print(f"[✓] Session loaded.")
    except:
        print(f"[*] Attempting login as {username}...")
        try:
            loader.login(username, password)
            loader.save_session_to_file(session_file)
            print("[✓] Login successful!")
            # Re-apply custom headers after login
            loader.context._session.headers.update({
                "X-IG-App-ID": "936619743392459",
                "X-Requested-With": "XMLHttpRequest"
            })
            time.sleep(2) # Give it a moment
        except Exception as e:
            print(f"[!] Login failed: {e}. Attempting to continue as guest...")

login_or_load_session(L, YOUR_USERNAME, YOUR_PASSWORD)

# ─────────────────────────────────────────
# API HELPERS
# ─────────────────────────────────────────
def api_request(loader, url, retries=2, use_session=True):
    # Common App IDs used by Instagram web
    APP_IDS = ["936619743392459", "1217981644879628", "1107562852655381"]
    
    headers = {
        "User-Agent": loader.context.user_agent,
        "X-Requested-With": "XMLHttpRequest"
    }
    
    for app_id in APP_IDS:
        headers["X-IG-App-ID"] = app_id
        
        for attempt in range(retries + 1):
            if use_session:
                resp = loader.context._session.get(url, headers=headers)
            else:
                resp = requests.get(url, headers=headers)
                
            if resp.status_code == 200:
                return resp.json()
            elif resp.status_code == 429:
                wait = (attempt + 1) * 5
                print(f"\n[!] Rate limited (429) for App ID {app_id}. Retrying in {wait}s...")
                time.sleep(wait)
            elif resp.status_code in [401, 403]:
                if use_session:
                    return api_request(loader, url, retries=retries, use_session=False)
                break
            else:
                break
            
    return None

def api_post_request(loader, url, data, retries=2):
    APP_IDS = ["936619743392459", "1217981644879628", "1107562852655381"]

    headers = {
        "User-Agent": loader.context.user_agent,
        "X-Requested-With": "XMLHttpRequest",
    }

    for app_id in APP_IDS:
        headers["X-IG-App-ID"] = app_id

        for attempt in range(retries + 1):
            resp = loader.context._session.post(url, headers=headers, data=data)
            if resp.status_code == 200:
                return resp.json()
            if resp.status_code == 429:
                wait = (attempt + 1) * 5
                print(f"\n[!] Rate limited (429) for App ID {app_id}. Retrying in {wait}s...")
                time.sleep(wait)
            else:
                break

    return None

def extract_song(item):
    """Extract licensed or original audio metadata from a feed/reel item."""

    def from_asset_info(asset):
        if not asset or not isinstance(asset, dict):
            return None

        title = asset.get("title") or asset.get("song_name")
        artist = asset.get("display_artist") or asset.get("artist_name") or asset.get("subtitle")
        if not title and not artist:
            return None

        return {
            "title": title or "Unknown",
            "artist": artist or "Unknown",
            "audio_cluster_id": asset.get("audio_cluster_id") or asset.get("id"),
            "is_original_audio": False,
        }

    clips = item.get("clips_metadata") or {}
    if not isinstance(clips, dict):
        clips = {}

    music_info = clips.get("music_info") or {}
    if isinstance(music_info, dict):
        song = from_asset_info(music_info.get("music_asset_info")) or from_asset_info(music_info)
        if song:
            return song

    song = from_asset_info(item.get("music_asset_info"))
    if song:
        return song

    for slide in item.get("carousel_media") or []:
        if isinstance(slide, dict):
            slide_song = extract_song(slide)
            if slide_song:
                return slide_song

    original = clips.get("original_sound_info") or {}
    if isinstance(original, dict):
        title = original.get("original_audio_title")
        artist = original.get("ig_artist") or {}
        artist_name = artist.get("username") if isinstance(artist, dict) else None
        if title and title != "Original audio":
            return {
                "title": title,
                "artist": artist_name or "Unknown",
                "audio_cluster_id": original.get("audio_asset_id") or original.get("audio_cluster_id"),
                "is_original_audio": True,
            }
        if artist_name:
            return {
                "title": "Original audio",
                "artist": artist_name,
                "audio_cluster_id": original.get("audio_asset_id") or original.get("audio_cluster_id"),
                "is_original_audio": True,
            }

    return None

def song_display_name(song):
    return f"{song['artist']} - {song['title']}"

def song_count_key(song):
    if song.get("audio_cluster_id"):
        return f"id:{song['audio_cluster_id']}"
    return f"{song['artist'].lower()}|{song['title'].lower()}"

def from_location(loc):
    if not loc or not isinstance(loc, dict):
        return None

    name = loc.get("name") or loc.get("short_name")
    loc_id = loc.get("pk") or loc.get("id") or loc.get("location_id")
    if not name and not loc_id:
        return None

    return {
        "name": name or "Unknown",
        "id": str(loc_id) if loc_id else None,
        "lat": loc.get("lat"),
        "lng": loc.get("lng"),
    }

def extract_locations(item):
    """Extract all unique location tags from a feed/reel/story item."""

    locations = []
    seen_keys = set()

    def add_location(loc):
        info = from_location(loc)
        if not info:
            return
        key = location_count_key(info)
        if key in seen_keys:
            return
        seen_keys.add(key)
        locations.append(info)

    add_location(item.get("location"))
    for slide in item.get("carousel_media") or []:
        if isinstance(slide, dict):
            add_location(slide.get("location"))

    return locations

def location_count_key(location):
    if location.get("id"):
        return f"id:{location['id']}"
    return location["name"].lower()

def record_locations(locations, location_counts, location_examples):
    for location in locations:
        key = location_count_key(location)
        location_counts[key] += 1
        if key not in location_examples:
            location_examples[key] = location

def process_media_item(item, posts_data, all_hashtags, all_mentions,
                       post_types, song_counts, song_examples,
                       location_counts, location_examples, seen_codes):
    code = item.get("code")
    if code and code in seen_codes:
        return
    if code:
        seen_codes.add(code)

    caption_text = item.get("caption", {}).get("text", "") if item.get("caption") else ""

    hashtags = [t.strip("#") for t in caption_text.split() if t.startswith("#")]
    mentions = [t.strip("@") for t in caption_text.split() if t.startswith("@")]
    all_hashtags.extend(hashtags)
    all_mentions.extend(mentions)

    locations = extract_locations(item)
    location_info = locations[0] if locations else None
    record_locations(locations, location_counts, location_examples)

    product_type = item.get("product_type") or ""
    if product_type == "clips" or item.get("media_type") == 2:
        post_type = "reel" if product_type == "clips" else "video"
    else:
        post_type = "photo"
    post_types[post_type] += 1

    song = extract_song(item)
    if song:
        key = song_count_key(song)
        song_counts[key] += 1
        if key not in song_examples:
            song_examples[key] = song

    post_record = {
        "shortcode":      code,
        "url":            f"https://www.instagram.com/p/{code}/" if code else None,
        "type":           post_type,
        "date":           datetime.fromtimestamp(item.get("taken_at")).isoformat() if item.get("taken_at") else None,
        "caption":        caption_text,
        "likes":          item.get("like_count"),
        "comments":       item.get("comment_count"),
        "location":       location_info,
        "hashtags":       hashtags,
        "mentions":       mentions,
        "song":           song,
    }
    posts_data.append(post_record)

def fetch_user_feed(loader, profile_id, max_pages=5):
    items = []
    next_max_id = ""

    for page in range(max_pages):
        print(f"  Fetching feed page {page + 1}...          ", end="\r")
        feed_url = f"https://www.instagram.com/api/v1/feed/user/{profile_id}/"
        if next_max_id:
            feed_url += f"?max_id={next_max_id}"

        feed_json = api_request(loader, feed_url)
        if not feed_json:
            print(f"\n[!] Feed request failed for page {page + 1}.")
            break

        items.extend(feed_json.get("items", []))
        next_max_id = feed_json.get("next_max_id")
        if not next_max_id:
            break
        time.sleep(2)

    return items

def fetch_user_reels(loader, profile_id, max_pages=5):
    items = []
    max_id = None
    reels_url = "https://www.instagram.com/api/v1/clips/user/"

    for page in range(max_pages):
        print(f"  Fetching reels page {page + 1}...         ", end="\r")
        data = {
            "target_user_id": str(profile_id),
            "page_size": "12",
        }
        if max_id:
            data["max_id"] = max_id

        reels_json = api_post_request(loader, reels_url, data)
        if not reels_json:
            print(f"\n[!] Reels request failed for page {page + 1}.")
            break

        page_items = reels_json.get("items") or []
        for entry in page_items:
            media = entry.get("media") if isinstance(entry, dict) else None
            items.append(media if media else entry)

        paging = reels_json.get("paging_info") or {}
        max_id = paging.get("max_id")
        if not max_id and not reels_json.get("more_available"):
            break
        if not page_items:
            break
        time.sleep(2)

    return items

def fetch_user_stories(loader, profile_id):
    items = []
    story_url = f"https://www.instagram.com/api/v1/feed/user/{profile_id}/story/"
    story_json = api_request(loader, story_url)
    if not story_json:
        return items

    reel = story_json.get("reel") or {}
    return reel.get("items") or []

def process_story_item(item, location_counts, location_examples, seen_story_ids):
    story_id = item.get("pk") or item.get("id")
    if story_id and story_id in seen_story_ids:
        return
    if story_id:
        seen_story_ids.add(story_id)

    record_locations(extract_locations(item), location_counts, location_examples)

# ─────────────────────────────────────────
# 1. PROFILE INFO
# ─────────────────────────────────────────
print(f"[*] Fetching profile: {TARGET_USERNAME}...")
profile_url = f"https://www.instagram.com/api/v1/users/web_profile_info/?username={TARGET_USERNAME}"
profile_json = api_request(L, profile_url)

# If 401, retry login once
if not profile_json:
    print("[*] Retrying with fresh login...")
    login_or_load_session(L, YOUR_USERNAME, YOUR_PASSWORD, force_login=True)
    profile_json = api_request(L, profile_url)

if not profile_json:
    print("[!] Could not fetch profile data. Exiting.")
    exit(1)

user_data = profile_json['data']['user']
profile_id = user_data['id']

profile_report = {
    "username":          user_data['username'],
    "full_name":         user_data['full_name'],
    "user_id":           user_data['id'],
    "biography":         user_data['biography'],
    "followers":         user_data['edge_followed_by']['count'],
    "followees":         user_data['edge_follow']['count'],
    "posts_count":       user_data['edge_owner_to_timeline_media']['count'],
    "is_private":        user_data['is_private'],
    "is_verified":       user_data['is_verified'],
    "profile_pic_url":   user_data['profile_pic_url_hd'],
    "scraped_at":        datetime.now().isoformat(),
}

with open(f"{OUTPUT_DIR}/profile.json", "w", encoding="utf-8") as f:
    json.dump(profile_report, f, indent=2, ensure_ascii=False)
print(f"  → Saved profile info")

# ─────────────────────────────────────────
# 2. POSTS + REELS SCRAPING (Full Metadata)
# ─────────────────────────────────────────
print("\n[*] Scraping posts and reels...")
posts_data          = []
all_hashtags        = []
all_mentions        = []
post_types          = Counter()
song_counts         = Counter()
song_examples       = {}
location_counts     = Counter()
location_examples   = {}
seen_codes          = set()
seen_story_ids      = set()

max_pages = 5

feed_items = fetch_user_feed(L, profile_id, max_pages=max_pages)
reel_items = fetch_user_reels(L, profile_id, max_pages=max_pages)
story_items = fetch_user_stories(L, profile_id)

for item in feed_items + reel_items:
    process_media_item(
        item, posts_data, all_hashtags, all_mentions,
        post_types, song_counts, song_examples,
        location_counts, location_examples, seen_codes,
    )

for item in story_items:
    process_story_item(item, location_counts, location_examples, seen_story_ids)

posts_with_songs = [p for p in posts_data if p.get("song")]
posts_with_locations = [p for p in posts_data if p.get("location")]
top_songs = []
top_locations = []
for rank, (key, count) in enumerate(song_counts.most_common(5), start=1):
    song = song_examples[key]
    top_songs.append({
        "rank": rank,
        "title": song["title"],
        "artist": song["artist"],
        "display": song_display_name(song),
        "count": count,
        "is_original_audio": song.get("is_original_audio", False),
    })

for rank, (key, count) in enumerate(location_counts.most_common(5), start=1):
    location = location_examples[key]
    top_locations.append({
        "rank": rank,
        "name": location["name"],
        "id": location["id"],
        "lat": location["lat"],
        "lng": location["lng"],
        "count": count,
    })

print(f"\n  → Scraped {len(posts_data)} posts/reels total")
print(f"  → Found songs on {len(posts_with_songs)} posts/reels")
print(f"  → Found locations on {len(posts_with_locations)} posts/reels")
if story_items:
    print(f"  → Checked {len(story_items)} active stories for locations")

with open(f"{OUTPUT_DIR}/posts.json", "w", encoding="utf-8") as f:
    json.dump(posts_data, f, indent=2, ensure_ascii=False)

with open(f"{OUTPUT_DIR}/posts_with_songs.json", "w", encoding="utf-8") as f:
    json.dump(posts_with_songs, f, indent=2, ensure_ascii=False)

with open(f"{OUTPUT_DIR}/top_songs.json", "w", encoding="utf-8") as f:
    json.dump(top_songs, f, indent=2, ensure_ascii=False)

with open(f"{OUTPUT_DIR}/posts_with_locations.json", "w", encoding="utf-8") as f:
    json.dump(posts_with_locations, f, indent=2, ensure_ascii=False)

with open(f"{OUTPUT_DIR}/top_locations.json", "w", encoding="utf-8") as f:
    json.dump(top_locations, f, indent=2, ensure_ascii=False)

# ─────────────────────────────────────────
# 3. ANALYTICS
# ─────────────────────────────────────────
print("\n[*] Running analytics...")
hashtag_counts = Counter(all_hashtags)
with open(f"{OUTPUT_DIR}/hashtags.json", "w") as f:
    json.dump(hashtag_counts.most_common(), f, indent=2)

mention_counts = Counter(all_mentions)
with open(f"{OUTPUT_DIR}/mentions.json", "w") as f:
    json.dump(mention_counts.most_common(), f, indent=2)

# ─────────────────────────────────────────
# MASTER SUMMARY
# ─────────────────────────────────────────
summary = {
    "target_account":      TARGET_USERNAME,
    "scraped_at":          datetime.now().isoformat(),
    "profile":             profile_report,
    "content_breakdown":   dict(post_types),
    "top_hashtags":        hashtag_counts.most_common(10),
    "top_mentions":        mention_counts.most_common(10),
    "posts_with_songs":      len(posts_with_songs),
    "top_songs":             top_songs,
    "posts_with_locations":  len(posts_with_locations),
    "stories_checked":       len(story_items),
    "top_locations":         top_locations,
    "total_likes":         sum(p["likes"] or 0 for p in posts_data),
    "total_comments":      sum(p["comments"] or 0 for p in posts_data),
    "avg_likes":           round(sum(p["likes"] or 0 for p in posts_data) / max(len(posts_data), 1), 1),
}

with open(f"{OUTPUT_DIR}/SUMMARY.json", "w", encoding="utf-8") as f:
    json.dump(summary, f, indent=2, ensure_ascii=False)

print("\n" + "="*55)
print(f"✅ SCRAPING COMPLETE!")
print(f"   Output folder : {OUTPUT_DIR}/")
print(f"   Posts scraped : {len(posts_data)}")
print(f"   With songs      : {len(posts_with_songs)}")
print(f"   With locations  : {len(posts_with_locations)}")
print(f"   Avg Likes       : {summary['avg_likes']}")
if top_songs:
    print("\n   Top 5 songs:")
    for song in top_songs:
        print(f"     {song['rank']}. {song['display']} ({song['count']}x)")
else:
    print("\n   No songs found in scraped posts/reels.")
if top_locations:
    print("\n   Top 5 locations:")
    for location in top_locations:
        print(f"     {location['rank']}. {location['name']} ({location['count']}x)")
else:
    print("\n   No locations found in scraped posts/reels/stories.")
print("="*55)
 
