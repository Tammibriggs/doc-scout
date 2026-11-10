"""Search the website's picks by what the project is about (8 Nov): "AI", "payments", "Go".

The search runs in memory over each pick's name, description, GitHub topics and language, the
only fields the website asks Atlas for when searching (about 350 bytes a pick; hosted.atlas).
Gemma's note isn't searched: it's written about the docs, and a search should match what the
project says about itself.

- Every word must match (``ai payments`` finds AI projects about payments).
- Plurals match simply ("payment" finds "payments"), and a word of 5 letters or more also
  matches longer words that start with it ("photo" finds "photography"; "java" doesn't find
  "javascript").
- A word that names a kind of project expands to the words such projects use: "ai" also finds
  "llm", "rag" and "machine-learning" (:data:`CATEGORIES`). A specific word, such as "rag",
  finds only itself.
- Words every pick shares ("api", "rest", "project") are ignored.

Everything goes through :func:`search`, so moving to Atlas Search later replaces only that.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

MAX_QUERY = 60
PREFIX_FROM = 5  # a typed word this long also matches longer words that start with it

# Each kind of project: the words that name it, then the words its projects use. Typing a
# naming word finds any of them; typing one of the other words finds only that word. Words a
# project uses rather than is about are left out, tried on the 92 picks of 8 Nov: "docker" (most
# self-hosted apps ship an image), database engines ("postgresql": the app stores its data
# there), "dashboard" (any admin page), "raspberry pi" (where it runs), bare "streaming" (an
# AI gateway's streamed answers), "orchestration" (AI agents), "image" (Docker image) and bare
# "agent" (monitoring agents). Typed on its own, any of them still finds itself.
CATEGORIES: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "AI": (
        ("ai", "artificial intelligence", "llm", "llms", "large language model", "genai", "generative ai",
         "machine learning", "ml", "deep learning"),
        ("gpt", "chatgpt", "openai", "anthropic", "claude", "gemini", "gemma", "ollama", "llama", "mistral",
         "huggingface", "hugging face", "rag", "retrieval augmented generation", "ai agent", "ai agents", "agentic",
         "multi agent", "mcp", "model context protocol", "embedding", "embeddings", "nlp", "natural language processing",
         "chatbot", "chatbots", "copilot", "inference", "neural network", "computer vision", "langchain",
         "llamaindex", "vector database", "vector search", "speech to text", "text to speech"),
    ),
    "Blockchain": (
        ("blockchain", "web3", "crypto", "cryptocurrency", "cryptocurrencies"),
        ("ethereum", "bitcoin", "solana", "stellar", "soroban", "defi", "nft", "nfts", "smart contract",
         "smart contracts", "dapp", "dapps", "evm", "polkadot", "hyperledger", "lightning network", "onchain", "on chain"),
    ),
    "Finance": (
        ("finance", "financial", "fintech", "money", "payment", "payments", "billing", "accounting", "banking"),
        ("invoice", "invoices", "invoicing", "checkout", "bank", "budget", "budgeting", "expense", "expenses",
         "ledger", "bookkeeping", "stripe", "paypal", "tax", "trading", "personal finance", "open banking"),
    ),
    "E-commerce": (
        ("ecommerce", "e commerce", "commerce", "shop", "shopping", "retail"),
        ("storefront", "shopping cart", "marketplace", "checkout", "inventory", "point of sale", "woocommerce",
         "shopify", "magento", "payment", "payments"),
    ),
    "DevOps": (
        ("devops", "infrastructure", "infra", "platform engineering", "sre"),
        ("kubernetes", "k8s", "helm", "terraform", "ansible", "ci cd", "cicd", "continuous integration",
         "continuous delivery", "continuous deployment", "gitops", "paas", "serverless", "container orchestration",
         "cloud native", "iac", "infrastructure as code"),
    ),
    "Monitoring": (
        ("monitoring", "observability"),
        ("metrics", "uptime", "alerting", "alerts", "logging", "logs", "log management", "tracing", "apm",
         "status page", "prometheus", "grafana", "opentelemetry", "telemetry", "incident management"),
    ),
    "Security": (
        ("security", "cybersecurity", "infosec", "auth", "authentication", "identity"),
        ("authorization", "oauth", "oauth2", "oidc", "openid", "sso", "single sign on", "iam", "access control",
         "rbac", "password manager", "passkey", "passkeys", "2fa", "two factor", "mfa", "totp", "secrets management",
         "vulnerability", "vulnerabilities", "pentest", "penetration testing", "firewall", "vpn", "encryption",
         "zero trust", "siem", "waf", "keycloak", "jwt", "ldap"),
    ),
    "Messaging": (
        ("messaging", "chat", "communication"),
        ("messenger", "instant messaging", "sms", "telegram", "whatsapp", "discord", "slack", "xmpp", "irc",
         "push notification", "push notifications", "notification", "notifications"),
    ),
    "Email": (
        ("email", "e mail", "mail"),
        ("smtp", "imap", "newsletter", "newsletters", "mailing list", "inbox", "mailbox", "mail server"),
    ),
    "Media": (
        ("media", "multimedia"),
        ("video", "videos", "audio", "music", "photo", "photos", "picture", "pictures", "gallery", "video streaming",
         "media streaming", "music streaming", "live streaming",
         "podcast", "podcasts", "movie", "movies", "film", "tv", "jellyfin", "plex", "youtube", "media server"),
    ),
    "CMS": (
        ("cms", "content management", "blog", "blogging"),
        ("headless cms", "wiki", "website builder", "static site", "publishing", "knowledge base"),
    ),
    "Databases": (
        ("database", "databases", "db"),
        ("nosql", "key value store", "time series database", "graph database", "vector database", "query engine"),
    ),
    "Analytics": (
        ("analytics",),
        ("business intelligence", "web analytics", "product analytics", "data visualization"),
    ),
    "IoT": (
        ("iot", "internet of things", "home automation", "smart home"),
        ("home assistant", "homeassistant", "mqtt", "zigbee", "z wave", "sensor", "sensors", "esp32", "arduino"),
    ),
    "Healthcare": (
        ("healthcare", "health care", "medical"),
        ("fhir", "ehr", "emr", "hospital", "clinic", "patient", "patients", "hl7", "telemedicine", "wearable", "wearables"),
    ),
    "Education": (
        ("education", "edtech", "elearning", "e learning"),
        ("lms", "learning management", "course", "courses", "school", "schools", "student", "students", "teacher",
         "teachers", "classroom", "quiz", "moodle"),
    ),
    "Maps": (
        ("maps", "gis", "geospatial", "location"),
        ("map", "openstreetmap", "osm", "geocoding", "gps", "geolocation"),
    ),
    "Productivity": (
        ("productivity",),
        ("todo", "to do", "task management", "project management", "kanban", "calendar", "notes", "note taking",
         "bookmarks", "time tracking"),
    ),
    "Storage": (
        ("storage", "file storage", "file sharing", "cloud storage", "backup", "backups"),
        ("s3", "object storage", "file sync", "nextcloud", "webdav"),
    ),
}

IGNORED = {"a", "an", "and", "or", "the", "for", "of", "in", "on", "to", "with", "api", "rest", "project", "app"}
_NO_STEM = {"news", "ios", "aws", "dns", "cms", "sms", "gis", "nas"}  # an "s" that isn't a plural
_WORD = re.compile(r"[a-z0-9]+")
_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")


def _stem(word: str) -> str:
    """A plural's singular, roughly: the same rule on both sides is what matters."""
    if word in _NO_STEM:
        return word
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 3 and word.endswith("s") and not word.endswith(("ss", "us", "is")):
        return word[:-1]
    return word


def _words(text: str) -> list[str]:
    return [_stem(w) for w in _WORD.findall(text.lower())]


def _phrase(text: str) -> str:
    return " ".join(_words(text))


# A naming word (as stemmed words) -> every word of the kinds it names
_NAMES: dict[str, set[str]] = {}
for _names, _terms in CATEGORIES.values():
    for _name in _names:
        _NAMES.setdefault(_phrase(_name), set()).update(_phrase(t) for t in (*_names, *_terms))
_LONGEST = max(len(name.split()) for name in _NAMES)


class _Text:
    """A pick's searchable words, as one string for phrases and a set for prefixes."""

    def __init__(self, pick: dict[str, Any]) -> None:
        name = str(pick.get("full_name") or "")
        topics = [str(t) for t in pick.get("topics") or []]
        parts = [name, str(pick.get("description") or ""), str(pick.get("language") or ""), *topics]
        # The repo's name split at capitals (LibreChat -> Libre Chat, OpenAI -> Open AI); only the
        # name, since elsewhere it would turn JavaScript into "java"
        parts.append(_CAMEL.sub(" ", name.rsplit("/", 1)[-1]))
        parts += [re.sub(r"[^a-z0-9]", "", t.lower()) for t in topics]  # self-hosted -> selfhosted
        # "|" keeps a phrase from running from one part into the next
        self.text = " " + " | ".join(" ".join(_words(part)) for part in parts) + " "
        self.words = set(self.text.split())

    def has(self, phrase: str, prefix: bool) -> bool:
        if f" {phrase} " in self.text:
            return True
        return prefix and any(w.startswith(phrase) for w in self.words)


def parse(query: str) -> list[list[tuple[str, bool]]]:
    """What a query asks for: one entry per word or naming phrase, each a list of (phrase,
    prefix allowed) of which one must be in the pick."""
    words = [w for w in _words(query[:MAX_QUERY]) if w not in IGNORED]
    needs: list[list[tuple[str, bool]]] = []
    i = 0
    while i < len(words):
        for n in range(min(_LONGEST, len(words) - i), 0, -1):
            name = " ".join(words[i : i + n])
            if name in _NAMES:
                needs.append([(term, False) for term in sorted(_NAMES[name])])
                i += n
                break
        else:
            needs.append([(words[i], len(words[i]) >= PREFIX_FROM)])
            i += 1
    return needs


def search(picks: Iterable[dict[str, Any]], query: str) -> list[dict[str, Any]]:
    """The picks that match every word of ``query``, in their order."""
    needs = parse(query)
    found = []
    for pick in picks:
        text = _Text(pick)
        if all(any(text.has(phrase, prefix) for phrase, prefix in need) for need in needs):
            found.append(pick)
    return found


def suggestions(picks: list[dict[str, Any]], limit: int = 4) -> list[tuple[str, str, int]]:
    """The kinds of project with the most picks: (label, query, count), for an empty result."""
    counts = [(label, names[0], len(search(picks, names[0]))) for label, (names, _) in CATEGORIES.items()]
    return sorted((c for c in counts if c[2]), key=lambda c: -c[2])[:limit]
