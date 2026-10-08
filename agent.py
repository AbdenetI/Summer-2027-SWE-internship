#!/usr/bin/env python3
"""Public career-board watcher for Summer 2027 SWE internships. Python 3.11+."""
import argparse
import datetime as dt
import html
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import smtplib
import sqlite3
import sys
import time
from email.message import EmailMessage
from urllib.parse import quote
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent
UTC = dt.timezone.utc
USER_AGENT = "AbdenetInternWatch/1.0 (personal job search; contact via repository owner)"


class Stripper(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)


def plain(value):
    s = Stripper()
    s.feed(html.unescape(str(value or "")))
    return re.sub(r"\s+", " ", html.unescape(" ".join(s.parts))).strip()


def get_json(url):
    req = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urlopen(req, timeout=20) as response:
        return json.load(response)


def fetch_board(board):
    source, slug = board["source"], board["slug"]
    if source == "greenhouse":
        data = get_json(f"https://boards-api.greenhouse.io/v1/boards/{quote(slug)}/jobs?content=true")
        for j in data.get("jobs", []):
            yield dict(key=f"greenhouse:{slug}:{j['id']}", company=board["company"], title=j.get("title", ""),
                       description=plain(j.get("content")), location=j.get("location", {}).get("name", ""),
                       url=j.get("absolute_url", ""), published=j.get("first_published") or "")
    elif source == "lever":
        data = get_json(f"https://api.lever.co/v0/postings/{quote(slug)}?mode=json")
        for j in data:
            lists = " ".join(plain(v) for v in (j.get("lists") or []) for v in v.values() if isinstance(v, str))
            yield dict(key=f"lever:{slug}:{j['id']}", company=board["company"], title=j.get("text", ""),
                       description=" ".join([plain(j.get("descriptionPlain") or j.get("description")), lists,
                                             plain(j.get("additionalPlain") or j.get("additional"))]),
                       location=j.get("categories", {}).get("location", ""), url=j.get("hostedUrl", ""),
                       published="")
    elif source == "ashby":
        data = get_json(f"https://api.ashbyhq.com/posting-api/job-board/{quote(slug)}")
        for j in data.get("jobs", []):
            if j.get("isListed") is False:
                continue
            yield dict(key=f"ashby:{slug}:{j.get('id') or j.get('jobUrl')}", company=board["company"],
                       title=j.get("title", ""), description=plain(j.get("descriptionPlain") or j.get("descriptionHtml")),
                       location=j.get("location", ""), url=j.get("applyUrl") or j.get("jobUrl", ""),
                       published=j.get("publishedAt") or "")
    else:
        raise ValueError(f"Unknown board source: {source}")


def posted_at(value):
    if not value:
        return None
    try:
        return dt.datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)
    except ValueError:
        return None


def evaluate(j, profile, now):
    title = j["title"].lower()
    body = (j["title"] + " " + j["description"]).lower()
    location = j["location"].lower()
    reasons = []
    if not re.search(r"\b(intern(ship)?|co[- ]?op)\b", title):
        return None
    if not re.search(r"software|full.?stack|backend|back.?end|frontend|front.?end|ai|machine learning|ml engineer|web developer|platform engineer", title):
        return None
    if re.search(r"(202[68]|summer 2026|fall 2027|winter 2027|spring 2027)", title):
        return None
    summer = bool(re.search(r"summer\s*2027|2027\s*summer|may\s*[-–/]\s*august\s*2027", body))
    if re.search(r"summer\s*202[68]|2026\s*summer|2028\s*summer", body) and not summer:
        return None
    if not summer and not profile.get("include_undated_internships", False):
        return None
    # Check the entire description; flagged jobs are excluded even if the title is attractive.
    if re.search(r"security clearance|security clearances|clearance required|clearance eligibility|obtain.{0,35}clearance|active (secret|top secret|ts/sci)|secret clearance|public trust", body):
        return None
    if re.search(r"(must|need|required).{0,50}(u\.?s\.? citizen|us citizen|citizenship|permanent resident|green card)|(u\.?s\.? citizen(ship)?|permanent residenc[ey]|green card).{0,35}(required|only)|u\.?s\.? citizens only|no visa sponsorship|unable to sponsor|cannot sponsor", body):
        return None
    if re.search(r"(graduate|graduation|graduating).{0,90}(2026 only|before (may|june|august) 2027)|class of 2026", body):
        return None
    if re.search(r"(must|required).{0,70}(master'?s|ph\.?d|doctoral) degree", body):
        return None
    if re.search(r"\b(uk|london|canada|toronto|india|bengaluru|singapore|germany|berlin)\b", location) and not re.search(r"\b(us|usa|united states|remote)\b", location):
        return None
    score = 45 if summer else 20
    groups = [
        ("React/TypeScript", r"\breact\b|typescript", 10),
        ("Python/Django/FastAPI", r"\bpython\b|\bdjango\b|\bfastapi\b", 12),
        ("PostgreSQL/SQL", r"postgres|\bsql\b", 8),
        ("AI/ML or LLM applications", r"\bai\b|machine learning|\bllm\b|generative ai|\bnlp\b", 8),
        ("Docker/cloud/API", r"\bdocker\b|\bcloud\b|\bapi\b|\baws\b", 5),
    ]
    for label, pattern, weight in groups:
        if re.search(pattern, body):
            score += weight
            reasons.append(label)
    if re.search(r"full.?stack|backend|back.?end|software engineer", title):
        score += 7
        reasons.append("SWE/full stack/backend role")
    if re.search(r"2027|december 2027|fall 2027|returning to school|enrolled", body):
        score += 3
    if re.search(r"(junior|senior|undergraduate|bachelor|b\.s\.)", body):
        score += 3
    if re.search(r"(minimum|at least|requires?)\s*(2|3|4|5)\+?\s*years?.{0,25}experience", body):
        score -= 25
    threshold = profile.get("minimum_score", 60)
    if score < threshold:
        return None
    published = posted_at(j["published"])
    if published and published < now - dt.timedelta(days=profile.get("max_post_age_days", 21)):
        return None
    return {**j, "score": score, "reasons": reasons,
            "freshness": f"Posted {published.date().isoformat()}" if published else "First seen by this agent"}


def render(jobs):
    lines = ["Summer 2027 SWE internships matched to Abdenet's resume", "",
             "Ranked matches, not interview guarantees. Confirm work authorization and graduation eligibility on each application.", ""]
    for j in jobs:
        lines.extend([f"{j['company']} — {j['title']} ({j['score']} points)",
                      f"Location: {j['location'] or 'See listing'} | {j['freshness']}",
                      f"Why it fits: {', '.join(j['reasons']) or 'Summer 2027 internship'}",
                      j["url"], ""])
    return "\n".join(lines)


def send_email(body, count):
    required = ["SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASSWORD", "EMAIL_TO", "EMAIL_FROM"]
    missing = [k for k in required if not os.getenv(k)]
    if missing:
        raise RuntimeError("Email settings missing: " + ", ".join(missing))
    msg = EmailMessage()
    msg["Subject"] = f"{count} new Summer 2027 SWE internship match{'es' if count != 1 else ''}"
    msg["From"], msg["To"] = os.environ["EMAIL_FROM"], os.environ["EMAIL_TO"]
    msg.set_content(body)
    with smtplib.SMTP(os.environ["SMTP_HOST"], int(os.environ["SMTP_PORT"]), timeout=30) as smtp:
        smtp.starttls()
        smtp.login(os.environ["SMTP_USER"], os.environ["SMTP_PASSWORD"])
        smtp.send_message(msg)


def run(args):
    config = json.loads(Path(args.config).read_text())
    now = dt.datetime.now(UTC)
    all_jobs, failures = [], []
    for board in config["boards"]:
        try:
            all_jobs.extend(fetch_board(board))
        except Exception as ex:
            failures.append(f"{board['company']}: {ex}")
        time.sleep(0.3)
    matches = [x for j in all_jobs if (x := evaluate(j, config["profile"], now))]
    matches.sort(key=lambda j: (-j["score"], j["company"], j["title"]))
    if failures:
        print("Board errors:\n" + "\n".join(failures), file=sys.stderr)
    if args.log:
        log = Path(args.log)
        existing = log.read_text() if log.exists() else ""
        known = set(re.findall(r"\]\((https?://[^)]+)\)", existing))
        selected = []
        for job in matches:
            if job["url"] and job["url"] not in known:
                selected.append(job)
                known.add(job["url"])
        if len(failures) == len(config["boards"]):
            raise RuntimeError("All job boards failed; log left unchanged")
        lines = []
        for job in selected:
            label = (job["company"] + " — " + job["title"]).replace("[", "(").replace("]", ")")
            lines.append(f"- [{label}]({job['url']}) — deadline: See listing — posted: {job['published'] or 'unknown'} — location: {job['location']} — found: {now.strftime('%Y-%m-%dT%H:%M:%SZ')}")
        if args.dry_run:
            print("\n".join(lines) or "No new qualifying matches.")
        elif lines:
            with log.open("a") as output:
                output.write(("\n" if existing and not existing.endswith("\n") else "") + "\n".join(lines) + "\n")
        print(f"Found {len(selected)} new matches; {len(failures)} board errors.")
        return
    db = sqlite3.connect(args.db)
    db.execute("CREATE TABLE IF NOT EXISTS sent (key TEXT PRIMARY KEY, sent_at TEXT NOT NULL)")
    unseen = [j for j in matches if not db.execute("SELECT 1 FROM sent WHERE key=?", (j["key"],)).fetchone()]
    selected = unseen[:config["profile"].get("max_email_matches", 15)]
    if selected:
        body = render(selected)
        if args.dry_run:
            print(body)
        else:
            send_email(body, len(selected))
            with db:
                db.executemany("INSERT INTO sent VALUES (?, ?)", [(j["key"], now.isoformat()) for j in selected])
            print(f"Emailed {len(selected)} matches.")
    else:
        print(f"No new qualifying matches. Checked {len(all_jobs)} postings across {len(config['boards'])} boards.")
    db.close()
    # Fail loudly if all boards were unavailable; partial failures still yield useful results.
    if len(failures) == len(config["boards"]):
        raise RuntimeError("All job boards failed; see errors above")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=str(ROOT / "config.json"))
    parser.add_argument("--db", default=str(ROOT / "seen.sqlite"))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--log", help="Append unseen URLs to a Markdown log instead of emailing")
    run(parser.parse_args())
