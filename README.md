# Instagram Scraper

A Python script that collects public profile and post metadata from Instagram for a target account. It uses [Instaloader](https://instaloader.github.io/) for authentication and session management, and calls Instagram's **unofficial internal web API** (the same endpoints the instagram.com website uses in the browser).

> **Note:** This is not the official [Instagram Graph API](https://developers.facebook.com/docs/instagram-api/). There is no API key or Meta developer app involved. Requests mimic a logged-in web session.

---

## What data does it fetch?

### 1. Profile (`profile.json`)

| Field | Description |
|-------|-------------|
| `username` | Instagram handle |
| `full_name` | Display name |
| `user_id` | Numeric Instagram user ID |
| `biography` | Bio text |
| `followers` | Follower count |
| `followees` | Following count |
| `posts_count` | Total posts on profile |
| `is_private` | Whether the account is private |
| `is_verified` | Blue check status |
| `profile_pic_url` | HD profile picture URL |
| `scraped_at` | Timestamp of the scrape |

### 2. Posts & reels (`posts.json`)

Up to **5 pages** each from the main feed and the reels tab (~60 items per source). For each item:

| Field | Description |
|-------|-------------|
| `shortcode` | Post ID used in URLs |
| `url` | Full post link |
| `type` | `"photo"`, `"video"`, or `"reel"` |
| `date` | When the post was published |
| `caption` | Full caption text |
| `likes` | Like count |
| `comments` | Comment count |
| `location` | Name, ID, lat/lng (if tagged) |
| `hashtags` | Hashtags parsed from caption |
| `mentions` | `@` mentions parsed from caption |
| `song` | Music metadata if present (title, artist, original vs licensed) |

**It does not download** images, videos, stories, followers lists, or DMs.

### 3. Songs

- `posts_with_songs.json` — only posts/reels that have audio metadata
- `top_songs.json` — **top 5 most-used songs** (ranked by frequency)
- Song data comes from Instagram's `clips_metadata.music_info` (licensed tracks) and `original_sound_info` (original audio)

The script prints the top 5 songs at the end of the run and includes them in `SUMMARY.json`.

### 4. Locations

- `posts_with_locations.json` — only posts/reels that have a location tag
- `top_locations.json` — **top 5 most-tagged locations** (ranked by frequency)
- Location data comes from Instagram's `location` field on posts, reels, carousel slides, and active stories

The script prints the top 5 locations at the end of the run and includes them in `SUMMARY.json`.

### 5. Analytics

- `hashtags.json` — hashtag frequency across scraped posts
- `mentions.json` — `@` mention frequency
- `SUMMARY.json` — rollup: profile, content breakdown, top songs, top locations, top hashtags/mentions, total/average likes and comments

All output is written to `data/instagram_data_<target_username>/`.

### 6. Insights (`insights.json`)

After scraping, run the insights analyzer to infer interests, hobbies, travel style, music taste, and more from the raw data:

```bash
python instagram_insights.py <target_username>
```

| Method | What it infers | Reliability |
|--------|----------------|-------------|
| **Rule-based** | College, occupation hints, hobbies, interests, favorite places, travel style, music taste, languages, posting times, hashtags, social mentions | High–Medium |
| **Ollama (llama3.2)** | Personality, fashion style, favorite food, daily routine, favorite brands, events, humor, overall summary | Low–Medium |

Options:

```bash
python instagram_insights.py sharma091_123          # default: uses local Ollama
python instagram_insights.py sharma091_123 --no-ollama  # rule-based only (faster)
python instagram_insights.py sharma091_123 --model llama3.2
```

Requires [Ollama](https://ollama.com/) running locally with `llama3.2` pulled. If Ollama is unavailable, the script still produces rule-based insights.

**Input files used:** `profile.json`, `posts.json`, `stories.json`, `highlights.json`, `hashtags.json`, `mentions.json`, `top_songs.json`, `top_locations.json`, `SUMMARY.json`, or consolidated `raw_bundle.json`.

**Output:** `insights.json` with reliability scores and evidence for each inference.

---

## How does it talk to Instagram?

The script uses two layers:

1. **Instaloader** — logs in with your Instagram credentials and maintains an authenticated HTTP session (cookies + headers).
2. **Direct API calls** — `GET` requests to Instagram's internal endpoints:

   ```
   GET  /api/v1/users/web_profile_info/?username=<target>
   GET  /api/v1/feed/user/<user_id>/?max_id=<cursor>
   POST /api/v1/clips/user/   (reels tab — where most music metadata lives)
   GET  /api/v1/feed/user/<user_id>/story/   (active stories — location tags if present)
   ```

   Requests include browser-like headers (`User-Agent`, `X-IG-App-ID`, `X-Requested-With`). On rate limits (429) it retries with backoff; on auth errors (401/403) it may retry without the session or force a fresh login.

There is no separate REST API server in this project — the script *is* the client.

---

## What is the session file?

Files named `session-<username>` (e.g. `session-thebaldengineer77`) store your **saved login session** after a successful Instagram login. Instaloader serializes cookies and session state so the next run can skip logging in.

**Flow:**

1. If `session-<username>` exists → load it and reuse the session.
2. If missing or invalid → log in with `YOUR_USERNAME` / `YOUR_PASSWORD`, then save a new session file.
3. If the profile API returns no data → delete the stale session, log in again, and retry.

The session file is sensitive (equivalent to being logged in). Treat it like a password: do not commit it to git, share it, or upload it anywhere.

---

## How to run

### Prerequisites

- Python 3.8+
- An Instagram account (used only for authentication; the script scrapes a *different* target account)

### Install dependencies

```bash
pip install instaloader requests
```

### Configure the script

Edit the configuration block at the top of `instagram_scraper.py`:

```python
YOUR_USERNAME   = "your_instagram_username"
YOUR_PASSWORD   = "your_instagram_password"
TARGET_USERNAME = "account_to_scrape"
```

Change `TARGET_USERNAME` to whichever public profile you want to analyze.

### Run

```bash
python instagram_scraper.py
```

### Do you need to do anything with the session file?

| Situation | What to do |
|-----------|------------|
| **First run** | Nothing. The script logs in and creates `session-<your_username>` automatically. |
| **Later runs** | Nothing. It reuses the existing session file if still valid. |
| **Login fails / session expired** | Delete `session-<your_username>` and run again, or let the script remove it when it detects expiry (it does this on retry). |
| **You change `YOUR_USERNAME`** | A new session file will be created for the new username. Old session files can be deleted. |
| **Sharing the repo** | Do **not** include session files. Add `session-*` to `.gitignore`. |

You never need to manually edit the session file — it is binary/session data managed entirely by Instaloader.

---

## Limitations

- **Private accounts** — only works if your logged-in account follows the private target (same as viewing in the app).
- **Rate limits** — Instagram may throttle or block requests; the script retries on 429 but heavy use can trigger temporary bans.
- **Post cap** — only the first ~5 feed pages are scraped (`max_pages = 5` in code).
- **Terms of service** — scraping may violate Instagram's ToS. Use responsibly and for personal/educational purposes only.

---

## Project structure

```
instagram-scraper/
├── instagram_scraper.py    # Scrape profile, posts, reels, stories
├── instagram_insights.py   # Analyze scraped data (rule-based + Ollama)
├── session-<username>      # Auto-generated; keep local, do not commit
└── data/                   # Scraped user data (gitignored)
    └── instagram_data_<target>/
        ├── profile.json
        ├── posts.json
        ├── stories.json
        ├── highlights.json
        ├── raw_bundle.json
        ├── posts_with_songs.json
        ├── top_songs.json
        ├── posts_with_locations.json
        ├── top_locations.json
        ├── hashtags.json
        ├── mentions.json
        ├── SUMMARY.json
        └── insights.json
```

---

## Security recommendations

- Avoid hardcoding passwords in source code. Prefer environment variables:

  ```python
  YOUR_USERNAME = os.environ.get("IG_USERNAME")
  YOUR_PASSWORD = os.environ.get("IG_PASSWORD")
  ```

- Add to `.gitignore`:

  ```
  data/
  session-*
  ```
