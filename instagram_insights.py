#!/usr/bin/env python3
"""
Instagram Insights Analyzer

Reads scraped profile/post data and infers interests, hobbies, travel style,
music taste, social circle, and more using rule-based extraction plus optional
local Ollama (llama3.2) inference.
"""

import argparse
import json
import os
import re
from collections import Counter
from datetime import datetime

import requests

DATA_DIR = "data"
DEFAULT_MODEL = "llama3.2"
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")

HOBBY_KEYWORDS = {
    "fitness": ["gym", "workout", "fitness", "health", "gym life", "exercise", "training"],
    "travel": ["travel", "trip", "vacation", "explore", "wanderlust", "journey", "darshan", "jyotirlinga"],
    "photography": ["photoshoot", "photography", "camera", "portrait", "click"],
    "spirituality": ["temple", "shiva", "bholenath", "mahakal", "adiyogi", "jyotirlinga", "darshan", "spiritual"],
    "college_life": ["college", "collegelife", "campus", "university", "semester", "finalyear"],
    "food": ["food", "restaurant", "cafe", "coffee", "dinner", "lunch", "biryani", "pizza"],
    "gaming": ["gaming", "gamer", "pubg", "valorant", "esports"],
    "music": ["music", "concert", "festival", "coke studio", "song"],
    "pets": ["dog", "cat", "puppy", "kitten", "pet"],
    "cars": ["car", "bike", "motorcycle", "supercar", "automobile"],
    "reading": ["book", "reading", "novel", "library"],
}

INTEREST_THEMES = {
    "travel": ["travel", "beach", "mountain", "explore", "rameshwaram", "dhanushkodi", "bengaluru", "bangalore"],
    "fitness": ["gym", "fitness", "health", "workout", "stressrelief"],
    "spirituality": ["temple", "shiva", "bholenath", "adiyogi", "jyotirlinga", "mahakal"],
    "college": ["college", "collegelife", "iiit", "campus", "finalyear"],
    "photography": ["photoshoot", "photography", "flowers", "viral"],
    "village_life": ["village", "villagelife", "gao", "rural"],
}

TRAVEL_SIGNALS = {
    "beach": ["beach", "ocean", "sea", "coast", "dhanushkodi", "bayofbengal"],
    "mountains": ["mountain", "hill", "trek", "himalaya"],
    "pilgrimage": ["temple", "jyotirlinga", "darshan", "rameshwaram", "shiva", "mahakal"],
    "domestic": ["india", "up", "karnataka", "jabalpur", "ghaziabad", "bangalore", "bengaluru"],
    "urban": ["mall", "city", "bangalore", "bengaluru", "whitefield", "mg road"],
}


def load_json(path, default=None):
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_scraped_data(username):
    output_dir = os.path.join(DATA_DIR, f"instagram_data_{username}")
    if not os.path.isdir(output_dir):
        raise FileNotFoundError(f"No scraped data found at {output_dir}. Run instagram_scraper.py first.")

    bundle_path = os.path.join(output_dir, "raw_bundle.json")
    if os.path.exists(bundle_path):
        return output_dir, load_json(bundle_path)

    profile = load_json(os.path.join(output_dir, "profile.json"), {})
    posts = load_json(os.path.join(output_dir, "posts.json"), [])
    summary = load_json(os.path.join(output_dir, "SUMMARY.json"), {})

    return output_dir, {
        "target_account": username,
        "scraped_at": summary.get("scraped_at"),
        "profile": profile,
        "posts": posts,
        "stories": load_json(os.path.join(output_dir, "stories.json"), []),
        "highlights": load_json(os.path.join(output_dir, "highlights.json"), profile.get("highlights", [])),
        "hashtags": load_json(os.path.join(output_dir, "hashtags.json"), []),
        "mentions": load_json(os.path.join(output_dir, "mentions.json"), []),
        "top_songs": load_json(os.path.join(output_dir, "top_songs.json"), []),
        "top_locations": load_json(os.path.join(output_dir, "top_locations.json"), []),
        "posting_patterns": summary.get("posting_patterns", {}),
        "content_breakdown": summary.get("content_breakdown", {}),
        "engagement": {
            "total_likes": summary.get("total_likes", 0),
            "total_comments": summary.get("total_comments", 0),
            "avg_likes": summary.get("avg_likes", 0),
        },
    }


def normalize_text(*parts):
    return " ".join(p for p in parts if p).lower()


def insight(value, reliability, source, evidence=None):
    entry = {
        "value": value,
        "reliability": reliability,
        "source": source,
    }
    if evidence:
        entry["evidence"] = evidence
    return entry


def match_keywords(text, keyword_map):
    hits = []
    for label, keywords in keyword_map.items():
        score = sum(1 for kw in keywords if kw in text)
        if score:
            hits.append((label, score))
    hits.sort(key=lambda x: x[1], reverse=True)
    return hits


def extract_profile_facts(profile):
    bio = profile.get("biography") or ""
    facts = {}

    facts["full_name"] = insight(profile.get("full_name"), "high", "profile")
    facts["username"] = insight(profile.get("username"), "high", "profile")
    facts["bio"] = insight(bio, "high", "profile")
    facts["followers"] = insight(profile.get("followers"), "high", "profile")
    facts["following"] = insight(profile.get("followees"), "high", "profile")
    facts["posts_count"] = insight(profile.get("posts_count"), "high", "profile")
    facts["is_verified"] = insight(profile.get("is_verified", False), "high", "profile")

    if profile.get("external_url"):
        facts["website"] = insight(profile["external_url"], "high", "profile")
    if profile.get("pronouns"):
        facts["pronouns"] = insight(profile["pronouns"], "high", "profile")
    if profile.get("category"):
        facts["category"] = insight(profile["category"], "high", "profile")

    college_patterns = [
        r"\bIIIT\s*(?:DM\s*)?Jabalpur\b",
        r"\bIIT\s+[A-Za-z]+\b",
        r"\bNIT\s+[A-Za-z]+\b",
        r"\b[A-Za-z\s]+University\b",
        r"\b[A-Za-z\s]+College\b",
        r"\b[A-Za-z\s]+Institute\b",
    ]
    for pattern in college_patterns:
        college_match = re.search(pattern, bio, re.IGNORECASE)
        if college_match:
            facts["college"] = insight(college_match.group(0).strip(), "high", "bio")
            break

    year_match = re.search(r"\(?\s*(\d{4})\s*[-–]\s*(\d{2,4})\s*\)?", bio)
    if year_match:
        facts["education_years"] = insight(
            f"{year_match.group(1)}-{year_match.group(2)}", "high", "bio"
        )

    if re.search(r"engineer", bio, re.IGNORECASE):
        facts["occupation_hint"] = insight("Engineering / Tech", "high", "bio")

    city_match = re.search(
        r"(Bengaluru|Bangalore|Delhi|Mumbai|Jabalpur|Ghaziabad|Muradnagar|"
        r"Karnataka|Uttar Pradesh|UP)",
        bio,
        re.IGNORECASE,
    )
    if city_match:
        facts["city_hint"] = insight(city_match.group(0).strip(), "medium", "bio")

    return facts


def extract_hobbies_and_interests(data):
    posts = data.get("posts", [])
    highlights = data.get("highlights", [])
    hashtags = [h[0] for h in data.get("hashtags", []) if h and h[0]]

    corpus = normalize_text(
        data.get("profile", {}).get("biography", ""),
        " ".join(p.get("caption", "") for p in posts),
        " ".join(h.get("title", "") for h in highlights),
        " ".join(f"#{tag}" for tag in hashtags),
    )

    hobby_hits = match_keywords(corpus, HOBBY_KEYWORDS)
    interest_hits = match_keywords(corpus, INTEREST_THEMES)

    hobbies = [
        insight(name.replace("_", " ").title(), "high", "posts_and_hashtags", {"score": score})
        for name, score in hobby_hits[:8]
    ]
    interests = [
        insight(name.replace("_", " ").title(), "high", "content_themes", {"score": score})
        for name, score in interest_hits[:8]
    ]

    highlight_topics = [
        insight(h.get("title"), "high", "highlights", {"item_count": h.get("item_count")})
        for h in highlights if h.get("title")
    ]

    return {
        "hobbies": hobbies,
        "interests": interests,
        "highlight_topics": highlight_topics,
    }


def extract_places_and_travel(data):
    top_locations = data.get("top_locations", [])
    posts = data.get("posts", [])

    favorite_places = [
        insight(
            loc["name"],
            "high",
            "location_tags",
            {"count": loc["count"], "lat": loc.get("lat"), "lng": loc.get("lng")},
        )
        for loc in top_locations
    ]

    location_text = normalize_text(
        *(loc["name"] for loc in top_locations),
        *(p.get("caption", "") for p in posts if p.get("location")),
    )
    travel_hits = match_keywords(location_text, TRAVEL_SIGNALS)

    travel_preferences = [
        insight(name.replace("_", " ").title(), "high", "locations_and_captions", {"score": score})
        for name, score in travel_hits[:6]
    ]

    return {
        "favorite_places": favorite_places,
        "travel_preferences": travel_preferences,
    }


def extract_music_taste(data):
    top_songs = data.get("top_songs", [])
    songs = [
        insight(
            song["display"],
            "medium",
            "reels_and_stories",
            {
                "count": song["count"],
                "is_original_audio": song.get("is_original_audio", False),
            },
        )
        for song in top_songs
    ]
    licensed = [s for s in top_songs if not s.get("is_original_audio")]
    taste = None
    if licensed:
        artists = list(dict.fromkeys(s["artist"] for s in licensed))
        taste = insight(
            f"Enjoys {', '.join(artists[:3])}",
            "medium",
            "licensed_audio_in_reels",
            {"tracks": [s["display"] for s in licensed[:5]]},
        )
    return {"top_songs": songs, "music_taste_summary": taste}


def extract_social_circle(data):
    mentions = data.get("mentions", [])
    if not mentions:
        return {"close_friends": [], "frequent_mentions": []}

    frequent = [
        insight(username, "high", "caption_mentions", {"count": count})
        for username, count in mentions[:10]
        if username
    ]
    close_friends = [m for m in frequent if m["evidence"]["count"] >= 2]
    return {
        "frequent_mentions": frequent,
        "close_friends": close_friends,
    }


def extract_languages(data):
    posts = data.get("posts", [])
    bio = data.get("profile", {}).get("biography", "")
    text = bio + " " + " ".join(p.get("caption", "") for p in posts)

    languages = []
    if re.search(r"[\u0900-\u097F]", text):
        languages.append(insight("Hindi (Devanagari script)", "high", "captions_and_bio"))
    if re.search(r"[A-Za-z]", text):
        languages.append(insight("English", "high", "captions_and_bio"))
    if re.search(r"[\u0B80-\u0BFF]", text):
        languages.append(insight("Tamil", "high", "captions_and_bio"))

    return {"languages": languages}


def extract_posting_behavior(data):
    patterns = data.get("posting_patterns", {})
    posts = data.get("posts", [])
    content = data.get("content_breakdown", {})
    engagement = data.get("engagement", {})

    behavior = {}
    if patterns.get("peak_hour") is not None:
        hour = patterns["peak_hour"]
        period = "morning" if 5 <= hour < 12 else "afternoon" if 12 <= hour < 17 else "evening" if 17 <= hour < 21 else "night"
        behavior["peak_posting_time"] = insight(
            f"{period} (around {hour}:00)",
            "medium",
            "post_timestamps",
            {"by_hour": patterns.get("by_hour"), "by_day": patterns.get("by_day")},
        )

    if content:
        dominant = max(content, key=content.get)
        behavior["preferred_content"] = insight(
            dominant,
            "high",
            "content_breakdown",
            content,
        )

    if engagement:
        behavior["engagement"] = insight(
            f"Avg {engagement.get('avg_likes', 0)} likes per post",
            "high",
            "post_metrics",
            engagement,
        )

    reels = [p for p in posts if p.get("type") == "reel"]
    if reels:
        behavior["reel_activity"] = insight(
            f"{len(reels)} reels in scraped sample",
            "high",
            "posts",
        )

    return behavior


def extract_content_signals(data):
    posts = data.get("posts", [])
    hashtags = Counter(h[0].lower() for h in data.get("hashtags", []) if h and h[0])

    fitness_posts = sum(
        1 for p in posts
        if any(kw in (p.get("caption") or "").lower() for kw in HOBBY_KEYWORDS["fitness"])
    )
    travel_posts = sum(
        1 for p in posts
        if p.get("location") or any(kw in (p.get("caption") or "").lower() for kw in HOBBY_KEYWORDS["travel"])
    )
    spiritual_posts = sum(
        1 for p in posts
        if any(kw in (p.get("caption") or "").lower() for kw in HOBBY_KEYWORDS["spirituality"])
    )

    return {
        "top_hashtags": [
            insight(tag, "high", "hashtags", {"count": count})
            for tag, count in hashtags.most_common(15)
        ],
        "content_mix": {
            "fitness_posts": insight(fitness_posts, "high", "captions"),
            "travel_posts": insight(travel_posts, "high", "captions_and_locations"),
            "spiritual_posts": insight(spiritual_posts, "high", "captions"),
        },
    }


def build_llm_context(data, rule_insights):
    profile = data.get("profile", {})
    posts = data.get("posts", [])

    sample_captions = [
        {
            "type": p.get("type"),
            "date": p.get("date"),
            "caption": (p.get("caption") or "")[:400],
            "location": (p.get("location") or {}).get("name"),
            "song": (p.get("song") or {}).get("title"),
            "hashtags": p.get("hashtags", [])[:8],
        }
        for p in posts[:20]
    ]

    return {
        "profile": {
            "username": profile.get("username"),
            "full_name": profile.get("full_name"),
            "bio": profile.get("biography"),
            "external_url": profile.get("external_url"),
            "highlights": [h.get("title") for h in data.get("highlights", [])],
        },
        "rule_based_summary": {
            "hobbies": [h["value"] for h in rule_insights["hobbies_and_interests"]["hobbies"][:6]],
            "interests": [i["value"] for i in rule_insights["hobbies_and_interests"]["interests"][:6]],
            "favorite_places": [p["value"] for p in rule_insights["places_and_travel"]["favorite_places"][:5]],
            "travel_preferences": [t["value"] for t in rule_insights["places_and_travel"]["travel_preferences"]],
            "top_songs": [s["value"] for s in rule_insights["music_taste"]["top_songs"][:5]],
            "languages": [l["value"] for l in rule_insights["languages"]["languages"]],
            "profile_facts": {k: v["value"] for k, v in rule_insights["profile_facts"].items()},
        },
        "sample_posts": sample_captions,
        "posting_patterns": data.get("posting_patterns", {}),
        "engagement": data.get("engagement", {}),
    }


def call_ollama(context, model=DEFAULT_MODEL):
    system_prompt = (
        "You are a social media analyst. Infer personality and lifestyle signals ONLY "
        "from the provided public Instagram metadata. Be conservative, cite evidence, "
        "and assign reliability: high, medium, or low. Return valid JSON only."
    )
    user_prompt = f"""Analyze this Instagram profile data and infer additional insights.

Return JSON with this exact structure:
{{
  "personality": {{"value": "...", "reliability": "low|medium", "evidence": ["..."]}},
  "fashion_style": {{"value": "...", "reliability": "low|medium|high", "evidence": ["..."]}},
  "favorite_food": {{"value": "...", "reliability": "low|medium", "evidence": ["..."]}},
  "daily_routine": {{"value": "...", "reliability": "low|medium", "evidence": ["..."]}},
  "relationship_status": {{"value": "...", "reliability": "low|medium", "evidence": ["..."]}},
  "favorite_brands": {{"value": ["..."], "reliability": "low|medium", "evidence": ["..."]}},
  "events_and_occasions": {{"value": ["..."], "reliability": "medium|high", "evidence": ["..."]}},
  "communities": {{"value": ["..."], "reliability": "medium", "evidence": ["..."]}},
  "sense_of_humor": {{"value": "...", "reliability": "low|medium", "evidence": ["..."]}},
  "overall_summary": {{"value": "2-3 sentence profile summary", "reliability": "medium", "evidence": ["..."]}}
}}

DATA:
{json.dumps(context, ensure_ascii=False, indent=2)}
"""

    response = requests.post(
        f"{OLLAMA_URL}/api/chat",
        json={
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "stream": False,
            "format": "json",
        },
        timeout=180,
    )
    response.raise_for_status()
    content = response.json()["message"]["content"]
    return json.loads(content)


def extract_rule_based_insights(data):
    profile_facts = extract_profile_facts(data.get("profile", {}))
    hobbies_and_interests = extract_hobbies_and_interests(data)
    places_and_travel = extract_places_and_travel(data)
    music_taste = extract_music_taste(data)
    social_circle = extract_social_circle(data)
    languages = extract_languages(data)
    posting_behavior = extract_posting_behavior(data)
    content_signals = extract_content_signals(data)

    return {
        "profile_facts": profile_facts,
        "hobbies_and_interests": hobbies_and_interests,
        "places_and_travel": places_and_travel,
        "music_taste": music_taste,
        "social_circle": social_circle,
        "languages": languages,
        "posting_behavior": posting_behavior,
        "content_signals": content_signals,
    }


def build_insights_report(username, data, rule_insights, ai_insights=None, model=None):
    data_sources = {
        "posts": len(data.get("posts", [])),
        "stories": len(data.get("stories", [])),
        "highlights": len(data.get("highlights", [])),
        "hashtag_entries": len(data.get("hashtags", [])),
        "mention_entries": len(data.get("mentions", [])),
    }

    unavailable = []
    if not data.get("mentions"):
        unavailable.append("following_list")
    if not data.get("stories"):
        unavailable.append("active_stories")
    unavailable.append("comments_text")
    unavailable.append("tagged_posts_by_others")

    report = {
        "target_account": username,
        "generated_at": datetime.now().isoformat(),
        "analysis_method": "rule_based" + ("+ollama" if ai_insights else ""),
        "ollama_model": model,
        "data_sources": data_sources,
        "unavailable_data": unavailable,
        "disclaimer": (
            "Insights are inferred from public metadata only. "
            "Reliability varies by category. Use for personal/educational analysis."
        ),
        "profile": rule_insights["profile_facts"],
        "interests": rule_insights["hobbies_and_interests"]["interests"],
        "hobbies": rule_insights["hobbies_and_interests"]["hobbies"],
        "highlight_topics": rule_insights["hobbies_and_interests"]["highlight_topics"],
        "favorite_places": rule_insights["places_and_travel"]["favorite_places"],
        "travel_preferences": rule_insights["places_and_travel"]["travel_preferences"],
        "music_taste": rule_insights["music_taste"],
        "social_circle": rule_insights["social_circle"],
        "languages": rule_insights["languages"]["languages"],
        "posting_behavior": rule_insights["posting_behavior"],
        "content_signals": rule_insights["content_signals"],
    }

    if ai_insights:
        report["ai_inferred"] = ai_insights

    return report


def print_summary(report):
    print("\n" + "=" * 60)
    print(f"INSIGHTS: @{report['target_account']}")
    print("=" * 60)

    profile = report.get("profile", {})
    if profile.get("college"):
        print(f"  College     : {profile['college']['value']}")
    if profile.get("occupation_hint"):
        print(f"  Occupation  : {profile['occupation_hint']['value']}")
    if profile.get("bio"):
        print(f"  Bio         : {profile['bio']['value'][:80]}...")

    if report.get("hobbies"):
        print(f"\n  Hobbies     : {', '.join(h['value'] for h in report['hobbies'][:5])}")
    if report.get("interests"):
        print(f"  Interests   : {', '.join(i['value'] for i in report['interests'][:5])}")
    if report.get("favorite_places"):
        print(f"  Top places  : {', '.join(p['value'] for p in report['favorite_places'][:3])}")
    if report.get("music_taste", {}).get("music_taste_summary"):
        print(f"  Music       : {report['music_taste']['music_taste_summary']['value']}")

    if report.get("ai_inferred", {}).get("overall_summary"):
        print(f"\n  AI summary  : {report['ai_inferred']['overall_summary']['value']}")

    print("=" * 60)


def main():
    parser = argparse.ArgumentParser(description="Generate Instagram profile insights from scraped data.")
    parser.add_argument("username", nargs="?", default="sharma091_123", help="Target Instagram username")
    parser.add_argument("--no-ollama", action="store_true", help="Skip Ollama inference")
    parser.add_argument("--model", default=DEFAULT_MODEL, help=f"Ollama model (default: {DEFAULT_MODEL})")
    args = parser.parse_args()

    print(f"[*] Loading scraped data for @{args.username}...")
    output_dir, data = load_scraped_data(args.username)

    print("[*] Running rule-based analysis...")
    rule_insights = extract_rule_based_insights(data)

    ai_insights = None
    if not args.no_ollama:
        print(f"[*] Running Ollama inference ({args.model})...")
        try:
            context = build_llm_context(data, rule_insights)
            ai_insights = call_ollama(context, model=args.model)
            print("[✓] Ollama analysis complete.")
        except Exception as exc:
            print(f"[!] Ollama unavailable or failed: {exc}")
            print("[*] Continuing with rule-based insights only.")

    report = build_insights_report(args.username, data, rule_insights, ai_insights, args.model)
    output_path = os.path.join(output_dir, "insights.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    print(f"[✓] Saved insights → {output_path}")
    print_summary(report)


if __name__ == "__main__":
    main()
