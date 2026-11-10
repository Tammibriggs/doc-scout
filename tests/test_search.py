"""Searching the website's picks by what the project is about (docscout.hosted.search)."""

from docscout.hosted.search import CATEGORIES, parse, search, suggestions


def pick(name, description="", topics=(), language=None):
    return {"full_name": name, "description": description, "topics": list(topics), "language": language}


def found(picks, query):
    return [p["full_name"] for p in search(picks, query)]


def test_a_kind_of_project_finds_the_words_its_projects_use():
    picks = [
        pick("org/notes", "Notes app", topics=["llm", "self-hosted"]),
        pick("org/bot", "Run a team of bots", topics=["machine-learning"]),
        pick("org/gateway", "An OpenAI-compatible gateway"),
        pick("org/uptime", "Uptime monitoring", topics=["monitoring"]),
    ]
    assert found(picks, "AI") == ["org/notes", "org/bot", "org/gateway"]
    assert found(picks, "machine learning") == ["org/notes", "org/bot", "org/gateway"]  # a naming phrase
    assert found(picks, "llm") == ["org/notes", "org/bot", "org/gateway"]
    assert found(picks, "openai") == ["org/gateway"]  # a specific word finds only itself


def test_plurals_and_longer_words_match():
    picks = [pick("org/pay", "Payments platform"), pick("org/photos", "Photography portfolio"), pick("org/js", "UI", language="JavaScript")]
    assert found(picks, "payment") == ["org/pay"]
    assert found(picks, "photo") == ["org/photos"]  # 5 letters or more: also the start of a word
    assert found(picks, "java") == []  # shorter: the whole word only
    assert found(picks, "javascript") == ["org/js"]


def test_every_word_must_match_and_words_every_pick_shares_are_ignored():
    picks = [pick("org/ai-pay", "AI invoices", topics=["payments"]), pick("org/pay", "Payments"), pick("org/ai", "AI agents")]
    assert found(picks, "ai payments") == ["org/ai-pay"]
    assert found(picks, "payments api") == found(picks, "payments") == ["org/ai-pay", "org/pay"]
    assert found(picks, "the API") == ["org/ai-pay", "org/pay", "org/ai"]  # nothing left to match: everything does


def test_names_topics_and_language_are_searched_and_split_sensibly():
    picks = [
        pick("org/LibreChat", "Talk to your team"),
        pick("org/vault", "Passwords", topics=["self-hosted"]),
        pick("org/server", "Server", language="Go"),
        pick("org/db", "Store data in PostgreSQL"),
    ]
    assert found(picks, "chat") == ["org/LibreChat"]  # the repo's name split at capitals
    assert found(picks, "selfhosted") == found(picks, "self-hosted") == ["org/vault"]
    assert found(picks, "go") == ["org/server"]
    assert found(picks, "postgresql") == ["org/db"]


def test_words_a_project_only_uses_dont_name_its_kind():
    picks = [
        pick("org/crypt", "Cryptography toolkit"),
        pick("org/gw", "AI gateway with streaming responses"),
        pick("org/podcasts", "Podcast app", topics=["postgresql", "docker"]),
        pick("org/admin", "Admin dashboard"),
    ]
    assert found(picks, "blockchain") == []  # "crypto" names it, but only as a whole word
    assert found(picks, "media") == ["org/podcasts"]  # podcasts, not streamed answers
    assert found(picks, "database") == []  # it stores its data in PostgreSQL; it isn't about databases
    assert found(picks, "devops") == []  # it ships a Docker image
    assert found(picks, "analytics") == []


def test_a_phrase_doesnt_run_from_one_part_into_the_next():
    assert found([pick("org/smart", "Contract tools")], "blockchain") == []  # "smart" + "contract" aren't "smart contract"


def test_a_query_is_cut_to_its_length_limit():
    assert len(parse("payments " * 40)) <= 7


def test_suggestions_are_the_biggest_kinds_with_picks():
    picks = [pick("org/a", topics=["llm"]), pick("org/b", topics=["rag"]), pick("org/c", "Invoices"), pick("org/d", "Nothing")]
    assert suggestions(picks) == [("AI", "ai", 2), ("Finance", "finance", 1)]
    assert all(names and names[0] for names, _ in CATEGORIES.values())  # each kind's first word is its search
