"""Public discovery and isolated posting reads. No application cookies or credentials."""
import ipaddress
import json
import re
import socket
from html.parser import HTMLParser
from urllib.parse import urlencode, urljoin, urlsplit, unquote
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from core.automation.assistant import NoRedirect
from core.automation.models import canonical_url

MAX_BYTES = 2_000_000
JOB_LINK = re.compile(r"intern(?!et|ation|al)|\bjobs?\b|career|vacanc|position|opportunit|requisition", re.I)
EXCLUDED = re.compile(r"scholarship|bursary|privacy|cookie|sign.?in|log.?in|/form/website-feedback(?:/|$)|/example-page(?:/|$)|/blog/|"
                      r"\.(?:pdf|docx?|xlsx?|png|jpe?g|svg)(?:\?|$)", re.I)
# Social, news, search-aggregator and form hosts never hold a verifiable employer posting (a third of a live run's budget).
NOT_EMPLOYER = re.compile(r"^https://(?:[^/]*\.)?(?:linkedin|instagram|facebook|twitter|youtube|tiktok|reddit|wikipedia|glassdoor|indeed|"
                          r"straitstimes|channelnewsasia|yahoo|tracxn|crunchbase|pitchbook|medium)\.|^https://(?:www\.)?(?:lever\.co|form\.gov\.sg)/", re.I)
# Client-rendered boards: their HTML shell is useless (and can exceed MAX_BYTES), so they go straight to the browser.
SPA_HOSTS = {"jobs.careers.gov.sg", "www.mycareersfuture.gov.sg", "careers.sggc.sg"}


def employment_link(url):
    parts = urlsplit(url)
    path = unquote(parts.path)
    if EXCLUDED.search(path) or re.search(r"\.(?:pdf|docx?|xlsx?|png|jpe?g|svg)$", path, re.I):
        return False
    board = parts.hostname in {"jobs.lever.co", "jobs.eu.lever.co", "boards.greenhouse.io", "job-boards.greenhouse.io"}
    return (board and bool(path.strip("/"))) or bool(JOB_LINK.search(path + "?" + parts.query))


DEFAULT_SOURCES = """SG Growth Capital (EDBI and SEEDS) | https://jobs.eu.lever.co/sggc
# No careers page on their sites; kept so the targeted web search names them.
Heliconia Capital | https://www.heliconiacapital.com/
Vertex Holdings | https://vertexholdings.com/
Seviora (incl. Seviora Capital) | https://www.sevioragroup.com/careers
Clifford Capital | https://www.cliffordcapital.sg/careers/
MAS | https://www.mas.gov.sg/careers
MTI Economist Service | https://www.mti.gov.sg/who-we-are/careers-at-mti/economist-service/join-the-economist-service/
MOF | https://www.mof.gov.sg/careers
CCS (formerly CCCS) | https://www.ccs.gov.sg/about-ccs/careers/opportunities/
IBF | https://www.ibf.org.sg/youngtalent/ytp-aif
SGX | https://careers.sgx.com/search/?q=intern
Careers@Gov | https://www.careers.gov.sg/join-us/early-careers/
MyCareersFuture | https://www.mycareersfuture.gov.sg/search?search=intern&sortBy=new_posting_date&page=0
NUS | https://nus.edu.sg/cfg/students/jobs-internships
NTU | https://www.ntu.edu.sg/education/career-guidance-industry-collaborations
SMU | https://careerservices.smu.edu.sg/"""


def public_url(url):
    url = canonical_url(url.strip(), supported_only=False)
    host = urlsplit(url).hostname
    if host == "localhost" or host.endswith((".local", ".localhost")):
        raise ValueError("Scout reads public HTTPS pages only.")
    addresses = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
        raise ValueError("Scout reads public HTTPS pages only.")
    return url


class PublicRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return super().redirect_request(req, fp, code, msg, headers, public_url(newurl))


class PostingHTML(HTMLParser):
    def __init__(self, url):
        super().__init__(convert_charrefs=True)
        self.url, self.parts, self.links = url, [], []
        self.hidden = 0
        self.json_script = False
        self.script = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in {"script", "style", "nav", "footer"}:
            self.hidden += 1
            self.json_script = tag == "script" and attrs.get("type") == "application/ld+json"
            self.script = []
        if tag == "a" and attrs.get("href"):
            link = urljoin(self.url, attrs["href"])
            if link.startswith("https://"):
                self.links.append(link)
        if tag == "meta" and attrs.get("property", attrs.get("name", "")) in {"og:title", "description"}:
            self.parts.append(attrs.get("content", ""))

    def handle_endtag(self, tag):
        if tag in {"script", "style", "nav", "footer"}:
            if self.json_script:
                self.parts.extend(self.script)
            self.hidden = max(0, self.hidden - 1)
            self.json_script = False
        if tag in {"p", "div", "li", "h1", "h2", "a", "br"}:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)
        elif self.json_script:
            self.script.append(data)

    @property
    def text(self):
        return re.sub(r"[ \t]+", " ", " ".join(self.parts)).strip()


def api_json(url, body=None, headers=None):
    request = Request(url, data=json.dumps(body).encode() if body is not None else None,
                      headers={"Content-Type": "application/json", **(headers or {})})
    with build_opener(NoRedirect()).open(request, timeout=40) as response:
        payload = response.read(MAX_BYTES + 1)
    if len(payload) > MAX_BYTES:
        raise ValueError("The API response exceeded the scan limit.")
    return json.loads(payload)


def discover(cfg, query, brave_key=""):
    """Return real tool-result URLs, never URLs invented in generated prose."""
    try:
        if brave_key:
            data = api_json("https://api.search.brave.com/res/v1/web/search?" + urlencode({"q": " ".join(query.split()[:75])[:600], "count": 20, "country": "SG"}),
                            headers={"X-Subscription-Token": brave_key})
            return [r["url"] for r in data.get("web", {}).get("results", [])]
        if cfg["provider"] == "openai":
            data = api_json("https://api.openai.com/v1/responses", {
                "model": cfg["model"], "store": False, "input": query,
                "tools": [{"type": "web_search"}], "tool_choice": "required", "max_tool_calls": 1,
                "include": ["web_search_call.action.sources"], "max_output_tokens": 2000,
            }, {"Authorization": "Bearer " + cfg["key"]})
            calls = [item for item in data.get("output", []) if item.get("type") == "web_search_call"]
            if not calls:
                raise ValueError
            return [s["url"] for item in calls
                    for s in item.get("action", {}).get("sources", []) if s.get("url")]
        if cfg["provider"] == "anthropic":
            import anthropic
            with anthropic.Anthropic(api_key=cfg["key"], timeout=60, max_retries=0) as client:
                # Dynamic filtering (20260209) where the model has it; older models reject it with a 400 and get the basic tool.
                for tool in ("web_search_20260209", "web_search_20250305"):
                    try:
                        message = client.messages.create(model=cfg["model"], max_tokens=2000,
                            system="Search once. The app reads the search-tool results directly. After searching, reply only Done.",
                            output_config={"effort": "low"},
                            tools=[{"type": tool, "name": "web_search", "max_uses": 1}],
                            messages=[{"role": "user", "content": query}])
                        break
                    except anthropic.BadRequestError:
                        if tool == "web_search_20250305":
                            raise
            # Complete tool results remain usable if the subsequent prose is cut short or another search hits the limit.
            blocks = [b for b in message.content if b.type == "web_search_tool_result" and isinstance(b.content, list)]
            if not blocks:
                raise ValueError
            return [r.url for b in blocks for r in b.content if r.type == "web_search_result"]
        return []
    except Exception:
        raise ValueError("Web search unavailable for this model or key. Direct sources were still checked. Add a Brave key or choose a search-capable model.") from None


class PublicReader:
    def __init__(self):
        self.playwright = self.browser = self.context = None

    def close(self):
        try:
            if self.browser:
                self.browser.close()
        finally:
            if self.playwright:
                self.playwright.stop()

    def read(self, url, listing=False):
        url = public_url(url)
        if urlsplit(url).hostname in SPA_HOSTS:
            return self.render(url)
        try:
            with build_opener(PublicRedirect()).open(Request(url, headers={"User-Agent": "Intern-Bot Opportunity Scout/1.0"}), timeout=20) as response:
                raw = response.read(MAX_BYTES + 1)
                final = public_url(response.url)
                content_type = response.headers.get_content_type()
                encoding = response.headers.get_content_charset() or "utf-8"
        except HTTPError as exc:
            # Bot shields (EDBI, Enterprise Singapore) refuse any non-browser client; a real browser usually passes.
            if exc.code in {403, 429}:
                return self.render(url)
            raise
        if len(raw) > MAX_BYTES or content_type not in {"text/html", "application/json", "text/plain"}:
            raise ValueError("Page is too large or uses an unsupported document format.")
        html = raw.decode(encoding, errors="replace")
        if content_type == "application/json":
            return final, html, re.findall(r'https://[^\s"<>]+', html)
        parser = PostingHTML(final)
        parser.feed(html)
        links = list(dict.fromkeys(parser.links))
        if urlsplit(final).hostname in SPA_HOSTS or len(parser.text) < 300 or re.search(r"enable javascript|javascript is (?:required|disabled)", parser.text, re.I) or (listing and not any(JOB_LINK.search(u) for u in links)):
            return self.render(final)
        return final, parser.text[:28000], links

    def render(self, url):
        from playwright.sync_api import sync_playwright
        if not self.context:
            self.playwright = sync_playwright().start()
            self.browser = self.playwright.chromium.launch(headless=False)
            self.context = self.browser.new_context(accept_downloads=False)
            self.context.route("**/*", self.route)
        page = self.context.new_page()
        try:
            response = page.goto(url, wait_until="domcontentloaded", timeout=25000)
            # Give client-rendered public boards a bounded chance to populate.
            page.wait_for_timeout(2000)
            if response and response.status >= 400:
                raise ValueError("The public page could not be opened.")
            final = public_url(page.url)
            parser = PostingHTML(final)
            parser.feed(page.content())
            if len(parser.text) < 100 or re.search(r"access denied|verify you are human|checking your browser|sign in to view", parser.text, re.I):
                raise ValueError("This public page is blocked or requires sign-in.")
            return final, parser.text[:28000], list(dict.fromkeys(parser.links))
        finally:
            page.close()

    @staticmethod
    def route(route):
        try:
            public_url(route.request.url)
            if route.request.method != "GET":
                route.abort()
            else:
                route.continue_()
        except Exception:
            route.abort()
