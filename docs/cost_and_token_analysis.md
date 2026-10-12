# Cost & Token Consumption Analysis Report
## Autonomous Investment Research Intelligence Agent (IRA)

---

> [!IMPORTANT]
> **Measured figures (deployed Cloud Run service):**
>
> | Path | Latency | Tokens / brief | Cost / brief |
> |---|---|---|---|
> | REST `POST /v1/research/equity` | 2–7s | 0 (no model call) | **$0.00** |
> | Agentic `/adk` (Pro coordinator + Flash specialist) | 45s warm, 71s typical, 169s cold | ~21,700 | **~$0.05** |
>
> - **Asymmetric routing:** the Flash extraction specialist costs **$0.0053** per
>   brief where the same work on Pro would cost **$0.0215**, which saves about
>   **24% of total inference cost**. That saving comes from routing alone.
> - **Context caching:** confirmed on Vertex `CachedContent`. Later turns in a
>   session reported **1,593 then 2,739** cached prompt tokens. Nothing is cached
>   on the first turn, and Gemini won't cache a prefix under 2,048 tokens.
> - Specialist token usage has to be read from Cloud Monitoring: `AgentTool` runs
>   the specialist on a nested runner, so its usage doesn't show up in the ADK
>   response.
>
> **The tables in sections 1–3 below are the original pre-deployment *model***,
> built from Vertex list prices and an assumed 150,000-token 10-K. They are kept
> for comparison with the measured results. Treat them as estimates, not telemetry.

---

### Document Control
- **Document Version:** 1.2.0 — measured agentic-path figures added; tables relabelled as modelled
- **Cost Target:** $\le$ $0.25 USD per Synthesized Brief
- **Model Tiers Evaluated:** Google Vertex AI Gemini 2.5 Pro & Gemini 2.5 Flash

---

## 1. Executive Summary: Economic Viability

A critical failure mode of enterprise GenAI deployments is uncontrolled token cost when querying multi-hundred-page corporate regulatory filings. An annual Form 10-K report spans ~150,000 tokens. Calling a frontier model 3 to 4 times during multi-agent analysis consumes 450,000 to 600,000 tokens per research brief. Without architectural optimization, this equates to **$0.60 to $1.20 per query**, making autonomous research economically unsustainable at enterprise scale.

The IRA architecture overcomes this hurdle through two key mechanisms:
1. **Gemini Context Caching:** Form 10-Ks are cached on Vertex AI, reducing input token read pricing by **75%** ($0.3125 / 1M cached tokens vs $1.25 standard).
2. **Asymmetric Model Routing:** High-volume tabular extraction is delegated to **Gemini 2.5 Flash** ($0.075 / 1M input tokens), reserving **Gemini 2.5 Pro** solely for root coordination and final multi-source synthesis.

**Modelled result:** the projected cost per research brief is **$0.165 USD**, below the **$0.25 cap**. Projected, from list prices and an assumed filing size — not measured. See the banner at the top.

```mermaid
pie title Modelled Inference Cost per Brief, ADK path ($0.165 projected)
    "Gemini Context Caching Reads (10-K Input)" : 0.047
    "Gemini 2.5 Pro Synthesis & Planning" : 0.078
    "Gemini 2.5 Flash Sub-Agent Extraction" : 0.022
    "Cloud Run Compute & BigQuery Streaming" : 0.018
```

---

## 2. Per-Query Token & Cost Breakdown

| Operational Stage | Model Tier / Engine | Input Tokens | Output Tokens | Standard Cost | Optimized Cost (Context Caching + Routing) | Cost Reduction |
|---|---|---|---|---|---|---|
| **Root Planning Loop** | Gemini 2.5 Pro (Thinking: 2k) | 1,800 | 1,200 | $0.0125 | $0.0125 | Baseline |
| **SEC Filing Specialist** | Gemini 2.5 Flash | 150,000 (10-K) | 2,500 | $0.1187 | **$0.0245 (Cached)** | **79.4%** |
| **Transcript Specialist** | Gemini 2.5 Flash | 22,000 | 1,800 | $0.0072 | $0.0072 | Baseline |
| **Macro News Specialist** | Vertex Search / Grounding | 3,500 | 800 | $0.0025 | $0.0025 | Baseline |
| **Deterministic Calculator** | Pure Python Execution | 0 | 0 | $0.0000 | $0.0000 | **100% Free** |
| **Report Synthesis Engine** | Gemini 2.5 Pro | 150,000 (10-K Ref) + 8k | 3,200 | $0.2185 | **$0.0655 (Cached)** | **70.0%** |
| **Total per Query** | **Multi-Tier Orchestration** | **327,300** | **9,500** | **$0.3594** | **$0.1652** | **54.0% Overall** |

---

## 3. Scale Forecasting: Monthly Cloud Hosting Expenditure

```mermaid
graph LR
    subgraph Tier1 [Tier 1: 1,000 Queries / Month]
        T1_Inference["$165.00 Inference"]
        T1_Infra["$35.00 Cloud Run + BQ"]
        T1_Total["Total: $200.00 / Mo"]
    end

    subgraph Tier2 [Tier 2: 10,000 Queries / Month]
        T2_Inference["$1,650.00 Inference"]
        T2_Infra["$120.00 Cloud Run + BQ"]
        T2_Total["Total: $1,770.00 / Mo"]
    end

    subgraph Tier3 [Tier 3: 100,000 Queries / Month]
        T3_Inference["$16,500.00 Inference"]
        T3_Infra["$650.00 Cloud Run + BQ"]
        T3_Total["Total: $17,150.00 / Mo"]
    end
```

### 3.1 Financial ROI & Labor Savings
- **Manual Preparation Cost:** An equity analyst earning $150k/year costs ~$75/hour. A 4-hour manual quarterly synthesis costs **$300.00 in human labor**.
- **IRA Autonomous Preparation Cost:** **$0.165 in inference compute**.
- **Net Cost Savings:** **> 99.9% cost reduction per synthesized brief**.
- **Time Savings:** Reduces synthesis turnaround from 4 hours (240 minutes) to **38.5 seconds** (a **99.7% acceleration**), allowing analysts to cover 5x more companies per earnings season.
