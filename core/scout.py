"""Bounded, evidence-backed employment scouting and per-profile history."""
import hashlib
import json
import os
import re
import tempfile
from datetime import datetime, timedelta
from threading import Event
from typing import Literal
from urllib.parse import urlsplit
from uuid import uuid4
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field

from core.automation.assistant import generate_text
from core.automation.models import ApplicantProfile, canonical_url, job_identity, normalized
from core.automation.privacy import redact
from core.scout_sources import DEFAULT_SOURCES, EXCLUDED, NOT_EMPLOYER, PublicReader, discover, employment_link

SG = ZoneInfo("Asia/Singapore")
DEFAULT_BRIEF = ("Singapore Citizen, Year 2 undergraduate, double major Data Science + Economics. "
                 "Singapore internships and student-eligible jobs in finance (investing, VC/PE, central banking, "
                 "capital markets) and data. Prioritise niche government-linked employers and finance institutions.")
FRESHNESS_ORDER = {"recent": 0, "earlier": 1, "undated": 2}
KINDS = {"internships": {"internship"}, "jobs": {"job"}, "both": {"internship", "job"}}


class ScoutSettings(BaseModel):
    enabled: bool = False
    mode: Literal["internships", "jobs", "both"] = "internships"
    brief: str = Field(default=DEFAULT_BRIEF, min_length=1, max_length=5000)
    sources: str = Field(default=DEFAULT_SOURCES, max_length=12000)
    consent: str = ""


class Evidence(BaseModel):
    value: str = Field(default="", max_length=800)
    quote: str = Field(default="", max_length=1600)


class Assessment(BaseModel):
    kind: Literal["internship", "job", "other"]
    eligible: bool = Field(strict=True)
    is_posting: bool = Field(strict=True)
    is_open: bool = Field(strict=True)
    is_publisher: bool = Field(strict=True)
    title: str = Field(default="", max_length=250)
    organisation: str = Field(default="", max_length=200)
    reason: str = Field(default="", max_length=1800)
    official_url: str = ""
    evidence: dict[str, Evidence] = Field(default_factory=dict)


class Opportunity(BaseModel):
    id: str
    profile_name: str
    profile_snapshot: ApplicantProfile
    url: str
    title: str
    organisation: str
    kind: Literal["internship", "job"]
    reason: str
    evidence: dict[str, Evidence]
    published: str = ""
    deadline: str = ""
    freshness: Literal["recent", "earlier", "undated"]
    first_seen: str
    verified_at: str
    description: str = ""
    active: bool = True


def timestamp(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.replace(tzinfo=SG) if parsed.tzinfo is None else parsed
    except (ValueError, TypeError):
        return None


def consent_key(cfg, settings, profile):
    # A changed provider, endpoint, brief or profile needs a new preview before unattended disclosure.
    payload = [cfg["provider"], cfg["model"], cfg.get("url", ""), search_context(settings, profile)]
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def search_context(settings, profile):
    facts = profile.model_dump(include={"education", "experience", "skills", "languages", "summary", "citizenship", "country"})
    context = redact(json.dumps({"brief": settings.brief, "mode": settings.mode, "career_facts": facts}, ensure_ascii=False), profile)
    if len(context) > 16000:
        raise ValueError("Shorten the search brief or career facts to fit the Scout context limit.")
    return context


def deadline_expired(value, at):
    deadline = timestamp(value)
    if deadline is None:
        return False
    if "T" in value or " " in value:
        return deadline < at
    return deadline.astimezone(SG).date() < at.astimezone(SG).date()


def date_supported(value, quote, at):
    date = timestamp(value)
    if date is None:
        return False
    # "30th November 2026" proves the same date as "30 November 2026".
    compact = re.sub(r"[^a-z0-9]", "", re.sub(r"(\d)(?:st|nd|rd|th)\b", r"\1", quote.casefold()))
    formats = ("%Y-%m-%d", "%d/%m/%Y", "%d %b %Y", "%d %B %Y", "%b %d %Y", "%B %d %Y")
    for fmt in formats:
        formatted = date.strftime(fmt)
        variants = {formatted, re.sub(r"\b0(\d)\b", r"\1", formatted)}
        if any(re.sub(r"[^a-z0-9]", "", candidate.casefold()) in compact for candidate in variants):
            return True
    days = (at.astimezone(SG).date() - date.astimezone(SG).date()).days
    return (days == 0 and bool(re.search(r"\btoday\b", quote, re.I))) or (days == 1 and bool(re.search(r"\byesterday\b", quote, re.I)))


def daily_due(settings, last_attempt, at):
    local = at.astimezone(SG)
    return settings.enabled and local.hour >= 8 and last_attempt != local.date().isoformat()


def source_rows(settings):
    rows = []
    for line in settings.sources.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        name, separator, url = line.partition("|")
        url = url.strip() if separator else name.strip()
        # "www.mas.gov.sg/careers" means HTTPS; an explicit http:// is still refused.
        url = url if "://" in url else "https://" + url
        rows.append((name.strip() if separator else urlsplit(url).hostname, canonical_url(url, supported_only=False)))
    if len(rows) > 60:
        raise ValueError("Use at most 60 priority sources.")
    return rows


def json_reply(reply):
    reply = re.sub(r"<think>.*?</think>", "", reply, flags=re.S).strip()
    if reply.startswith("```"):
        reply = re.sub(r"^```(?:json)?\s*|\s*```$", "", reply)
    start = reply.find("{")
    if start < 0:
        raise ValueError("The AI reply did not contain a posting assessment.")
    # A model that corrects itself ("Correction: ... The correct output is: {...}") means its last object.
    payload, end = json.JSONDecoder().raw_decode(reply, start)
    while (start := reply.find("{", end)) >= 0:
        try:
            payload, end = json.JSONDecoder().raw_decode(reply, start)
        except ValueError:
            break

    # Models write null for unknown values; unknown means the field's empty default, not a rejected posting.
    def drop_nulls(value):
        if isinstance(value, dict):
            return {k: drop_nulls(v) for k, v in value.items() if v is not None}
        return value
    return Assessment.model_validate(drop_nulls(payload))


def verified_opportunity(assessment, url, text, profile_name, profile, settings, at):
    if assessment.kind not in KINDS[settings.mode] or not assessment.eligible or not assessment.is_posting or not assessment.is_open or not assessment.is_publisher:
        return None
    if not assessment.title or not assessment.organisation or not assessment.reason or normalized(assessment.title) not in normalized(text):
        return None
    evidence = {}
    page = normalized(text)
    for key in ("opening", "eligibility", "start", "duration", "hours", "published", "deadline"):
        fact = assessment.evidence.get(key, Evidence())
        evidence[key] = fact if fact.value and fact.quote and normalized(fact.quote) in page else Evidence()
    for key in ("published", "deadline"):
        if evidence[key].value and not date_supported(evidence[key].value, evidence[key].quote, at):
            evidence[key] = Evidence()
    if evidence["hours"].value and not re.search(r"(?:part|full)[ -]?time|\bhours?\b|\b\d+\s*(?:hrs?|days?)\b", evidence["hours"].quote, re.I):
        evidence["hours"] = Evidence()
    if not evidence["opening"].value:
        return None
    # Dates without source evidence are unknown, never proof of freshness or urgency.
    published = timestamp(evidence["published"].value)
    deadline = timestamp(evidence["deadline"].value)
    if evidence["published"].value and not published:
        raise ValueError("The posting date could not be verified.")
    # A future date is a misread, not a posting; an older open posting is still worth applying to.
    if published and published > at:
        return None
    if deadline_expired(evidence["deadline"].value, at):
        return None
    if evidence["deadline"].value and not deadline:
        evidence["deadline"] = Evidence()
    return Opportunity(id=hashlib.sha256(job_identity(url).encode()).hexdigest(), profile_name=profile_name,
        profile_snapshot=profile.model_copy(deep=True), url=url, title=assessment.title, organisation=assessment.organisation,
        kind=assessment.kind, reason=assessment.reason, evidence=evidence,
        published=evidence["published"].value, deadline=evidence["deadline"].value,
        freshness=("recent" if published >= at - timedelta(hours=48) else "earlier") if published else "undated", first_seen=at.isoformat(), verified_at=at.isoformat(),
        description=text.split("\nOfficial board feed ")[0][:20000])


def sort_key(item, at):
    deadline = timestamp(item.deadline)
    today = at.astimezone(SG).date()
    days = (deadline.astimezone(SG).date() - today).days if deadline else None
    urgent = days is not None and 0 <= days <= 14
    return (not urgent, days if urgent else 99999, FRESHNESS_ORDER[item.freshness], item.organisation.casefold(), item.title.casefold())


class Scout:
    def __init__(self, store, cfg, brave_key="", stop=None, progress=None, reader=None, search=None, assess=None):
        self.store, self.cfg, self.brave_key = store, cfg, brave_key
        self.stop = stop or Event()
        self.progress = progress or (lambda text: None)
        self.reader, self.search, self.assess = reader or PublicReader(), search or discover, assess or generate_text

    def scan(self, profile_name, profile, settings, at=None):
        at = at or datetime.now(SG)
        sources = source_rows(settings)
        context = search_context(settings, profile)
        report = {"id": str(uuid4()), "profile_name": profile_name, "started_at": at.isoformat(), "new_ids": [], "seen_ids": [],
                  "checked": 0, "search_requests": 0, "issues": [], "sources": [], "mode": "Direct sources", "status": "running"}
        self.store.save_scout_report(report)
        candidates, identities, feed_seen = [], set(), set()
        metadata = {}

        def add(url):
            try:
                # In-page anchors (#main-content) re-queue the same page; hash routes (#/job/1) stay distinct.
                url = re.sub(r"#[^/]*$", "", canonical_url(url, supported_only=False))
                identity = job_identity(url)
                if identity not in identities and not EXCLUDED.search(url) and not NOT_EMPLOYER.search(url):
                    identities.add(identity)
                    candidates.append(url)
            except (ValueError, TypeError):
                pass

        def read_feed(url):
            if url in feed_seen:
                return
            feed_seen.add(url)
            final, body, _ = self.reader.read(url)
            data = json.loads(body)
            jobs = data.get("jobs", []) if isinstance(data, dict) else data
            for job in jobs:
                link = job.get("absolute_url") or job.get("hostedUrl")
                if link:
                    add(link)
                    # Lever dates are epoch milliseconds, which no quote can prove; lead with a readable date so truncation keeps it.
                    if isinstance(job.get("createdAt"), int):
                        job = {"createdAt_date": datetime.fromtimestamp(job["createdAt"] / 1000, SG).isoformat(timespec="minutes"), **job}
                    metadata[job_identity(link)] = "\nOfficial board feed " + final + "\n" + json.dumps(job, ensure_ascii=False)[:10000]

        try:
            for name, url in sources:
                if self.stop.is_set():
                    break
                self.progress("Checking " + name)
                try:
                    final, text, links = self.reader.read(url, listing=True)
                    if urlsplit(final).hostname in {"api.lever.co", "api.eu.lever.co", "boards-api.greenhouse.io"}:
                        read_feed(final)
                    elif (re.search(r"intern(?!et|ation|al)|/jobs?/[^/]+", urlsplit(final).path, re.I) or 'JobPosting' in text
                          or (not any(employment_link(link) for link in links) and re.search(r"\binternship\b|\bvacanc", text, re.I))):
                        add(final)
                    for link in links:
                        if employment_link(link):
                            add(link)
                    # Public ATS APIs expose the employer's complete listing without an application account.
                    for link in links:
                        parts = urlsplit(link)
                        if parts.hostname in {"jobs.lever.co", "jobs.eu.lever.co"} and parts.path.strip("/"):
                            tenant = parts.path.strip("/").split("/")[0]
                            api_host = "api.eu.lever.co" if parts.hostname == "jobs.eu.lever.co" else "api.lever.co"
                            read_feed(f"https://{api_host}/v0/postings/{tenant}?mode=json")
                        elif parts.hostname in {"boards.greenhouse.io", "job-boards.greenhouse.io"} and parts.path.strip("/"):
                            tenant = parts.path.strip("/").split("/")[0]
                            read_feed(f"https://boards-api.greenhouse.io/v1/boards/{tenant}/jobs?content=true")
                    report["sources"].append({"name": name, "url": url, "status": "Opened"})
                except Exception:
                    report["sources"].append({"name": name, "url": url, "status": "Unavailable or requires sign-in"})
                    report["issues"].append(f"{name}: public source could not be checked.")

            broad = bool(self.brave_key) or self.cfg["provider"] in {"openai", "anthropic"}
            if broad:
                report["mode"] += " + " + ("Brave Search" if self.brave_key else self.cfg["name"] + " web search")
                groups = [sources[i::5] for i in range(5) if sources[i::5]] + [[]]
                for group in groups:
                    if self.stop.is_set():
                        continue
                    target = ", ".join(n for n, _ in group) if group else "other Singapore employers beyond the priority watchlist"
                    wanted = {"internships": "internships", "jobs": "student-eligible jobs", "both": "internships and student-eligible jobs"}[settings.mode]
                    query = (f"Find currently open {wanted} at {target}. " + redact(settings.brief, profile)
                             + " Prioritise postings published or updated in the past 48 hours. Return official posting sources.")
                    report["search_requests"] += 1
                    self.progress(f"Discovering postings ({report['search_requests']}/6)")
                    try:
                        for url in self.search(self.cfg, query, self.brave_key):
                            add(url)
                    except ValueError as exc:
                        report["issues"].append(str(exc))
                        break
            else:
                report["issues"].append("Broad web search is off. Add an optional Brave Search key for this provider.")

            # Concrete job links first (including every posting an official board feed lists, whatever its URL shape);
            # general career landing pages remain discoverable but cannot crowd them out.
            def general(u):
                return job_identity(u) not in metadata and not re.search(r"/jobs?/[^?]+|/postings/|/intern(?!et|ation|al)[^/?]*|/position/", u, re.I)
            # Interleave hosts within each tier so one large board cannot consume the whole candidate budget.
            counts, positions = {}, {}
            for url in candidates:
                key = (general(url), urlsplit(url).hostname)
                positions[url] = counts.get(key, 0)
                counts[key] = positions[url] + 1
            candidates.sort(key=lambda url: (general(url), positions[url]))
            fetched = set()
            index = 0
            while index < len(candidates) and report["checked"] < 40 and not self.stop.is_set():
                url = candidates[index]
                index += 1
                report["checked"] += 1
                self.progress(f"Verifying posting {report['checked']}/40")
                try:
                    final, text, links = self.reader.read(url)
                    identity = job_identity(final)
                    if identity in fetched or NOT_EMPLOYER.search(final):
                        continue
                    fetched.add(identity)
                    if urlsplit(final).hostname in {"api.lever.co", "api.eu.lever.co", "boards-api.greenhouse.io"}:
                        read_feed(final)
                        continue
                    text += metadata.get(identity, metadata.get(job_identity(url), ""))
                    payload_data = {"search": context, "today": at.isoformat(), "url": final, "page": text,
                                    "links": [u for u in links[:30] if len(u) <= 500]}
                    payload = json.dumps(payload_data, ensure_ascii=False)
                    if len(payload) > 60000:
                        payload_data["page"] = text[:max(0, 54000 - len(payload) + len(text))]
                        payload = json.dumps(payload_data, ensure_ascii=False)
                    assessment = json_reply(self.assess(self.cfg, "scout", payload))
                    self.store.record_event("scout", "scout_ai", "assessment", self.cfg["provider"])
                    if not assessment.is_publisher and assessment.official_url in links:
                        add(assessment.official_url)
                    if assessment.kind == "other" or not assessment.is_posting:
                        for link in links:
                            if employment_link(link):
                                add(link)
                    opportunity = verified_opportunity(assessment, final, text, profile_name, profile, settings, at)
                    if opportunity:
                        report["seen_ids"].append(opportunity.id)
                        if self.store.save_opportunity(opportunity):
                            report["new_ids"].append(opportunity.id)
                    elif assessment.is_publisher and not assessment.is_open:
                        self.store.close_opportunity(profile_name, hashlib.sha256(identity.encode()).hexdigest())
                    self.store.save_scout_report(report)
                except Exception:
                    report["issues"].append(f"Could not verify {urlsplit(url).hostname}{urlsplit(url).path}.")
            if index < len(candidates) and report["checked"] == 40:
                report["issues"].append("The 40-posting limit was reached; more candidates remain.")
            report["status"] = "cancelled" if self.stop.is_set() else ("partial" if report["issues"] else "complete")
        except Exception:
            report["status"] = "failed"
            report["issues"].append("The scan stopped unexpectedly. Saved results are available; try Scan now again.")
        finally:
            try:
                self.reader.close()
            except Exception:
                report["issues"].append("The scouting browser could not close cleanly.")
                report["status"] = "partial"
            report["finished_at"] = datetime.now(SG).isoformat()
            self.store.save_scout_report(report)
            try:
                write_log(self.store)
            except OSError:
                report["issues"].append("The Markdown log could not be written. Results are saved in the database.")
                report["status"] = "partial"
                self.store.save_scout_report(report)
        return report


def write_log(store):
    """Regenerate from committed SQLite records so a failed export is repairable."""
    path = store.path.parent / "opportunities-log.md"
    lines = ["# Intern-Bot opportunities log", ""]
    for item in store.opportunities():
        lines += [f"## {item.profile_name} · {item.title}",
                  f"- {item.organisation} · {item.kind} · {item.freshness}",
                  f"- First seen {item.first_seen} · Verified {item.verified_at}",
                  f"- Deadline {item.deadline or 'Not stated'}", f"- {item.url}", f"- {item.reason}", ""]
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as file:
            temporary = file.name
            file.write("\n".join(lines))
        os.replace(temporary, path)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)
