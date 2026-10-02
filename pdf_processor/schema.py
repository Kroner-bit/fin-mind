"""
JSON Schema template (V2) for research paper extraction.

ARCHITECTURE: General Research Core + Specialized Modules.

CORE (applies to every paper, strategy or not):
    document            bibliographic identity + contribution type
    research            question, hypothesis, objective, contributions
    classification     domains, concepts, in-scope flag
    entities            models, methods, phenomena
    markets             asset classes, markets, instruments
    statements          definitions, assumptions, theorems, proofs (math papers)
    formulas            typed mathematical objects with variables
    claims              typed, directional findings (replaces V1 key_findings)
    experiments         backtest is ONE type among many; experiments own results
    data                datasets + typed data uses
    reproducibility     facet flags + derived classification
    relations           paper-level lineage (extends / reproduces / contradicts / ...)
    modules             present-gated specialized sections (see below)
    limitations, source_references, extraction

MODULES (present-gated; sub-fields stay null unless the paper actually
contains that kind of content):
    strategy            trading system (V1 strategy subtree, evidence-gated)
    portfolio           portfolio construction / optimization
    market_making       quoting, inventory, adverse selection
    derivatives         pricing, hedging, Greeks, IV surface
    risk                risk measures, tail modeling, stress testing
    machine_learning    architectures, training, hyperparameters
    microstructure      LOB features, stylized facts, metaorders

STRUCTURAL RULES (from the V1/V2 vault audit):
    1. A strategy REFERENCES models/methods/formulas; it never contains them.
       modules.strategy is attached only when the paper itself defines a
       concrete trading system (THE STRATEGY GATE).
    2. EXPERIMENTS own results and validity checks; PAPERS own claims.
       Robustness checks and bias assessment live on experiments.
    3. Every categorical field draws from a controlled vocabulary below.
       Free text belongs in descriptive fields only.
"""

SCHEMA_VERSION = "2.0"


# ─── Controlled vocabularies ─────────────────────────────────────────────────

# Main contribution of the paper (what the paper IS, not what it is about;
# subject areas go to classification.domains)
PAPER_TYPES = [
    "Strategy",        # defines an implementable trading system
    "Model",           # proposes/extends a quantitative model
    "Method",          # proposes/extends a method, estimator, or algorithm
    "Theory",          # theoretical/axiomatic results
    "EmpiricalStudy",  # primarily empirical evidence (regressions, event studies)
    "Dataset",         # introduces a dataset or data resource
    "Benchmark",       # systematic comparison/benchmark of models or methods
    "SoftwareLibrary", # introduces software/tooling
    "Survey",          # literature review / survey
    "Other",
    "OutOfScope",      # no finance/economics or transferable quantitative content
]

# Subject areas (choose all that apply)
DOMAINS = [
    "QuantitativeFinance", "MathematicalFinance", "FinancialMathematics",
    "Probability", "Statistics", "Econometrics",
    "AssetPricing", "PortfolioTheory", "PortfolioOptimization",
    "Derivatives", "Options", "Volatility", "Risk",
    "MarketMicrostructure", "Liquidity", "MarketImpact",
    "Execution", "MarketMaking", "OptimalControl",
    "AlgorithmicTrading", "SystematicTrading", "StatisticalArbitrage",
    "FactorResearch", "Anomalies", "EmpiricalFinance", "BehavioralFinance",
    "MacroFinance", "Forecasting", "TimeSeriesAnalysis",
    "StochasticProcesses", "StochasticCalculus", "Optimization",
    "MachineLearning", "DeepLearning", "ReinforcementLearning",
    "Econophysics", "MarketSimulation", "AgentBasedModeling",
    "TextMiningFinance", "CryptocurrencyFinance", "DeFi",
    "EnergyMarkets", "CommodityMarkets", "FixedIncome", "Credit",
    "Mathematics", "Other",
]

# What the paper contributes (research.contributions[].type)
CONTRIBUTION_TYPES = [
    "model", "method", "theory", "empirical_evidence", "dataset",
    "software", "benchmark", "survey", "strategy", "null_result",
]

# Trading logic of a strategy (NOT the implementation tool:
# "MachineLearning" is NOT a family - ML belongs in modules.machine_learning)
STRATEGY_FAMILIES = [
    "Momentum", "TrendFollowing", "MeanReversion", "Breakout",
    "PairsTrading", "StatisticalArbitrage", "Factor", "Carry",
    "VolatilityTrading", "MarketMaking", "OptimalExecution",
    "EventDriven", "Seasonality", "IndexArbitrage", "TriangularArbitrage",
    "GridTrading", "TechnicalAnalysis", "Hedging", "PortfolioStrategy",
    "Other",
]

# Role of a model entity within the paper
MODEL_ORIGINS = ["proposed", "extended", "used", "evaluated"]
MODEL_CLASSES = [
    "diffusion", "stochastic_volatility", "jump_process", "point_process",
    "time_series", "regression", "factor", "state_space", "markov",
    "copula", "equilibrium", "market_impact", "microstructure",
    "agent_based", "neural", "tree_based", "kernel", "bayesian",
    "extreme_value", "optimization", "other",
]

METHOD_CATEGORIES = [
    "estimation", "inference", "forecasting", "optimization",
    "machine_learning", "validation", "simulation", "sampling",
    "data_processing", "risk_measurement", "trading", "other",
]

PHENOMENON_KINDS = ["anomaly", "stylized_fact", "effect", "regularity", "puzzle"]

STATEMENT_TYPES = [
    "definition", "assumption", "lemma", "proposition", "theorem",
    "corollary", "conjecture", "proof", "remark",
]

FORMULA_TYPES = [
    "model_equation",  # defining equation of a model (SDE, dynamics)
    "estimator",       # parameter estimation (MLE, GMM, least squares)
    "indicator",       # market/technical indicator definition
    "signal_rule",     # trading signal generation rule
    "pricing_rule",    # derivative/asset pricing formula
    "objective",       # objective/utility/loss function
    "constraint",      # feasibility constraint
    "identity",        # mathematical identity
    "update_rule",     # recursive/filtering update
    "other",
]

CLAIM_TYPES = ["empirical", "theoretical", "methodological"]
CLAIM_DIRECTIONS = [
    "positive",   # supports the hypothesis
    "negative",   # contradicts the hypothesis
    "null",       # no significant effect (report these - they are valuable)
    "mixed",      # holds conditionally / in some settings only
]

EXPERIMENT_TYPES = [
    "backtest",           # simulated trading of a strategy
    "forecast_evaluation",# out-of-sample forecast accuracy comparison
    "regression_study",   # cross-sectional / panel / time-series regression
    "event_study",        # event-window analysis (CAR, abnormal returns)
    "simulation_study",   # simulated market / agent-based / Monte Carlo
    "monte_carlo_study",  # MC estimation of quantities/prices
    "cross_validation",   # CV / walk-forward validation methodology
    "benchmark_study",    # systematic comparison of models/methods/tools
    "empirical_study",    # other empirical analysis
]

BIAS_KEYS = [
    "lookahead_bias", "survivorship_bias", "selection_bias", "data_snooping",
    "overfitting", "data_leakage", "p_hacking", "unrealistic_execution",
    "liquidity_bias",
]
BIAS_VALUES = ["identified", "addressed", "possible", "not_identified", "not_applicable"]

ASSET_CLASSES = [
    "Equities", "FixedIncome", "Commodities", "Energy", "ForeignExchange",
    "Futures", "Options", "Derivatives", "Cryptocurrency", "Indices",
    "ETFs", "MoneyMarket", "Credit", "InterestRates", "VolatilityInstruments",
    "RealEstate", "Other",
]

DATA_TYPES = [
    "OHLC", "OHLCV", "Tick", "TradeAndQuote", "OrderBook", "OrderFlow",
    "Fundamentals", "Macro", "News", "Text", "Sentiment", "OptionsChain",
    "ImpliedVolatility", "Alternative", "Simulated", "Other",
]

DATASET_ACCESS = ["public", "commercial", "proprietary", "author_provided", "simulated"]
DATA_USE_ROLES = ["signal", "training", "validation", "test", "evaluation", "construction"]

RELATION_TYPES = [
    "extends", "reproduces", "contradicts", "confirms", "uses",
    "compares_against", "cites",
]

REPRO_CLASSIFICATIONS = ["FullyReproducible", "PartiallyReproducible", "NotReproducible", "Unknown"]

LATENCY_CLASSES = ["EndOfDay", "Daily", "Hourly", "Minute", "Second",
                   "SubSecond", "Millisecond", "Microsecond", "Unknown"]

LIVE_FEASIBILITY = ["TechnicallyDeployable", "PartiallyDeployable", "InsufficientInformation"]

CONFIDENCE_VALUES = ["high", "medium", "low"]

# Canonical metric names (non-exhaustive; use snake_case; add others as printed)
METRIC_EXAMPLES = [
    # trading
    "total_return", "cagr", "annualized_return", "volatility", "sharpe_ratio",
    "sortino_ratio", "calmar_ratio", "max_drawdown", "win_rate",
    "profit_factor", "average_trade_return", "number_of_trades",
    "turnover", "alpha", "beta", "information_ratio", "excess_return",
    # forecasting
    "rmse", "mae", "mse", "mape", "qlike", "r_squared", "dm_test_statistic",
    # statistical fit
    "log_likelihood", "aic", "bic", "t_statistic", "p_value", "effect_size",
    # classification
    "accuracy", "auc", "f1_score", "precision", "recall",
    # cost
    "spread_cost", "market_impact_cost", "total_transaction_cost",
]


# ─── Empty experiment template ──────────────────────────────────────────────

def _empty_experiment() -> dict:
    return {
        "type": None,
        "description": None,
        "performed": None,

        "data": {
            "datasets": [],
            "data_type": None,
            "frequency": None,
            "period": {"start": None, "end": None},
            "universe": None,
            "splits": {
                "training_period": None,
                "validation_period": None,
                "test_period": None,
                "out_of_sample_period": None,
                "walk_forward": None,
            },
        },

        "methodology": {
            "design": None,
            "estimator_or_model": None,
            "controls": [],
            "procedure": None,
        },

        "backtest_details": {
            "engine": None,
            "portfolio_construction": None,
            "rebalancing_frequency": None,
            "capital": None,
            "leverage": None,
            "execution_model": None,
            "order_types": [],
            "fill_assumption": None,
            "transaction_costs": {
                "included": None,
                "commission": None,
                "spread": None,
                "slippage": None,
                "market_impact": None,
                "financing": None,
                "other": [],
            },
        },

        "results": [
            {
                "metric": None,
                "value": None,
                "unit": None,
                "context": None,
                "comparison": None,
                "better_than_baseline": None,
                "period": None,
                "page": None,
            }
        ],

        "statistical_tests": [
            {
                "test": None,
                "statistic": None,
                "p_value": None,
                "confidence_interval": None,
                "multiple_testing_correction": None,
                "page": None,
            }
        ],

        "robustness_checks": [
            {"type": None, "description": None, "outcome": None}
        ],

        "bias_assessment": {key: None for key in BIAS_KEYS},
    }


# ─── Main schema template ────────────────────────────────────────────────────

def get_empty_schema() -> dict:
    """Returns the full empty V2 schema template for a research paper."""
    return {
        "schema_version": SCHEMA_VERSION,

        "document": {
            "file_name": None,
            "title": None,
            "authors": [],
            "publication_year": None,
            "date": None,
            "arxiv_id": None,
            "ssrn_id": None,
            "doi": None,
            "journal": None,
            "pages": None,
            "paper_type": None,
            "keywords": [],
            "abstract": None
        },

        "research": {
            "research_question": None,
            "hypothesis": None,
            "objective": None,
            "market_phenomenon": None,
            "economic_intuition": None,
            "contributions": [
                {"type": None, "description": None}
            ]
        },

        "classification": {
            "in_scope": None,
            "domains": [],
            "concepts": []
        },

        "entities": {
            "models": [
                {
                    "name": None,
                    "model_class": None,
                    "origin": None,
                    "description": None,
                    "key_variables": {},
                    "assumptions": []
                }
            ],
            "methods": [
                {
                    "name": None,
                    "category": None,
                    "origin": None,
                    "description": None
                }
            ],
            "phenomena": [
                {
                    "name": None,
                    "kind": None,
                    "description": None
                }
            ]
        },

        "markets": {
            "asset_classes": [],
            "markets": [],
            "countries": [],
            "exchanges": [],
            "instruments": [],
            "tickers": []
        },

        "statements": [
            {
                "type": None,
                "name": None,
                "text": None,
                "conditions": [],
                "proof_method": None,
                "page": None
            }
        ],

        "formulas": [
            {
                "name": None,
                "formula": None,
                "type": None,
                "variables": {},
                "parameters": [],
                "purpose": None,
                "related_model": None,
                "page": None
            }
        ],

        "claims": [
            {
                "statement": None,
                "type": None,
                "direction": None,
                "scope": None,
                "page": None
            }
        ],

        "experiments": [_empty_experiment()],

        "data": {
            "datasets": [
                {
                    "name": None,
                    "provider": None,
                    "access": None,
                    "description": None
                }
            ],
            "data_uses": [
                {
                    "role": None,
                    "dataset": None,
                    "data_type": None,
                    "frequency": None,
                    "fields": [],
                    "lookback": None,
                    "transformation": None,
                    "source": None
                }
            ],
            "alternative_data": [],
            "data_sources": []
        },

        "reproducibility": {
            "classification": None,
            "source_code_available": None,
            "code_url": None,
            "data_available": None,
            "parameters_complete": None,
            "formulas_complete": None,
            "rules_complete": None,
            "execution_assumptions_complete": None
        },

        "relations": {
            "related_work": [
                {"relation": None, "target": None, "note": None}
            ]
        },

        "modules": {

            "strategy": {
                "present": False,
                "evidence": None,
                "name": None,
                "family": None,
                "type": None,
                "direction": None,
                "systematic": None,
                "holding_period": None,
                "trading_frequency": None,

                "signal": {
                    "description": None,
                    "formula": None,
                    "inputs": [],
                    "indicators": [],
                    "thresholds": [],
                    "lookback_periods": [],
                    "filters": []
                },

                "entry": {
                    "long": None,
                    "short": None,
                    "conditions": []
                },

                "exit": {
                    "take_profit": None,
                    "stop_loss": None,
                    "trailing_stop": None,
                    "time_exit": None,
                    "signal_reversal": None,
                    "other": []
                },

                "position_sizing": {
                    "method": None,
                    "parameters": {}
                },

                "risk_management": {
                    "method": None,
                    "parameters": {}
                },

                "execution_style": {
                    "order_types": [],
                    "fill_assumption": None,
                    "latency_requirement": None
                },

                "live_deployment": {
                    "technical_feasibility": None,
                    "latency_class": None,
                    "real_time_data_required": None,
                    "technical_dependencies": []
                }
            },

            "portfolio": {
                "present": False,
                "construction_method": None,
                "optimization_objective": None,
                "constraints": [],
                "rebalancing": None,
                "universe": None
            },

            "market_making": {
                "present": False,
                "quoting_model": None,
                "inventory_management": None,
                "adverse_selection_handling": None,
                "spread_policy": None,
                "order_type_mix": None
            },

            "derivatives": {
                "present": False,
                "instrument_class": None,
                "pricing_models": [],
                "hedging_approach": None,
                "greeks_used": [],
                "volatility_surface_aspects": None
            },

            "risk": {
                "present": False,
                "measures": [],
                "estimation_method": None,
                "tail_modeling": None,
                "stress_testing": None
            },

            "machine_learning": {
                "present": False,
                "task": None,
                "architectures": [],
                "learning_paradigm": None,
                "training_protocol": None,
                "hyperparameters": {},
                "feature_engineering": None,
                "validation_strategy": None,
                "hardware_note": None
            },

            "microstructure": {
                "present": False,
                "order_book_features": [],
                "stylized_facts": [],
                "metaorder_analysis": None,
                "liquidity_measures": []
            }
        },

        "limitations": [],

        "source_references": [],

        "extraction": {
            "confidence": None,
            "out_of_scope_reason": None,
            "missing_information": [],
            "notes": []
        }
    }


EXPECTED_TOP_LEVEL_KEYS = frozenset({
    "schema_version", "document", "research", "classification", "entities",
    "markets", "statements", "formulas", "claims", "experiments", "data",
    "reproducibility", "relations", "modules", "limitations",
    "source_references", "extraction",
})


# ─── V1 compatibility adapter ────────────────────────────────────────────────

def to_v1(v2: dict) -> dict:
    """
    Adapt a V2 extraction result to the legacy V1 shape, so that existing
    consumers (generate_obsidian_vault.py and friends) keep working while
    the pipeline migrates. Lossy by design: V2-only information
    (statements, entities, relations, modules other than strategy) is not
    representable in V1.

    Call this once per result before handing it to V1-only consumers.
    """
    def g(obj, *path, default=None):
        cur = obj
        for key in path:
            if not isinstance(cur, dict):
                return default
            cur = cur.get(key)
        return cur if cur is not None else default

    doc = g(v2, "document", default={})
    modules = g(v2, "modules", default={})
    strategy = g(modules, "strategy", default={}) or {}
    experiments = [e for e in g(v2, "experiments", default=[])
                   if isinstance(e, dict)]

    def first_experiment(*types):
        for e in experiments:
            if e.get("type") in types:
                return e
        return {}

    backtest_exp = first_experiment("backtest")
    empirical_exps = [e for e in experiments if e.get("type") and e.get("performed")]

    all_results = []
    all_tests = []
    for e in experiments:
        all_results.extend([r for r in g(e, "results", default=[]) if isinstance(r, dict)])
        all_tests.extend([t for t in g(e, "statistical_tests", default=[]) if isinstance(t, dict)])

    trading_metrics = {}
    for r in all_results:
        metric = r.get("metric")
        if metric and metric not in trading_metrics:
            trading_metrics[metric] = r.get("value")

    backtest_data = g(backtest_exp, "data", default={})
    backtest_costs = g(backtest_exp, "backtest_details", "transaction_costs", default={})
    backtest_exec = g(backtest_exp, "backtest_details", default={})

    data = g(v2, "data", default={})
    data_uses = [u for u in g(data, "data_uses", default=[]) if isinstance(u, dict)]
    signal_data = [
        {
            "data_type": u.get("data_type"),
            "frequency": u.get("frequency"),
            "fields": u.get("fields", []),
            "lookback": u.get("lookback"),
            "required": None,
            "transformation": u.get("transformation"),
            "source": u.get("source"),
        }
        for u in data_uses if u.get("role") == "signal"
    ]

    claims = [c for c in g(v2, "claims", default=[]) if isinstance(c, dict)]
    key_findings = [c.get("statement") for c in claims if c.get("statement")]

    def bias_v1(exp_list):
        out = {key: None for key in BIAS_KEYS}
        other = []
        for e in exp_list:
            for k, v in g(e, "bias_assessment", default={}).items():
                if v is not None and out.get(k) is None:
                    out[k] = v
        out["other"] = other
        return out

    def robustness_v1(exp_list):
        checks = []
        for e in exp_list:
            for c in g(e, "robustness_checks", default=[]):
                if isinstance(c, dict) and c.get("type"):
                    checks.append(c.get("type"))
        return {
            "different_markets": "addressed" if any("market" in str(c).lower() for c in checks) else None,
            "different_periods": "addressed" if any("period" in str(c).lower() or "sub" in str(c).lower() for c in checks) else None,
            "different_parameters": "addressed" if any("param" in str(c).lower() for c in checks) else None,
            "different_timeframes": None,
            "different_transaction_costs": "addressed" if any("cost" in str(c).lower() for c in checks) else None,
            "market_regimes": "addressed" if any("regime" in str(c).lower() for c in checks) else None,
            "parameter_perturbation": "addressed" if any("perturb" in str(c).lower() for c in checks) else None,
            "walk_forward": "addressed" if any("walk" in str(c).lower() for c in checks) else None,
            "other_tests": checks,
        }

    perf = {
        "total_return": trading_metrics.get("total_return"),
        "cagr": trading_metrics.get("cagr"),
        "annualized_return": trading_metrics.get("annualized_return"),
        "volatility": trading_metrics.get("volatility"),
        "sharpe_ratio": trading_metrics.get("sharpe_ratio"),
        "sortino_ratio": trading_metrics.get("sortino_ratio"),
        "calmar_ratio": trading_metrics.get("calmar_ratio"),
        "max_drawdown": trading_metrics.get("max_drawdown"),
        "win_rate": trading_metrics.get("win_rate"),
        "profit_factor": trading_metrics.get("profit_factor"),
        "average_trade": trading_metrics.get("average_trade_return"),
        "number_of_trades": trading_metrics.get("number_of_trades"),
        "turnover": trading_metrics.get("turnover"),
        "alpha": trading_metrics.get("alpha"),
        "beta": trading_metrics.get("beta"),
        "information_ratio": trading_metrics.get("information_ratio"),
        "benchmark": {
            "name": None,
            "return": None,
            "excess_return": trading_metrics.get("excess_return"),
        },
    }
    for r in all_results:
        if r.get("comparison"):
            perf["benchmark"]["name"] = r.get("comparison")
            break

    return {
        "schema_version": "1.0",

        "document": {
            "file_name": doc.get("file_name"),
            "title": doc.get("title"),
            "authors": doc.get("authors", []),
            "publication_year": doc.get("publication_year"),
            "date": doc.get("date"),
            "ssrn_id": doc.get("ssrn_id"),
            "doi": doc.get("doi"),
            "journal": doc.get("journal"),
            "pages": doc.get("pages"),
            "paper_type": doc.get("paper_type"),
            "keywords": doc.get("keywords", []),
            "abstract": doc.get("abstract"),
        },

        "research": {
            "research_question": g(v2, "research", "research_question"),
            "hypothesis": g(v2, "research", "hypothesis"),
            "objective": g(v2, "research", "objective"),
            "market_phenomenon": g(v2, "research", "market_phenomenon"),
            "economic_intuition": g(v2, "research", "economic_intuition"),
        },

        "markets": {
            "asset_classes": g(v2, "markets", "asset_classes", default=[]),
            "markets": g(v2, "markets", "markets", default=[]),
            "countries": g(v2, "markets", "countries", default=[]),
            "exchanges": g(v2, "markets", "exchanges", default=[]),
            "instruments": g(v2, "markets", "instruments", default=[]),
            "tickers": g(v2, "markets", "tickers", default=[]),
        },

        "strategy": {
            "present": bool(strategy.get("present")),
            "name": strategy.get("name"),
            "family": strategy.get("family"),
            "type": strategy.get("type"),
            "direction": strategy.get("direction"),
            "systematic": strategy.get("systematic"),
            "holding_period": strategy.get("holding_period"),
            "trading_frequency": strategy.get("trading_frequency"),
            "signal": strategy.get("signal", {
                "description": None, "formula": None, "inputs": [],
                "indicators": [], "thresholds": [], "lookback_periods": [],
                "filters": []}),
            "entry": strategy.get("entry", {
                "long": None, "short": None, "conditions": []}),
            "exit": strategy.get("exit", {
                "take_profit": None, "stop_loss": None, "trailing_stop": None,
                "time_exit": None, "signal_reversal": None, "other": []}),
            "position_sizing": strategy.get("position_sizing", {
                "method": None, "parameters": {}}),
            "risk_management": strategy.get("risk_management", {
                "method": None, "parameters": {}}),
        },

        "data_requirements": {
            "signal_data": signal_data,
            "backtest_data": [],
            "alternative_data": data.get("alternative_data", []),
            "fundamental_data": [u for u in data_uses if u.get("data_type") == "Fundamentals"],
            "macro_data": [u for u in data_uses if u.get("data_type") == "Macro"],
            "news_data": [u for u in data_uses if u.get("data_type") in ("News", "Text", "Sentiment")],
            "data_sources": data.get("data_sources", []),
        },

        "backtest": {
            "performed": bool(backtest_exp),
            "period": {
                "start": g(backtest_data, "period", "start"),
                "end": g(backtest_data, "period", "end"),
            },
            "training_period": g(backtest_data, "splits", "training_period"),
            "validation_period": g(backtest_data, "splits", "validation_period"),
            "test_period": g(backtest_data, "splits", "test_period"),
            "out_of_sample_period": g(backtest_data, "splits", "out_of_sample_period"),
            "instruments": g(v2, "markets", "instruments", default=[]),
            "frequency": backtest_data.get("frequency"),
            "data_type": backtest_data.get("data_type"),
            "methodology": {
                "engine_type": backtest_exec.get("engine"),
                "event_driven": None,
                "rebalancing_frequency": backtest_exec.get("rebalancing_frequency"),
                "capital": backtest_exec.get("capital"),
                "leverage": backtest_exec.get("leverage"),
                "execution_model": backtest_exec.get("execution_model"),
            },
            "transaction_costs": {
                "included": backtest_costs.get("included"),
                "commission": backtest_costs.get("commission"),
                "spread": backtest_costs.get("spread"),
                "slippage": backtest_costs.get("slippage"),
                "market_impact": backtest_costs.get("market_impact"),
                "financing": backtest_costs.get("financing"),
                "other": backtest_costs.get("other", []),
            },
            "execution": {
                "order_types": backtest_exec.get("order_types", []),
                "fill_assumption": backtest_exec.get("fill_assumption"),
                "partial_fills": None,
                "latency": None,
                "liquidity_constraints": None,
            },
        },

        "performance": perf,

        "statistics": {
            "t_statistics": [t.get("statistic") for t in all_tests if t.get("statistic") is not None],
            "p_values": [t.get("p_value") for t in all_tests if t.get("p_value") is not None],
            "confidence_intervals": [t.get("confidence_interval") for t in all_tests if t.get("confidence_interval") is not None],
            "standard_errors": [],
            "statistical_tests": [t.get("test") for t in all_tests if t.get("test")],
            "multiple_testing_correction": next(
                (t.get("multiple_testing_correction") for t in all_tests
                 if t.get("multiple_testing_correction")), None),
        },

        "robustness": robustness_v1(empirical_exps),
        "bias_analysis": bias_v1(empirical_exps),

        "infrastructure": {
            "backtest": {
                "engine_type": backtest_exec.get("engine"),
                "event_driven": None,
                "data_type": backtest_data.get("data_type"),
                "data_frequency": backtest_data.get("frequency"),
                "historical_depth": None,
                "order_book_required": None,
                "execution_simulation": backtest_exec.get("execution_model"),
                "slippage_model": None,
                "market_impact_model": None,
                "latency_model": None,
                "compute_requirements": {
                    "cpu": None, "ram": None, "gpu": None,
                    "storage": None, "parallelization": None,
                },
            },
            "live": {
                "market_data": None,
                "data_api": None,
                "broker_or_exchange": None,
                "execution_api": None,
                "order_types": g(strategy, "execution_style", "order_types", default=[]),
                "latency_requirement": g(strategy, "execution_style", "latency_requirement"),
                "colocation_required": None,
                "vps_sufficient": None,
                "monitoring": None,
                "logging": None,
                "failover": None,
            },
            "recommended_stack": {
                "language": None,
                "data_processing": [],
                "database": None,
                "storage": None,
                "backtest_engine": None,
                "execution": None,
                "infrastructure": None,
            },
            "minimum_requirements": {
                "cpu": None, "ram": None, "gpu": None,
                "storage": None, "network": None,
            },
            "complexity": {"backtest": None, "live": None},
        },

        "reproducibility": {
            "classification": g(v2, "reproducibility", "classification"),
            "source_code_available": g(v2, "reproducibility", "source_code_available"),
            "data_available": g(v2, "reproducibility", "data_available"),
            "parameters_complete": g(v2, "reproducibility", "parameters_complete"),
            "formulas_complete": g(v2, "reproducibility", "formulas_complete"),
            "entry_rules_complete": g(v2, "reproducibility", "rules_complete"),
            "exit_rules_complete": g(v2, "reproducibility", "rules_complete"),
            "execution_assumptions_complete": g(v2, "reproducibility", "execution_assumptions_complete"),
        },

        "live_deployment": {
            "technical_feasibility": g(strategy, "live_deployment", "technical_feasibility"),
            "required_data_available": None,
            "real_time_data_required": g(strategy, "live_deployment", "real_time_data_required"),
            "execution_feasible": None,
            "latency_class": g(strategy, "live_deployment", "latency_class"),
            "technical_dependencies": g(strategy, "live_deployment", "technical_dependencies", default=[]),
        },

        "key_findings": key_findings,

        "limitations": g(v2, "limitations", default=[]),

        "key_parameters": {
            (m.get("name") or f"model_{i}"): m.get("key_variables", {})
            for i, m in enumerate([m for m in g(v2, "entities", "models", default=[])
                                   if isinstance(m, dict) and m.get("name")])
        },

        "formulas": [
            {
                "name": f.get("name"),
                "formula": f.get("formula"),
                "variables": f.get("variables", {}),
                "purpose": f.get("purpose"),
                "page": f.get("page"),
            }
            for f in g(v2, "formulas", default=[]) if isinstance(f, dict)
        ],

        "source_references": g(v2, "source_references", default=[]),

        "extraction": {
            "confidence": g(v2, "extraction", "confidence"),
            "missing_information": g(v2, "extraction", "missing_information", default=[]),
            "notes": g(v2, "extraction", "notes", default=[]),
        },
    }
