#!/usr/bin/env python3
# Blogger 자동 예약 발행기 — 표준 라이브러리만 사용(설치 불필요)
# posts/*.json 의 글을 Blogger API로 올린다.
# 이미 올린 글은 posts/_published.json 에 기록해 중복 발행 방지.
#
# ★ 사람처럼 "이틀에 한 편씩" 천천히 올린다.
#   - 한 번 실행에 MAX_PER_RUN(기본 1)편만 올림
#   - 워크플로(cron)가 이틀에 한 번 돌게 설정 → 결과적으로 이틀에 1편
#   - 발행(공개) 날짜도 코드가 자동으로 '이틀 간격'으로 매긴다
#     (그래서 글 파일의 date 값은 신경 안 써도 되고, 다시 올릴 필요 없음)
#   - 블로거 하루 한도(403)가 나오면 그날은 멈추고 다음 실행에서 이어감
#
# GitHub Secrets:
#   BLOGGER_CLIENT_ID, BLOGGER_CLIENT_SECRET, BLOGGER_REFRESH_TOKEN, BLOGGER_BLOG_ID
# 선택 환경변수:
#   MAX_PER_RUN       한 번 실행에 올릴 최대 편수 (기본 1)
#   SCHEDULE_START    새 글(0018편~) 첫 공개일 (기본 2026-08-14, 기존 17편 다음)
#   SCHEDULE_GAP_DAYS 글 사이 간격(일) (기본 2 = 이틀에 한 편)
#   BASE_COUNT        기존 방식(자체 date)으로 이미 올린 마지막 편 번호 (기본 17)

import os, json, glob, urllib.request, urllib.parse, datetime, sys, time

CLIENT_ID = os.environ.get("BLOGGER_CLIENT_ID")
CLIENT_SECRET = os.environ.get("BLOGGER_CLIENT_SECRET")
REFRESH_TOKEN = os.environ.get("BLOGGER_REFRESH_TOKEN")
BLOG_ID = os.environ.get("BLOGGER_BLOG_ID")

MAX_PER_RUN = int(os.environ.get("MAX_PER_RUN", "1"))
SLEEP_SECONDS = float(os.environ.get("SLEEP_SECONDS", "5"))
SCHEDULE_START = os.environ.get("SCHEDULE_START", "2026-08-14")
GAP_DAYS = int(os.environ.get("SCHEDULE_GAP_DAYS", "2"))
BASE_COUNT = int(os.environ.get("BASE_COUNT", "17"))   # 0001~0017은 예전 방식으로 이미 발행됨

HERE = os.path.dirname(os.path.abspath(__file__))
POSTS_DIR = os.path.join(HERE, "posts")
PUBLISHED_LOG = os.path.join(POSTS_DIR, "_published.json")
KST = datetime.timezone(datetime.timedelta(hours=9))

def die(msg):
    print("‼  " + msg); sys.exit(1)

def post_number(name):
    try: return int(os.path.splitext(os.path.basename(name))[0])
    except: return 999999

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

def load_published():
    if os.path.exists(PUBLISHED_LOG):
        return set(json.load(open(PUBLISHED_LOG, encoding="utf-8")))
    return set()

def save_published(s):
    json.dump(sorted(s), open(PUBLISHED_LOG, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

def scheduled_date(new_index):
    # new_index = 0,1,2... (새 글 순번) → 첫 글은 SCHEDULE_START, 이후 GAP_DAYS씩
    start = datetime.datetime.strptime(SCHEDULE_START, "%Y-%m-%d").replace(hour=10, minute=0, tzinfo=KST)
    return (start + datetime.timedelta(days=GAP_DAYS * new_index)).isoformat()

def insert_post(token, post, published_rfc3339):
    body = {
        "kind": "blogger#post",
        "title": post["title"],
        "content": post["html"],
        "labels": post.get("labels", []),
        "published": published_rfc3339,   # 미래 날짜면 Blogger가 예약(SCHEDULED) 처리
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

    # 이미 올린 '새 글(번호 > BASE_COUNT)' 개수 → 다음 공개일 계산용
    new_done = sum(1 for n in published if post_number(n) > BASE_COUNT)

    done = 0
    print(f"이번 실행 한도: 최대 {MAX_PER_RUN}편 / 공개 간격 {GAP_DAYS}일 / 시작일 {SCHEDULE_START} / 이미 올린 새글 {new_done}편")
    for f in files:
        name = os.path.basename(f)
        if name in published:
            continue
        if done >= MAX_PER_RUN:
            print(f"⏸ 이번 실행 한도({MAX_PER_RUN}편) 도달 — 나머지는 다음 자동 실행에서 이어서.")
            break
        post = json.load(open(f, encoding="utf-8"))
        sched = scheduled_date(new_done)
        try:
            pid, status = insert_post(token, post, sched)
            published.add(name); save_published(published)
            print(f"✅ {name}  →  {sched[:10]} 공개 예약 ({status})  id={pid}")
            done += 1; new_done += 1
            time.sleep(SLEEP_SECONDS)
        except Exception as e:
            msg = str(e)
            print(f"❌ {name} 실패: {msg}")
            if "403" in msg or "429" in msg:
                print("⛔ 블로거 일일 발행 한도(403/429)로 보입니다. 오늘은 여기까지 — 다음 실행에서 자동으로 이어집니다.")
                break
    print(f"\n완료: {done}편 새로 예약, {len(published)}편 누적.")

if __name__ == "__main__":
    main()
