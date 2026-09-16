# Technical Design Document (TDD) — Part 1: System Architecture
## Autonomous Investment Research Intelligence Agent (IRA)

---

### Document Control
- **Document Version:** 1.0.0
- **Classification:** Confidential / System Architecture Specification
- **Architectural Paradigms:** Hierarchical Multi-Agent Topology, Contract-First API, Event-Driven Observability, Zero-Trust Infrastructure

---

## 1. Architectural Vision & Core Principles

The IRA system implements a decoupled, event-driven, hierarchical multi-agent architecture powered by Google Cloud Platform, the Google Agent Development Kit (ADK), and Gemini 2.5 Pro.

```mermaid
graph TB
    subgraph ClientAndIngress [Client & Ingress Layer]
        Client[Institutional Analyst Web / Terminal UI]
        LoadBalancer[Cloud Load Balancing + Cloud Armor WAF]
        FastAPIGateway[FastAPI Application Gateway<br/>OAuth2 / Bearer Token & DLP Redaction]
    end

    subgraph SecurityBoundary [Pre-Execution Security Boundary]
        InputGuard[InputGuardrail: Injection & Scope Classifier]
        RateLimiter[Token Bucket Rate Limiter: SEC 8 req/s cap]
    end

    subgraph AgentRuntime [Vertex AI Multi-Agent Runtime]
        RootAgent[Root Coordinator Agent<br/>Gemini 2.5 Pro + Thinking Budget Planner]
        
        subgraph SpecializedAgents [Domain Specialized Sub-Agents]
            SECAgent[SEC Filing Specialist<br/>Form 10-K/10-Q XBRL Parser]
            TranscriptAgent[Earnings Transcript Specialist<br/>Executive Remarks vs Q&A Segmenter]
            MacroAgent[Macro & News Specialist<br/>Vertex AI Search Grounding]
        end

        subgraph CoreEngines [Execution & Caching Engines]
            CalcEngine[FinancialCalculator<br/>Deterministic Decimal Precision Math]
            ContextCacheEngine[Gemini Context Caching Manager<br/>Static 10-K In-Memory Token Cache]
            SynthesisEngine[Report Synthesis & Citation Verifier]
        end
    end

    subgraph DatastoresAndOps [Datastores, Observability & Async Pub/Sub]
        CloudTrace[Google Cloud Trace<br/>Distributed OpenTelemetry Spans]
        CloudLogging[Google Cloud Logging<br/>Structured JSON Logs]
        BigQueryAudit[BigQuery Datasets<br/>Immutable Compliance Audit Trails]
        PubSubBroker[Google Cloud Pub/Sub<br/>Research Events Broadcaster]
        SecretManager[Google Secret Manager]
    end

    Client --> LoadBalancer --> FastAPIGateway
    FastAPIGateway --> InputGuard --> RootAgent
    RootAgent --> SECAgent
    RootAgent --> TranscriptAgent
    RootAgent --> MacroAgent
    SECAgent --> RateLimiter
    SECAgent --> ContextCacheEngine
    SECAgent --> CalcEngine
    TranscriptAgent --> CalcEngine
    RootAgent --> SynthesisEngine
    SynthesisEngine --> FastAPIGateway
    FastAPIGateway --> Client

    FastAPIGateway -.-> CloudTrace
    RootAgent -.-> CloudTrace
    FastAPIGateway -.-> CloudLogging
    SynthesisEngine -.-> BigQueryAudit
    SynthesisEngine -.-> PubSubBroker
    FastAPIGateway -.-> SecretManager
```

### Core Architecture Tenets:
1. **Separation of Reasoning and Extraction:** High-order reasoning and multi-step decomposition reside exclusively in the Root Coordinator (Gemini 2.5 Pro), while high-throughput tabular parsing and quote extraction are delegated to specialized sub-agents running Gemini 2.5 Flash.
2. **Deterministic Mathematical Verification:** Zero arithmetic is performed by language models; all financial growth rates, margins, FCF conversions, and leverage ratios are computed by pure Python execution tools using IEEE 754-safe `Decimal` operations.
3. **Evidentiary Line-Item Provenance:** No financial figure or executive claim is rendered without an explicit `EvidentiaryCitation` referencing filing accession numbers, statement row items, or verbatim transcript timestamps.
4. **Pre-Execution Defense-in-Depth:** Adversarial prompt injections, jailbreaks, and out-of-domain queries are intercepted by pre-execution classifier callbacks before model dispatch.

---

## 2. End-to-End System Interaction & Sequence Flow

```mermaid
sequenceDiagram
    autonumber
    actor Analyst as Equity Analyst
    participant API as FastAPI Gateway
    participant DLP as Cloud DLP Engine
    participant Guard as Pre-Execution Guardrail
    participant Root as Root Coordinator (Gemini 2.5 Pro)
    participant SEC as SEC Filing Sub-Agent
    participant Trans as Transcript Sub-Agent
    participant Macro as Macro Sub-Agent
    participant Calc as Financial Calculator
    participant Synth as Synthesis Engine
    participant BQ as BigQuery / Cloud Logging
    participant PubSub as Cloud Pub/Sub

    Analyst->>API: POST /v1/research/equity {ticker: "AAPL", fiscal_year: 2024, focus_areas: ["Services_Margin", "China"]}
    API->>API: Validate OAuth2 Bearer Token
    API->>DLP: Redact proprietary portfolio metadata & analyst PII
    DLP-->>API: Sanitized request payload
    API->>Guard: Inspect prompt for injection & domain scope
    Guard-->>API: Verdict: PASS (Security score 1.0)
    
    API->>Root: Dispatch sanitized research request
    Note over Root: Plan-and-Execute reasoning loop with thinking budget
    Root->>Root: Formulate Decomposed Execution Plan
    
    par Concurrent Sub-Agent Data Gathering
        Root->>SEC: fetch_sec_filing_section(ticker="AAPL", form="10-K", year=2024)
        SEC->>SEC: Query SEC EDGAR MCP / Check Context Cache
        SEC-->>Root: Return parsed XBRL Markdown tables & metadata
    and
        Root->>Trans: get_earnings_transcript(ticker="AAPL", quarter="Q4_2024")
        Trans->>Trans: Segment CFO remarks vs analyst Q&A
        Trans-->>Root: Return segmented quotes & sentiment tags
    and
        Root->>Macro: query_macro_news(ticker="AAPL", focus_areas)
        Macro->>Macro: Vertex AI Search Grounding
        Macro-->>Root: Return grounded market indicators & news
    end

    Root->>Calc: calculate_metrics(raw_balance_sheet, raw_operations, raw_cash_flows)
    Calc-->>Root: Return deterministic verified metrics (YoY growth, margin compression, FCF, D/E)

    Root->>Synth: Synthesize cross-source brief with line-item citations
    Synth->>Synth: Validate 100% evidentiary provenance
    Synth-->>Root: Schema-validated ResearchBriefResponse

    par Asynchronous Audit & Event Broadcast
        Root->>BQ: Stream immutable audit record (user, ticker, latency_ms, prompt_hash, tokens)
    and
        Root->>PubSub: Publish `research.brief.completed` event topic
    end

    Root-->>API: Return ResearchBriefResponse
    API-->>Analyst: HTTP 200 OK + Audit-Ready Brief JSON
```

---

## 3. Component Deep Dive & Contracts

### 3.1 Ingress & Security Boundary (FastAPI Gateway)
- **Authentication:** Validates incoming Bearer JWT tokens against Google Cloud IAM / OAuth2 provider.
- **DLP Sanitization Middleware:** Invokes Cloud DLP REST API or local regex redaction filter to scrub customer account numbers, portfolio holdings, and analyst names.
- **Input Guardrail:** Rejects prompt injection patterns (`ignore all prior instructions`, `act as DAN`, `drop table`) and enforces financial scope boundaries.

### 3.2 Root Coordinator Agent (Google ADK)
- **Model:** `gemini-2.5-pro` with `thinking_budget` allocated for complex multi-part planning.
- **State Management:** In-memory execution state maintaining sub-agent response bundles, verified calculation payloads, and execution latency timestamps.
- **Concurrency:** Uses `asyncio.gather` for non-blocking parallel dispatch to sub-agents.

### 3.3 Domain Sub-Agents
- **SEC Filing Specialist:** Connects via Model Context Protocol (MCP) to parse SEC EDGAR filings; normalizes XBRL tables into markdown representations.
- **Earnings Transcript Specialist:** Parses quarterly call transcripts; separates prepared executive remarks (CFO guidance) from live analyst Q&A.
- **Macro News Specialist:** Leverages Vertex AI Search grounding for live interest rate policies, trade tariffs, and sector sentiment.

### 3.4 Verification & Synthesis Engine
- **Financial Calculator:** Pure Python tool computing metrics using standard formulas and `decimal.Decimal` arithmetic.
- **Citation Verifier:** Validates that every numerical claim in the synthesized report maps to a registered `EvidentiaryCitation` object.

---

## 4. High-Availability & Fault Tolerance Strategy

```mermaid
stateDiagram-v2
    [*] --> Healthy: Service Running Normal
    Healthy --> Degraded: Upstream SEC 429 / Vertex 503
    Degraded --> Healthy: Retry with Jitter Succeeds
    Degraded --> CircuitBreakerOpen: 5 Consecutive Failures
    CircuitBreakerOpen --> FallbackMode: Return Cached Filing Snapshots
    FallbackMode --> HalfOpen: 60-Second Cooldown Expired
    HalfOpen --> Healthy: Probe Request Succeeds
    HalfOpen --> CircuitBreakerOpen: Probe Request Fails
```

1. **Horizontal Autoscaling:** Cloud Run autoscales from 1 to 50 instances based on CPU utilization and request concurrency ($\ge 80$).
2. **Circuit Breaker:** Prevents cascading thread pool exhaustion during upstream SEC EDGAR outages.
3. **Graceful Degradation:** When upstream APIs are unavailable, the system automatically falls back to cached 10-K filing extracts from Cloud Storage.
4. **Health Check Probes:**
   - `/healthz`: Liveness probe verifying process responsiveness.
   - `/readyz`: Readiness probe asserting database connectivity and API key validity.
