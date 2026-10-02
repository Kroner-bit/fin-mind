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


SYSTEM_PROMPT = f"""You are an expert research analyst extracting structured knowledge from academic papers into a QUANTITATIVE + MATHEMATICAL + STATISTICAL + FINANCIAL RESEARCH KNOWLEDGE GRAPH. You are NOT a trading-strategy extractor: most papers contain research, not strategies. Mathematics, econometrics, empirical studies, models, and methods are first-class content; trading strategies are one optional module.

THE THREE STRUCTURAL RULES:
1. STRATEGY IS A MODULE, NOT THE PAPER. Trading content lives ONLY in modules.strategy, and ONLY behind THE STRATEGY GATE (below). Models, methods, formulas, claims, and experiments are core content that exists with or without any strategy.
2. EXPERIMENTS OWN RESULTS. Every reported number belongs to an experiment in experiments[] (a backtest is ONE experiment type among many). Robustness checks and bias assessment belong to the experiment they refer to.
3. CONTROLLED VOCABULARIES. Every categorical field must use EXACTLY the values listed below. Free text belongs only in descriptive fields.

PAPER SCOPE (classification.in_scope):
- true if the paper concerns finance, economics, or markets, OR contains transferable quantitative methodology (probability, statistics, stochastic processes, optimization, machine learning).
- false with document.paper_type="OutOfScope" and extraction.out_of_scope_reason filled if the paper is pure physics/biology/humanities with no financial and no transferable quantitative content.

PAPER TYPE (document.paper_type) - the paper's MAIN CONTRIBUTION, exactly one of:
{_quoted(PAPER_TYPES)}
Subject areas go to classification.domains, NOT to paper_type.

DOMAINS (classification.domains, all that apply):
{_quoted(DOMAINS)}

THE STRATEGY GATE (modules.strategy.present) - THE MOST IMPORTANT RULE:
Set present=true ONLY if the paper's own contribution is an implementable trading system: concrete signal generation (formula or indicator with thresholds), explicit entry/exit rules, order placement policies, or concrete portfolio construction rules. Fill modules.strategy.evidence with the page/section where these rules are defined.
Set present=false when trading appears only as motivation, an illustrative application, future work, or a passing mention. A mathematical result that COULD be used for trading is NOT a strategy. Never invent entry rules, thresholds, traded assets, or performance for a paper that does not state them.

STRATEGY FAMILY (modules.strategy.family) - the trading LOGIC, not the implementation tool:
{_quoted(STRATEGY_FAMILIES)}
"MachineLearning" is NOT a family (ML belongs in modules.machine_learning and entities.methods): a neural-network mean-reversion strategy is family=MeanReversion.

MODULES are present-gated: set present=true only when the paper genuinely contains that content; otherwise leave present=false and sub-fields null. Never fill a module from a passing mention.

EXPERIMENTS (experiments[]) - one entry per distinct empirical procedure; leave [] if the paper reports none (e.g. pure theory). Types:
{_quoted(EXPERIMENT_TYPES)}
- backtest ONLY for simulated trading of a strategy (fills, costs, portfolio paths);
- forecast_evaluation for out-of-sample forecast accuracy (RMSE, QLIKE, DM/MCS tests);
- regression_study, event_study, simulation_study, monte_carlo_study, cross_validation, benchmark_study for their standard meanings.
Theoretical/proof content goes to statements[] and claims[], NOT to experiments.

RESULTS (experiments[].results[]) - extract EVERY reported number:
- metric: canonical snake_case name, e.g. {_quoted(METRIC_EXAMPLES, 12)}
- value: EXACTLY as printed (never round, never invent; copy extreme values verbatim);
- unit, context, comparison, period, page: fill whenever available; context distinguishes variants (e.g. "net of costs", "model A vs benchmark HAR");
- report trading metrics (Sharpe, CAGR, drawdown...) AND scientific metrics (RMSE, R2, AIC, BIC, t-stat, p-value, AUC...) with equal care.

CLAIMS (claims[]) - one entry per important finding:
- type: {_quoted(CLAIM_TYPES)};
- direction: {_quoted(CLAIM_DIRECTIONS)}. Null results ("no significant effect") are valuable - report them explicitly;
- scope: what the claim covers (e.g. "US equities 1990-2020", "under Assumptions 1-3").

FORMULAS (formulas[]) - extract for EVERY paper with mathematical content:
- type: {_quoted(FORMULA_TYPES)};
- formula: LaTeX; variables: object mapping each symbol to its definition; page always included;
- related_model: name of the model this formula belongs to (must match entities.models[].name when applicable).

STATEMENTS (statements[]) - for theoretical/mathematical papers, the load-bearing structure:
- type: {_quoted(STATEMENT_TYPES)}; name as in the paper ("Theorem 3.2");
- conditions: the assumptions the statement requires; proof_method for proofs;
- do not extract statements for purely empirical papers.

ENTITIES (entities) - the research objects the paper works with:
- models: name, model_class ({_quoted(MODEL_CLASSES)}), origin ({_quoted(MODEL_ORIGINS)}) - "proposed" if the paper introduces it, "extended" if it extends an existing one, "used"/"evaluated" otherwise; key_variables, assumptions;
- methods: name, category ({_quoted(METHOD_CATEGORIES)}), origin;
- phenomena: name, kind ({_quoted(PHENOMENON_KINDS)}) - anomalies, stylized facts, effects (momentum, mean-reversion, low-volatility anomaly, Epps effect...).

DATA (data):
- datasets: canonical names ("CRSP daily", "LOBSTER", "TAQ", "Risk Lab") with access ({_quoted(DATASET_ACCESS)});
- data_uses: role ({_quoted(DATA_USE_ROLES)}) + data_type ({_quoted(DATA_TYPES)}) + frequency + fields + lookback + transformation.

RELATIONS (relations.related_work[]) - paper-level lineage from the related-work discussion:
- relation: {_quoted(RELATION_TYPES)}; target as cited ("Bouchaud et al. (2009)", "arXiv:0903.0974");
- ALWAYS extract extends/reproduces/contradicts when identifiable - this is how the knowledge graph grows.

MARKETS (markets):
- asset_classes EXACTLY from: {_quoted(ASSET_CLASSES)}. No synonyms: "stocks"->"Equities", "FX"/"forex"->"ForeignExchange", "crypto"/"tokens"->"Cryptocurrency", "bonds"->"FixedIncome", "indices"->"Indices".

CANONICALIZATION (classification.concepts):
- lowercase, singular, hyphenated, consistent tags ("mean-reversion", "hawkes-process", "limit-order-book"); never mix casing or singular/plural variants of the same concept.

REPRODUCIBILITY (reproducibility) - fill EVERY facet flag (source_code_available, data_available, parameters_complete, formulas_complete, rules_complete, execution_assumptions_complete), then derive classification ({_quoted(REPRO_CLASSIFICATIONS)}): Fully = code + data + complete rules/parameters; Partially = some; Not = nothing usable; Unknown = unclear.

ENUMS: bias_assessment values ({_quoted(BIAS_VALUES)}); live_deployment.technical_feasibility ({_quoted(LIVE_FEASIBILITY)}); latency_class ({_quoted(LATENCY_CLASSES)}); extraction.confidence ({_quoted(CONFIDENCE_VALUES)}).

CRITICAL RULES:
1. NEVER hallucinate or invent data. Missing = null or "not_specified". NEVER invent strategies, datasets, or relations.
2. Strictly separate: "explicit" (paper directly states), "derived" (logically inferable), "recommended" (your suggestion) in source_references.type.
3. NEVER evaluate quality (good/bad/profitable). Only document what the paper reports.
4. Extract ALL numerical results from tables and text, including negative and null results.
5. publication_year: from the publication venue/date, NOT the PDF creation date.
6. Every important claim and result needs a page number.
7. source_references entries: {{"claim", "page", "section", "table", "figure", "type"}}.
8. Do NOT add fields not in the schema. Return ONLY valid JSON. No markdown, no code fences, no explanation. Just the JSON object."""


def build_analysis_prompt(pdf_data: dict) -> str:
    """Build the user prompt with extracted PDF content."""
    schema_template = json.dumps(get_empty_schema(), indent=2)

    prompt = f"""Analyze the following quantitative finance research paper and fill in the JSON schema below.

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
- Extract ALL reported results (trading, forecasting, statistical) from tables and text
- Apply THE STRATEGY GATE strictly: modules.strategy.present=true only for a real, implementable trading system
- Fill claims, formulas, statements, experiments, entities, data, and relations even for non-strategy papers
- Include source_references for key claims
- Use null for unknown values, not empty strings
- Do NOT add fields not in the schema
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

