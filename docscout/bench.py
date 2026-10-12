"""``docscout bench-llm``: measure LLM speed and memory on this machine.

Runs a few reviews on built-in sample repos and recommends ``max_candidates`` so the
daily LLM step fits a time budget. Close memory-hungry apps first on small machines.
"""

from __future__ import annotations

import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from docscout.llm.base import LLMClient, LLMError, LLMUnavailable, RepoContext, Review, review_with_retry

SAMPLES = [
    RepoContext(
        full_name="example-org/uptime-api",
        description="Self-hosted uptime monitoring with a REST API, webhooks and status pages.",
        topics=["self-hosted", "monitoring", "rest-api"],
        language="Go",
        wanted_api_types=["REST"],
        readme_excerpt=(
            "# Uptime\nSelf-hosted uptime monitoring.\n\n## Run\n`docker compose up`\n\n"
            "## API\nGET /api/checks\nPOST /api/checks\nGET /api/checks/{id}/results\n"
        ),
        findings=["21/38 operations have no description", "No request or response examples", "No 4xx responses"],
        issues=["Document webhook payloads (help wanted)"],
    ),
    RepoContext(
        full_name="example-org/spec-codegen",
        description="Generate type-safe TypeScript clients from OpenAPI specifications.",
        topics=["openapi", "codegen", "typescript"],
        language="TypeScript",
        wanted_api_types=["REST"],
        readme_excerpt="# spec-codegen\nnpx spec-codegen ./openapi.yaml --out ./client\n",
        findings=["Spec found only under examples/"],
    ),
    RepoContext(
        full_name="example-org/recipes",
        description="Recipe manager and meal planner for your home server.",
        topics=["self-hosted", "recipes"],
        language="Python",
        wanted_api_types=["REST"],
        readme_excerpt="# Recipes\nA web app for recipes. It has an API at /api/v1 (see the wiki).\n",
        findings=["No OpenAPI spec", "README mentions an API but documents no endpoints"],
    ),
]


@dataclass
class BenchResult:
    seconds: list[float] = field(default_factory=list)
    reviews: list[Review] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    model_bytes: int | None = None
    min_available_bytes: int | None = None
    unavailable: str | None = None  # setup problem that stopped the benchmark, with its fix

    @property
    def avg_seconds(self) -> float | None:
        return sum(self.seconds) / len(self.seconds) if self.seconds else None

    def recommended_max_candidates(self, budget_minutes: float = 10) -> int | None:
        if not self.avg_seconds:
            return None
        return max(1, min(30, int(budget_minutes * 60 / self.avg_seconds)))


def _mem_available() -> int | None:
    meminfo = Path("/proc/meminfo")
    if not meminfo.is_file():
        return None
    for line in meminfo.read_text().splitlines():
        if line.startswith("MemAvailable:"):
            return int(line.split()[1]) * 1024
    return None


def run(client: LLMClient, runs: int = 3, readme_chars: int = 1500) -> BenchResult:
    result = BenchResult()
    lowest: list[int] = []
    stop = threading.Event()

    def watch_memory() -> None:
        while not stop.is_set():
            value = _mem_available()
            if value is not None:
                lowest.append(value)
            stop.wait(0.5)

    watcher = threading.Thread(target=watch_memory, daemon=True)
    watcher.start()
    try:
        for ctx in SAMPLES[:runs]:
            start = time.monotonic()
            try:
                review = review_with_retry(client, ctx, readme_chars)
            except LLMUnavailable as exc:
                result.unavailable = str(exc)
                break
            except LLMError as exc:
                result.errors.append(f"{ctx.full_name}: {exc}")
                continue
            result.seconds.append(time.monotonic() - start)
            result.reviews.append(review)
            print(f"  {ctx.full_name}: {result.seconds[-1]:.1f}s -> {review.project_type}/{review.api_style} ({review.confidence:.2f})", file=sys.stderr)
            loaded = getattr(client, "loaded_model_bytes", None)
            if loaded:
                result.model_bytes = loaded() or result.model_bytes
    finally:
        stop.set()
        watcher.join(timeout=2)
        client.unload()
    result.min_available_bytes = min(lowest) if lowest else None
    return result


def format_result(result: BenchResult, client_name: str) -> str:
    gb = 1024**3
    lines = [f"LLM benchmark ({client_name})"]
    if result.unavailable:
        lines.append(f"  The LLM can't be used yet: {result.unavailable}")
        lines.append("  Everything else in DocScout works without it; reports then use code-based results only.")
        return "\n".join(lines)
    if result.seconds:
        lines.append(
            f"  reviews: {len(result.seconds)}, average {result.avg_seconds:.1f}s, "
            f"slowest {max(result.seconds):.1f}s (the first includes loading the model)"
        )
    if result.model_bytes:
        lines.append(f"  model memory: {result.model_bytes / gb:.1f} GB")
    if result.min_available_bytes is not None:
        lines.append(f"  lowest free memory during the run: {result.min_available_bytes / gb:.1f} GB")
    expected = [("serves_api", "rest"), ("api_tooling", None), ("serves_api", "rest")]
    for review, (want_type, want_style) in zip(result.reviews, expected):
        ok = review.project_type == want_type and want_style in (None, review.api_style)
        mark = "ok" if ok else f"expected {want_type}" + (f"/{want_style}" if want_style else "")
        lines.append(f"  - {review.project_type}/{review.api_style} ({mark}); first steps: {len(review.first_steps)}")
    for error in result.errors:
        lines.append(f"  error: {error}")
    rec = result.recommended_max_candidates()
    if rec:
        lines.append(f"  recommended [llm] max_candidates = {rec}  (keeps the daily LLM step near 10 minutes)")
    return "\n".join(lines)
