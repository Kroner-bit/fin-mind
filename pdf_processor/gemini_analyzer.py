"""
Google AI Studio (Gemini) API integration for quantitative research PDF analysis.
"""

import json
import time
from google import genai
from google.genai import types

from schema import (
    EXPECTED_TOP_LEVEL_KEYS,
    get_empty_schema,
    ASSET_CLASSES,
    BIAS_VALUES,
    CLAIM_DIRECTIONS,
    CLAIM_TYPES,
    CONFIDENCE_VALUES,
    DATA_TYPES,
    DATASET_ACCESS,
    DATA_USE_ROLES,
    DOMAINS,
    EXPERIMENT_TYPES,
    FORMULA_TYPES,
    LATENCY_CLASSES,
    LIVE_FEASIBILITY,
    METHOD_CATEGORIES,
    METRIC_EXAMPLES,
    MODEL_CLASSES,
    MODEL_ORIGINS,
    PAPER_TYPES,
    PRIMARY_DISCIPLINES,
    TRANSFERABILITY_SCORES,
    APPLICABLE_FINANCIAL_AREAS,
    PHENOMENON_KINDS,
    RELATION_TYPES,
    REPRO_CLASSIFICATIONS,
    STATEMENT_TYPES,
    STRATEGY_FAMILIES,
)


# ─── System prompt for Gemini ────────────────────────────────────────────────

def _quoted(values, limit=None):
    """Format a vocabulary list as: "A", "B", "C" (optionally truncated)."""
    items = [f'"{v}"' for v in values[:limit]] if limit else [f'"{v}"' for v in values]
    text = ", ".join(items)
    if limit and len(values) > limit:
        text += ", ..."
    return text


SYSTEM_PROMPT = f"""You are an expert scientific and quantitative research analyst extracting structured knowledge from academic papers into a MULTI-DISCIPLINARY QUANTITATIVE, MATHEMATICAL, SCIENTIFIC, AND FINANCIAL KNOWLEDGE GRAPH.

PAPERS COME FROM DIVERSE DISCIPLINES:
Our research repository contains papers from Quantitative Finance, Econometrics, Computer Science/AI, Mathematics/Statistics, Physics/Complex Systems, and Astrophysics/Cosmology (e.g. galaxies, star clusters, celestial mechanics, stochastic turbulence).
ALL of these papers are valuable: elite quantitative hedge funds and quantitative researchers systematically study natural sciences, astrophysics, and complex systems to discover transferable mathematical models, spatial/temporal clustering algorithms, density estimators, network topologies, power laws, and noise-filtering techniques.

THE FOUR STRUCTURAL PILLARS OF V3 EXTRACTION:
1. ACCURATE SCIENTIFIC DOMAIN CLASSIFICATION:
   Identify the true primary discipline of the paper (cross_domain_transfer.primary_discipline):
   {_quoted(PRIMARY_DISCIPLINES)}
   - If the paper is about astrophysics, galaxies, star clusters, astronomy, celestial mechanics, fluid dynamics, or pure physics:
     * Set cross_domain_transfer.is_direct_finance = false.
     * Set cross_domain_transfer.primary_discipline to the genuine scientific field (e.g. "AstrophysicsAndCosmology").
     * Do NOT invent fake financial assets, stocks, or exchanges: leave markets.asset_classes = [].
     * Do NOT invent fake trading strategies: set modules.strategy.present = false.

2. CROSS-DOMAIN TRANSFER TO QUANTITATIVE TRADING (cross_domain_transfer):
   FOR EVERY PAPER (especially non-finance or foundational quantitative papers), analyze how its scientific methods, mathematical formalisms, spatial/temporal dynamics, or empirical models could inspire or be adapted into quantitative trading, market microstructure, risk modeling, or algorithmic strategies!
   - transferability_score: exactly one of {_quoted(TRANSFERABILITY_SCORES)}.
   - analogies_to_finance:
     * scientific_concept: What the paper studies in its own scientific domain (e.g. "Identification and luminosity distribution of star clusters in NGC 1311 using spatial resolution and spectral energy distribution against noisy background").
     * financial_market_analogy: The analogous market or quantitative phenomenon (e.g. "Clustering of limit order book liquidity, detecting institutional block trade clusters, or spatial/topological grouping of co-moving equities in multi-asset universes").
   - transferable_methodologies: List of concrete mathematical tools, statistical algorithms, point processes, or estimators from the paper that can be ported to finance.
   - trading_ideas: At least 1 concrete, creative quantitative trading or market research idea inspired by the paper's methods (with title, testable hypothesis, suggested implementation, and applicable financial areas from {_quoted(APPLICABLE_FINANCIAL_AREAS)}).

3. STRATEGY IS A STRICTLY GATED MODULE:
   Set modules.strategy.present = true ONLY if the paper itself is a finance paper proposing an implementable trading system: concrete signal generation, explicit entry/exit rules, order placement, or portfolio construction rules. For non-finance or foundational science papers, present = false.

4. EXPERIMENTS OWN RESULTS & CLAIMS OWN FINDINGS:
   Every reported number belongs to an experiment in experiments[] (a backtest is ONE experiment type among many; observational studies, regressions, and simulations are first-class). Extract mathematical formulas (formulas[]) and formal statements/theorems (statements[]) with equal rigor.

PAPER SCOPE (classification.in_scope):
- true for any paper concerning finance/economics, OR containing quantitative, mathematical, statistical, computational, physical, or astronomical research with potential methodological/transferable value.
- false only for completely non-quantitative, non-scientific content (humanities, pure opinion pieces, editorial notes).

PAPER TYPE (document.paper_type) - exactly one of:
{_quoted(PAPER_TYPES)}
(For observational astronomy/astrophysics or empirical physical measurement catalogues, choose "Observation" or "EmpiricalStudy").

DOMAINS (classification.domains, all that apply):
{_quoted(DOMAINS)}

STRATEGY FAMILY (modules.strategy.family) - only if modules.strategy.present=true:
{_quoted(STRATEGY_FAMILIES)}

EXPERIMENT TYPES (experiments[].type):
{_quoted(EXPERIMENT_TYPES)}

RESULTS (experiments[].results[]):
- metric: canonical snake_case name, e.g. {_quoted(METRIC_EXAMPLES, 12)}
- value: EXACTLY as printed (never round, never invent);

CLAIMS (claims[]):
- type: {_quoted(CLAIM_TYPES)}; direction: {_quoted(CLAIM_DIRECTIONS)}.

FORMULAS (formulas[]):
- type: {_quoted(FORMULA_TYPES)}; LaTeX formula with variable mappings.

STATEMENTS (statements[]):
- type: {_quoted(STATEMENT_TYPES)}; theorem/lemma/definition structure.

ENTITIES (entities):
- models: name, model_class ({_quoted(MODEL_CLASSES)}), origin ({_quoted(MODEL_ORIGINS)}).
- methods: name, category ({_quoted(METHOD_CATEGORIES)}), origin.
- phenomena: name, kind ({_quoted(PHENOMENON_KINDS)}).

REPRODUCIBILITY (reproducibility):
- classification ({_quoted(REPRO_CLASSIFICATIONS)}).

CRITICAL RULES:
1. NEVER hallucinate or invent data. Missing = null or "not_specified". NEVER invent fake trading strategies or fake asset classes for non-finance papers.
2. For non-finance papers (astrophysics, physics, pure math), preserve their authentic scientific identity and extract their transferable quantitative value in cross_domain_transfer.
3. Extract ALL numerical results from tables and text.
4. publication_year: from publication venue/date, NOT PDF creation date.
5. Return ONLY valid JSON, no markdown fences, no explanation."""


def build_analysis_prompt(pdf_data: dict) -> str:
    """Build the user prompt with extracted PDF content."""
    schema_template = json.dumps(get_empty_schema(), indent=2)

    prompt = f"""Analyze the following scientific / quantitative research paper and fill in the V3 JSON schema below.

FILE: {pdf_data['file_name']}
PAGES: {pdf_data['page_count']}

PDF METADATA:
Title: {pdf_data['pdf_metadata'].get('title', 'N/A')}
Author: {pdf_data['pdf_metadata'].get('author', 'N/A')}
Creation Date: {pdf_data['pdf_metadata'].get('creation_date', 'N/A')}

EXTRACTED TABLES:
{pdf_data['tables_text']}

FULL PAPER TEXT:
{pdf_data['full_text']}

---

JSON SCHEMA TO FILL (return ONLY the filled JSON):
{schema_template}

Remember:
- Set document.file_name to "{pdf_data['file_name']}"
- Accurately identify primary_discipline (e.g. AstrophysicsAndCosmology, PhysicsAndComplexSystems, QuantitativeFinance, etc.)
- If non-finance: do NOT invent fake trading strategies or fake stock markets; fill cross_domain_transfer with financial market analogies and transferable quantitative ideas
- Apply THE STRATEGY GATE strictly: modules.strategy.present=true ONLY for a real, implementable trading system
- Extract ALL reported results, claims, formulas, and entities from tables and text
- Return ONLY valid JSON, no markdown fences"""

    return prompt


class DailyQuotaExhaustedError(Exception):
    """Raised when Google AI Studio 24-hour daily quota limit (RPD, e.g. 500) is exceeded."""
    def __init__(self, message: str, limit: int = 500):
        super().__init__(message)
        self.limit = limit


def extract_retry_delay(error: Exception) -> float | None:
    """Extract retry delay in seconds from Gemini API 429 quota exhaustion message."""
    import re
    error_str = str(error)
    match = re.search(r"retry\s+in\s+([0-9.]+)\s*s", error_str, re.IGNORECASE)
    if match:
        try:
            return float(match.group(1))
        except ValueError:
            pass
    match = re.search(r"['\"]retryDelay['\"]\s*:\s*['\"]([0-9.]+)\s*s['\"]", error_str, re.IGNORECASE)
    if match:
        try:
            return float(match.group(1))
        except ValueError:
            pass
    return None


def is_daily_quota_error(error: Exception) -> bool:
    """Check if the error is Google's 24-hour daily quota exhaustion (RPD)."""
    error_str = str(error).lower()

    # Exclude per-minute limits (TPM: tokens per minute, RPM: requests per minute)
    if "perminute" in error_str or "input_token_count" in error_str or "token_count" in error_str:
        return False

    daily_indicators = [
        "generaterequestsperday",
        "generate_content_free_tier_requests",
    ]
    for ind in daily_indicators:
        if ind in error_str:
            return True

    # Strict regex check for limit: 500 requests
    import re
    if re.search(r"limit:\s*500\b", error_str) and "request" in error_str:
        return True
    if re.search(r"['\"]quotavalue['\"]\s*:\s*['\"]500['\"]", error_str) and "day" in error_str:
        return True

    return False


def is_demand_spike_error(error: Exception) -> bool:
    """Check if the error is a temporary demand spike / 503 UNAVAILABLE on Gemini servers."""
    error_str = str(error).lower()
    return "503" in error_str or "unavailable" in error_str or "high demand" in error_str or "spikes in demand" in error_str


def is_per_minute_quota_error(error: Exception) -> bool:
    """Check if the error is a temporary per-minute rate limit (TPM/RPM 429)."""
    error_str = str(error).lower()
    if is_daily_quota_error(error):
        return False
    return (
        "perminute" in error_str or
        "input_token_count" in error_str or
        "250000" in error_str or
        ("429" in error_str and "resource_exhausted" in error_str) or
        "rate limit" in error_str
    )


class GeminiAnalyzer:
    """Handles communication with Google AI Studio Gemini API with retry and fallback."""

    # HTTP/API error codes that are retryable
    RETRYABLE_CODES = {429, 500, 502, 503, 504}

    def __init__(self, api_key: str, model_name: str = "gemini-2.0-flash",
                 fallback_models: list[str] = None,
                 max_retries: int = 5, initial_delay: float = 10,
                 max_delay: float = 120, backoff_multiplier: float = 2):
        self.api_key = api_key
        self.model_name = model_name
        self.fallback_models = fallback_models or []
        self.max_retries = max_retries
        self.initial_delay = initial_delay
        self.max_delay = max_delay
        self.backoff_multiplier = backoff_multiplier
        self.client = genai.Client(api_key=api_key)

    def _get_model_sequence(self) -> list[str]:
        """Get the ordered list of models to try: primary + fallbacks."""
        models = [self.model_name]
        for fb in self.fallback_models:
            if fb not in models:
                models.append(fb)
        return models

    def _is_retryable_error(self, error: Exception) -> bool:
        """Check if an error is retryable (503, 429, etc.)."""
        error_str = str(error)
        for code in self.RETRYABLE_CODES:
            if str(code) in error_str:
                return True
        retryable_keywords = ["UNAVAILABLE", "overloaded", "high demand",
                              "rate limit", "quota", "RESOURCE_EXHAUSTED",
                              "capacity", "temporarily"]
        return any(kw.lower() in error_str.lower() for kw in retryable_keywords)

    def _call_api(self, model: str, user_prompt: str,
                  on_status: callable = None) -> tuple[dict, int, int, int]:
        """Make a single API call to the specified model. No retries here."""
        if on_status:
            on_status(f"Calling model: {model}...")

        response = self.client.models.generate_content(
            model=model,
            contents=user_prompt,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                temperature=0.1,
                max_output_tokens=65536,
                response_mime_type="application/json",
            ),
        )

        # Extract token usage
        prompt_tokens = 0
        completion_tokens = 0
        total_tokens = 0

        if hasattr(response, 'usage_metadata') and response.usage_metadata:
            prompt_tokens = getattr(response.usage_metadata, 'prompt_token_count', 0) or 0
            completion_tokens = getattr(response.usage_metadata, 'candidates_token_count', 0) or 0
            total_tokens = getattr(response.usage_metadata, 'total_token_count', 0) or 0

        if total_tokens == 0:
            total_tokens = prompt_tokens + completion_tokens

        if on_status:
            on_status(f"Response from {model}. Tokens: {prompt_tokens:,} in / "
                      f"{completion_tokens:,} out / {total_tokens:,} total")

        # Parse JSON
        raw_text = response.text.strip()

        # Remove markdown code fences if present
        if raw_text.startswith("```"):
            lines = raw_text.split("\n")
            if lines[-1].strip() == "```":
                lines = lines[1:-1]
            else:
                lines = lines[1:]
            raw_text = "\n".join(lines)

        result = json.loads(raw_text)

        # Validate top-level keys
        expected_keys = EXPECTED_TOP_LEVEL_KEYS

        missing_keys = expected_keys - set(result.keys())
        if missing_keys:
            if on_status:
                on_status(f"Warning: Missing top-level keys: {missing_keys}")
            full_schema = get_empty_schema()
            for key in missing_keys:
                result[key] = full_schema[key]

        return result, prompt_tokens, completion_tokens, total_tokens

    def _extract_retry_delay(self, error: Exception) -> float | None:
        """Extract retry delay in seconds from Gemini API 429 quota exhaustion message."""
        import re
        error_str = str(error)
        match = re.search(r"retry\s+in\s+([0-9.]+)\s*s", error_str, re.IGNORECASE)
        if match:
            try:
                return float(match.group(1))
            except ValueError:
                pass
        match = re.search(r"['\"]retryDelay['\"]\s*:\s*['\"]([0-9.]+)\s*s['\"]", error_str, re.IGNORECASE)
        if match:
            try:
                return float(match.group(1))
            except ValueError:
                pass
        return None

    def analyze_paper(self, pdf_data: dict,
                      on_status: callable = None,
                      should_stop: callable = None) -> tuple[dict, int, int, int]:
        """
        Send extracted PDF data to Gemini for analysis with retry and fallback.

        Args:
            pdf_data: Extracted PDF content dict
            on_status: Callback for status messages
            should_stop: Callable returning True if processing should abort

        Returns:
            tuple of (json_result, prompt_tokens, completion_tokens, total_tokens)
        """
        if on_status:
            on_status(f"Building analysis prompt for {pdf_data['file_name']}...")

        user_prompt = build_analysis_prompt(pdf_data)

        estimated_tokens = len(user_prompt) // 4
        if on_status:
            on_status(f"Estimated input: ~{estimated_tokens:,} tokens")

        models = self._get_model_sequence()
        last_error = None

        for model_idx, model in enumerate(models):
            if should_stop and should_stop():
                raise InterruptedError("Processing stopped by user")

            delay = self.initial_delay
            model_label = f"{model}" + (" (fallback)" if model_idx > 0 else " (primary)")

            for attempt in range(1, self.max_retries + 1):
                if should_stop and should_stop():
                    raise InterruptedError("Processing stopped by user")

                try:
                    if on_status:
                        attempt_info = f"[Attempt {attempt}/{self.max_retries}]" if attempt > 1 else ""
                        on_status(f"Sending to {model_label} {attempt_info}...")

                    result, pt, ct, tt = self._call_api(model, user_prompt, on_status)

                    # Ensure file_name is set
                    if result.get("document", {}).get("file_name") is None:
                        result["document"]["file_name"] = pdf_data["file_name"]

                    if on_status and model_idx > 0:
                        on_status(f"[OK] Succeeded with fallback model: {model}")

                    return result, pt, ct, tt

                except json.JSONDecodeError as e:
                    last_error = e
                    if on_status:
                        on_status(f"[WARN] Invalid JSON from {model}, attempt {attempt}: {e}")
                    # JSON errors are retryable (model might produce valid JSON next time)
                    if attempt < self.max_retries:
                        if on_status:
                            on_status(f"  Retrying in {delay:.0f}s...")
                        self._interruptible_sleep(delay, should_stop)
                        delay = min(delay * self.backoff_multiplier, self.max_delay)
                    continue

                except InterruptedError:
                    raise

                except Exception as e:
                    last_error = e
                    # 1. 24-hour Daily Quota (RPD) - Fail fast to switch key / trigger 24h countdown
                    if is_daily_quota_error(e):
                        if on_status:
                            on_status(f"[ERROR] Napi kvóta elérve (500 RPD): {e}")
                        raise DailyQuotaExhaustedError(str(e), limit=500)

                    # 2. Demand Spike (503 UNAVAILABLE / High Demand)
                    if is_demand_spike_error(e):
                        spike_wait = max(delay, 15.0)
                        if on_status:
                            on_status(f"[WARN] Gemini modell átmenetileg leterhelt (503 Demand Spike), "
                                      f"próbálkozás {attempt}/{self.max_retries}. Várakozás {spike_wait:.0f}s...")
                        if attempt < self.max_retries:
                            self._interruptible_sleep(spike_wait, should_stop)
                            delay = min(spike_wait * self.backoff_multiplier, self.max_delay)
                            continue
                        else:
                            if on_status:
                                on_status(f"  Max retries reached for {model} during demand spike.")
                            break  # Move to fallback model

                    # 3. Per-minute Quota Gate (429 TPM/RPM) or generic retryable
                    if is_per_minute_quota_error(e) or self._is_retryable_error(e):
                        google_delay = self._extract_retry_delay(e)
                        if google_delay is not None:
                            wait_time = max(google_delay + 2.0, 5.0)
                            if on_status:
                                on_status(f"[WARN] Perces kvótakorlát (TPM/RPM plafon: 429), Google várakozás: {google_delay:.1f}s. Várakozás {wait_time:.1f}s...")
                        else:
                            wait_time = max(delay, 15.0)
                            if on_status:
                                on_status(f"[WARN] Átmeneti perces kvótakorlát (TPM/RPM: 429), "
                                          f"próbálkozás {attempt}/{self.max_retries}. Várakozás {wait_time:.0f}s...")

                        if attempt < self.max_retries:
                            self._interruptible_sleep(wait_time, should_stop)
                            delay = min(max(delay, wait_time) * self.backoff_multiplier, self.max_delay)
                            continue
                        else:
                            if on_status:
                                on_status(f"  Max retries reached for {model}.")
                            break  # Move to next fallback model
                    else:
                        # Check if it's a model-not-found error (skip to fallback)
                        error_str = str(e)
                        is_model_not_found = ("404" in error_str or
                                              "NOT_FOUND" in error_str or
                                              "no longer available" in error_str or
                                              "not found" in error_str.lower())

                        if is_model_not_found and model_idx < len(models) - 1:
                            if on_status:
                                on_status(f"[WARN] Model {model} not available, "
                                          f"skipping to next fallback...")
                            last_error = e
                            break  # Move to next fallback model
                        else:
                            # Truly non-retryable error, fail
                            if on_status:
                                on_status(f"[FAIL] Non-retryable error from {model}: {e}")
                            raise

            # All retries exhausted for this model, try next fallback
            if model_idx < len(models) - 1:
                next_model = models[model_idx + 1]
                if on_status:
                    on_status(f"[SWITCH] Switching to fallback model: {next_model}")

        # All models and retries exhausted
        if last_error and is_daily_quota_error(last_error):
            raise DailyQuotaExhaustedError(str(last_error), limit=500)
        raise RuntimeError(
            f"All models failed after retries. Models tried: {models}. "
            f"Last error: {last_error}"
        )

    def _interruptible_sleep(self, seconds: float, should_stop: callable = None):
        """Sleep that can be interrupted by should_stop."""
        end_time = time.time() + seconds
        while time.time() < end_time:
            if should_stop and should_stop():
                raise InterruptedError("Processing stopped by user")
            time.sleep(min(1, end_time - time.time()))

