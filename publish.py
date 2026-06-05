#!/usr/bin/env python3
# Blogger 자동 예약 발행기 — 표준 라이브러리만 사용(설치 불필요)
# posts/*.json 의 글을 Blogger API로 '미래 날짜 예약'으로 올린다.
# 이미 올린 글은 posts/_published.json 에 기록해 중복 발행 방지.
#
# 필요한 환경변수(또는 GitHub Secrets):
#   BLOGGER_CLIENT_ID, BLOGGER_CLIENT_SECRET, BLOGGER_REFRESH_TOKEN, BLOGGER_BLOG_ID
#
# 글 파일 형식(posts/0001.json):
# {
#   "title": "글 제목",
#   "date":  "2026-06-09 10:00",   # 예약 시각(한국시간 KST)
#   "labels": ["태그1","태그2"],
#   "html":  "<p>본문 HTML…</p>"
# }

import os, json, glob, urllib.request, urllib.parse, datetime, sys

CLIENT_ID = os.environ.get("BLOGGER_CLIENT_ID")
CLIENT_SECRET = os.environ.get("BLOGGER_CLIENT_SECRET")
REFRESH_TOKEN = os.environ.get("BLOGGER_REFRESH_TOKEN")
BLOG_ID = os.environ.get("BLOGGER_BLOG_ID")

HERE = os.path.dirname(os.path.abspath(__file__))
POSTS_DIR = os.path.join(HERE, "posts")
PUBLISHED_LOG = os.path.join(POSTS_DIR, "_published.json")
KST = datetime.timezone(datetime.timedelta(hours=9))

def die(msg):
    print("‼  " + msg); sys.exit(1)

def get_access_token():
    if not all([CLIENT_ID, CLIENT_SECRET, REFRESH_TOKEN]):
        die("환경변수(BLOGGER_CLIENT_ID/SECRET/REFRESH_TOKEN)가 비어 있습니다. SETUP.md 참고.")
    data = urllib.parse.urlencode({
        "client_id": CLIENT_ID, "client_secret": CLIENT_SECRET,
        "refresh_token": REFRESH_TOKEN, "grant_type": "refresh_token",
    }).encode()
    req = urllib.request.Request("https://oauth2.googleapis.com/token", data=data)
    with urllib.request.urlopen(req) as r:
        return json.load(r)["access_token"]

def to_rfc3339(date_str):
    # "2026-06-09 10:00" (KST) -> RFC3339 with +09:00
    dt = datetime.datetime.strptime(date_str.strip(), "%Y-%m-%d %H:%M").replace(tzinfo=KST)
    return dt.isoformat()

def load_published():
    if os.path.exists(PUBLISHED_LOG):
        return set(json.load(open(PUBLISHED_LOG, encoding="utf-8")))
    return set()

def save_published(s):
    json.dump(sorted(s), open(PUBLISHED_LOG, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

def insert_post(token, post):
    body = {
        "kind": "blogger#post",
        "title": post["title"],
        "content": post["html"],
        "labels": post.get("labels", []),
        "published": to_rfc3339(post["date"]),   # 미래 날짜면 Blogger가 예약(SCHEDULED) 처리
    }
    url = f"https://www.googleapis.com/blogger/v3/blogs/{BLOG_ID}/posts/"
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"),
        headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"})
    with urllib.request.urlopen(req) as r:
        res = json.load(r)
    return res.get("id"), res.get("status", "(status?)")

def main():
    if not BLOG_ID:
        die("BLOGGER_BLOG_ID 가 비어 있습니다.")
    token = get_access_token()
    published = load_published()
    files = sorted(glob.glob(os.path.join(POSTS_DIR, "*.json")))
    files = [f for f in files if not f.endswith("_published.json") and "example" not in os.path.basename(f).lower()]
    done = 0
    for f in files:
        name = os.path.basename(f)
        if name in published:
            continue
        post = json.load(open(f, encoding="utf-8"))
        try:
            pid, status = insert_post(token, post)
            published.add(name); save_published(published)
            print(f"✅ {name}  →  {post['date']} 예약 ({status})  id={pid}")
            done += 1
        except Exception as e:
            print(f"❌ {name} 실패: {e}")
    print(f"\n완료: {done}개 새로 예약, {len(published)}개 누적.")

if __name__ == "__main__":
    main()
