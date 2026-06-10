#!/usr/bin/env python3
# Blogger 자동 예약 발행기 v2 — 표준 라이브러리만 사용(설치 불필요)
# v1 대비 개선:
#  1) 403/429 응답 본문(reason)을 읽어 정확한 원인 기록 (rateLimitExceeded / blogger.post.create 거부 등)
#  2) posts/_status.json 에 매 실행 결과 기록 (연속 403 횟수, 마지막 성공, 페널티 해제 감지)
#  3) GITHUB_STEP_SUMMARY 에 한글 요약 출력 → Actions 실행 페이지에서 로그인 없이도 결과 확인
#  4) 5xx 일시 오류는 60초 후 1회 재시도 (403/429는 재시도 안 함 — 일일 한도라 무의미)
#  5) 페널티가 풀려 첫 성공이 나오면 ✅ "페널티 해제!" 표시
# 사용법·환경변수는 v1과 동일 (MAX_PER_RUN, SCHEDULE_START, SCHEDULE_GAP_DAYS, BASE_COUNT)

import os, json, glob, urllib.request, urllib.error, urllib.parse, datetime, sys, time

CLIENT_ID = os.environ.get("BLOGGER_CLIENT_ID")
CLIENT_SECRET = os.environ.get("BLOGGER_CLIENT_SECRET")
REFRESH_TOKEN = os.environ.get("BLOGGER_REFRESH_TOKEN")
BLOG_ID = os.environ.get("BLOGGER_BLOG_ID")

MAX_PER_RUN = int(os.environ.get("MAX_PER_RUN", "1"))
SLEEP_SECONDS = float(os.environ.get("SLEEP_SECONDS", "5"))
SCHEDULE_START = os.environ.get("SCHEDULE_START", "2026-08-14")
GAP_DAYS = int(os.environ.get("SCHEDULE_GAP_DAYS", "2"))
BASE_COUNT = int(os.environ.get("BASE_COUNT", "17"))

HERE = os.path.dirname(os.path.abspath(__file__))
POSTS_DIR = os.path.join(HERE, "posts")
PUBLISHED_LOG = os.path.join(POSTS_DIR, "_published.json")
STATUS_LOG = os.path.join(POSTS_DIR, "_status.json")
KST = datetime.timezone(datetime.timedelta(hours=9))

def now_kst(): return datetime.datetime.now(KST).strftime("%Y-%m-%d %H:%M KST")

def die(msg):
    print("!! " + msg); sys.exit(1)

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

def load_json(path, default):
    if os.path.exists(path):
        try: return json.load(open(path, encoding="utf-8"))
        except Exception: return default
    return default

def save_json(path, obj):
    json.dump(obj, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

def scheduled_date(new_index):
    start = datetime.datetime.strptime(SCHEDULE_START, "%Y-%m-%d").replace(hour=10, minute=0, tzinfo=KST)
    return (start + datetime.timedelta(days=GAP_DAYS * new_index)).isoformat()

def http_error_detail(e):
    """HTTPError에서 코드 + 구글 API의 reason까지 뽑아낸다."""
    code = getattr(e, "code", "?")
    reason = ""
    try:
        body = e.read().decode("utf-8", "replace")
        j = json.loads(body)
        errs = j.get("error", {}).get("errors", [])
        reason = ",".join(x.get("reason", "") for x in errs) or j.get("error", {}).get("message", "")[:120]
    except Exception:
        pass
    return code, reason

def insert_post(token, post, published_rfc3339):
    body = {
        "kind": "blogger#post",
        "title": post["title"],
        "content": post["html"],
        "labels": post.get("labels", []),
        "published": published_rfc3339,
    }
    url = f"https://www.googleapis.com/blogger/v3/blogs/{BLOG_ID}/posts/"
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"),
        headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"})
    with urllib.request.urlopen(req) as r:
        res = json.load(r)
    return res.get("id"), res.get("status", "(status?)")

def write_summary(lines):
    """Actions 실행 페이지 '요약'에 한글 결과 표시 (로그인 없이도 보임)."""
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    text = "\n".join(lines)
    print("\n" + text)
    if path:
        with open(path, "a", encoding="utf-8") as f:
            f.write(text + "\n")

def main():
    if not BLOG_ID:
        die("BLOGGER_BLOG_ID 가 비어 있습니다.")
    token = get_access_token()
    published = set(load_json(PUBLISHED_LOG, []))
    status = load_json(STATUS_LOG, {"consecutive_403": 0, "last_success": None, "history": []})

    files = sorted(glob.glob(os.path.join(POSTS_DIR, "*.json")))
    files = [f for f in files if not os.path.basename(f).startswith("_")
             and "example" not in os.path.basename(f).lower()]
    new_done = sum(1 for n in published if post_number(n) > BASE_COUNT)
    remaining = [f for f in files if os.path.basename(f) not in published]

    done, blocked, detail = 0, False, ""
    was_blocked = status.get("consecutive_403", 0) > 0

    for f in remaining:
        if done >= MAX_PER_RUN:
            break
        name = os.path.basename(f)
        post = json.load(open(f, encoding="utf-8"))
        sched = scheduled_date(new_done)
        for attempt in (1, 2):
            try:
                pid, st = insert_post(token, post, sched)
                published.add(name); save_json(PUBLISHED_LOG, sorted(published))
                print(f"OK {name} -> {sched[:10]} 공개 예약 ({st}) id={pid}")
                done += 1; new_done += 1
                time.sleep(SLEEP_SECONDS)
                break
            except urllib.error.HTTPError as e:
                code, reason = http_error_detail(e)
                detail = f"{code} {reason}"
                if code in (403, 429):
                    blocked = True
                    print(f"BLOCKED {name}: HTTP {code} ({reason}) — 일일 한도/스팸 페널티. 오늘은 중단.")
                    break
                if 500 <= int(code) < 600 and attempt == 1:
                    print(f"RETRY {name}: HTTP {code} 일시 오류 — 60초 후 1회 재시도")
                    time.sleep(60); continue
                print(f"FAIL {name}: HTTP {code} ({reason})")
                break
            except Exception as e:
                detail = str(e)[:200]
                print(f"FAIL {name}: {detail}")
                break
        if blocked:
            break

    # 상태 기록
    if blocked:
        status["consecutive_403"] = status.get("consecutive_403", 0) + 1
    elif done > 0:
        status["consecutive_403"] = 0
        status["last_success"] = now_kst()
    status.setdefault("history", []).append(
        {"time": now_kst(), "published": done, "blocked": blocked, "detail": detail})
    status["history"] = status["history"][-30:]
    save_json(STATUS_LOG, status)

    # 한눈 요약
    lines = ["## Blogger 자동발행 결과 (" + now_kst() + ")"]
    if done > 0 and was_blocked:
        lines.append(f"🎉 **페널티 해제!** 이번 실행에서 {done}편 예약 성공 — 내일부터 정상 재개.")
    elif done > 0:
        lines.append(f"✅ {done}편 예약 성공.")
    elif blocked:
        lines.append(f"⛔ 여전히 차단 (연속 {status['consecutive_403']}회): {detail}")
    elif not remaining:
        lines.append("✔ 남은 글 없음 — 전부 발행 완료.")
    else:
        lines.append(f"⚠ 발행 0편 (오류: {detail or '원인 미상'})")
    lines.append(f"누적 발행 {len(published)}편 / 대기 {max(0, len(remaining)-done)}편")
    write_summary(lines)

if __name__ == "__main__":
    main()
