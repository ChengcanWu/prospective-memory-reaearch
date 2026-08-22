# Conditional Memory: Modeling and Triggering Deferred Intentions in LLM Agents

**Method:** ProMem

---


# Abstract

Large language model (LLM) agents are increasingly evaluated on *retrospective* memory---retrieving facts from long interaction histories to answer questions. Reliable assistants, however, must also maintain *prospective* memory: deferred intentions that should be executed when a future cue or clock condition becomes true, while the agent continues other mandatory activities, and that must be updated under reschedule, cancel, and override events without spurious false alarms. Recent work on PM-Bench [pmbench2026] shows that this ``when-to-act'' competence is far from solved: monitoring hidden environment channels is a severe bottleneck, cross-day and update-sensitive hits remain low, and no universal scaffold dominates the Set-F1 operating point. We argue that the missing abstraction is *conditional memory*: structured records of the form $(,,)$ that couple a trigger condition $$, an executable action $$, and a lifecycle state $$, rather than free-form episodic snippets optimized for needle retrieval. We formalize this view and propose **ProMem**, a prospective-memory scaffold with (i) dual stores separating an episodic retrospective bank from a Prospective Intention Store (PIS), (ii) an explicit lifecycle manager over announce→active→fired/completed/canceled/modified transitions, (iii) a proactive trigger monitor that decides when to query clocks, email, and other hidden channels, and (iv) a due-set scorer that selects executable candidates while suppressing lures. On the PM-Bench Virtual Week protocol we expect ProMem to improve Set-F1 especially on channel-required, cross-day, and update-sensitive slices, and to achieve a better precision--recall trade-off than spammy auto-heartbeats. Code and prompts will be released upon publication.

---


# Introduction

LLM agents that operate over long horizons are routinely equipped with memory modules: vector stores, summarization pipelines, graph memories, and retrieval-augmented generation (RAG) stacks designed to surface the right past fact at question time [locomo2024,longmemeval2024,amem2025]. These systems primarily target *retrospective* memory---answering ``what happened?'' from chat history. In everyday assistance, however, users also issue deferred instructions: take medicine at 21:00, book a slot when the portal opens, reply once an email arrives, cancel the reminder if plans change. Success here is not measured by retrieving a needle from a haystack, but by *acting at the right future moment* while still advancing concurrent tasks, and by *not* acting when the intention has been canceled or the cue is only a lure.

Cognitive science has long distinguished retrospective recall from *prospective memory* (PM)---remembering to execute delayed intentions under cue- or time-based triggers amid ongoing activity [einstein2005prospective,rendell2000virtual]. PM-Bench [pmbench2026] imports this distinction into LLM-agent evaluation via a seven-day Virtual Week: at each step the agent must choose a mandatory ongoing activity and optionally fire a set of prospective actions against a ground-truth *due set* $D_t$, while hidden state channels (clock, email, portals, ) are invisible unless actively queried. Empirically, frontier models remain fragile: channel-required hit rates are near floor, cross-day and update-sensitive intentions are frequently missed, and scaffolds that spam monitoring queries inflate false positives and degrade Set-F1. Critically, no single off-the-shelf pattern---plain single-agent prompting, todo ledgers, optional or auto heartbeats, or hierarchical union-query---is universally best.

We contend that the gap is conceptual as well as architectural. Retrospective memory treats past events as content to be retrieved under a query; prospective competence requires *conditional* records that remain dormant until a trigger fires, then transition through a lifecycle that supports modification and cancellation. Conflating the two---storing intentions as ordinary episodic text and hoping RAG or long context will ``notice'' when they are due---fails exactly where PM-Bench isolates difficulty: monitoring under uncertainty, discriminating lures, and preserving commitments across days and updates.

*[Figure placeholder]*

To address this gap we introduce **conditional memory** as a first-class abstraction for agent memory, and instantiate it with **ProMem** (Figure [fig:promem-overview]): dual memory stores, an intention lifecycle manager, a proactive trigger-monitoring policy, and a due-set scorer integrated with ongoing activity choice. Our contributions are:

    
- We identify prospective ``when-to-act'' memory as distinct from retrospective needle retrieval, anchored on PM-Bench evidence that monitoring and lifecycle updates---not mere storage---are the bottleneck.
    
- We define conditional memory as structured intentions $I=(,,,meta)$ and contrast them with episodic/retrospective banks; we formalize due sets $D_t$ and the Set-F1 objective.
    
- We propose ProMem: dual stores (episodic bank + Prospective Intention Store), lifecycle transitions, a monitor policy $_mon$ for hidden channels, and a due-set scorer that balances precision and recall under lures.
    
- We outline a PM-Bench-centric evaluation protocol with baselines matching published scaffolds, ablations isolating each ProMem component, and expected gains on channel, cross-day, and update-sensitive slices.

---


# Related Work

**Retrospective agent memory benchmarks.**
A large body of work evaluates whether agents can retrieve or recall information from long dialogues and multi-session histories. LoCoMo [locomo2024] stresses long-term conversational memory with questions grounded in prior turns; LongMemEval [longmemeval2024] and related suites probe retention, updates, and temporal reasoning over extended agent logs. Method papers respond with hierarchical summaries, graph memories, write--read controllers, and RAG variants [amem2025,memorybank2023,memgpt2023]. These benchmarks and systems primarily ask: given a question *now*, can the agent recover the right past fact? They do not require executing a previously announced action at a future cue while concurrent tasks continue.

**Prospective memory in cognitive science.**
Prospective memory research studies how humans form delayed intentions, monitor for cues, and execute actions under ongoing-task load [einstein2005prospective,smith2003demand]. The Virtual Week paradigm [rendell2000virtual] embeds irregular time- and event-based tasks in a simulated seven-day schedule and scores whether participants act when due---a design that PM-Bench [pmbench2026] adapts for LLM agents. We inherit PM-Bench's due-set framing and diagnostic slices (channel hit, cross-day, update-sensitive) and treat them as the primary yardstick for conditional memory.

**Agent scaffolds for reminders and monitoring.**
Practical agent stacks often maintain todo lists, calendars, or periodic ``heartbeat'' loops that wake the model to re-check the environment [memgpt2023,anthropic2024computeruse]. PM-Bench evaluates several such scaffolds---todo ledgers, optional and auto heartbeats, hierarchical union-query---and finds that more monitoring does not automatically yield higher Set-F1: auto-heartbeats can raise update hits while flooding false positives, and hierarchical querying can issue thousands of channel reads yet still miss channel-required dues [pmbench2026]. ProMem differs by separating prospective intentions from episodic text, maintaining explicit lifecycle state, and coupling a learned/prompted monitor policy with a due-set scorer rather than relying on undifferentiated periodic wakes.

**Positioning.**
Our work is complementary to retrospective memory research: episodic stores remain useful for answering history questions, but they are insufficient as the sole substrate for deferred execution. Conditional memory and ProMem target the orthogonal axis isolated by PM-Bench---triggering, updating, and suppressing intentions over time.

---


# Motivation and Preliminaries

## Motivation: From Needle Retrieval to When-to-Act

Retrospective memory benchmarks reward recovering a fact that already occurred. Prospective settings reward a different competence: the agent must (i) encode an intention when it is announced, (ii) keep it available across intervening steps and days, (iii) detect when its trigger is satisfied---often only after querying a channel that is hidden by default---and (iv) execute exactly the due actions while refusing lures and honoring cancel/reschedule/override updates. PM-Bench [pmbench2026] makes this operational: even when intentions are written into a ledger, agents under-monitor non-clock channels (best hidden-channel hit reported near $16.7%$), struggle on cross-day commitments, and face a precision--recall dilemma under heartbeats.

These failures suggest that ``store more text in memory'' is the wrong inductive bias. What is needed is a *conditional* representation: the intention is not an answer candidate for a user question, but a dormant policy fragment ``if $$ holds, do $$'' with mutable status $$. We call such records **conditional memory**. The remainder of this section formalizes the PM-Bench interaction model and our intention abstraction; Section [sec:methods] then presents ProMem as a scaffold built around this abstraction.

## Preliminaries: PM-Bench Interaction Model

We follow the PM-Bench Virtual Week protocol [pmbench2026]. Time proceeds in discrete steps $t=1,,T$ over a simulated week (released setting: $T=80$ steps, irregular day schedules). At step $t$ the agent observes a narrative vignette $v_t$, a menu of mandatory ongoing activities $C_t=\A,B,C\$, and a set of anonymous prospective action handles $X_t$ that mixes true task actions with *lures*. A collection of state channels $H$ (clock, email, portal, ) is *hidden*: contents are revealed only if the agent issues monitoring queries.

**Query-then-act protocol.**
Each step proceeds as:

    
- The agent may issue zero or more monitoring queries $q_t$ and observe returns $r_t=Read(q_t)$.
    
- The agent submits $a_t=(c_t,D_t)$ where $c_t_t$ is the ongoing activity and $D_t X_t$ is the set of prospective actions declared due now.

**Due set.**
Let $I$ be the set of task definitions. Each task $$ carries a trigger condition and an executable action. Write $X_t$ for the handles available at $t$. The ground-truth due set is

$$
D_t = \  X_t :  is still valid and its execution condition holds at t\,
$$

where event-based tasks become due when the relevant cue appears in $v_t$ or in queried channel returns, and time-based tasks become due when the simulated clock matches a target time (or falls in an allowed window). Validity excludes canceled tasks and respects the latest reschedule/override.

**Objective.**
PM-Bench aggregates set overlap over the trajectory:

$$
TP=_t |D_t_t|, 
FP=_t |D_t D_t|, 
FN=_t |D_t_t|,
$$

$$
Set-F1=2 TP2 TP+FP+FN.
$$

Precision-only metrics reward never acting; recall-only metrics reward firing every handle every step. Set-F1 requires both hitting dues and suppressing false alarms---the natural objective for conditional memory.

## Conditional Memory Formalism

definition[Conditional memory / intention]

An intention is a tuple

$$
I = (,,,meta),
$$

where $$ is a trigger predicate over observable evidence (narrative text, channel returns, clock), $$ is an executable action handle, $$ is a lifecycle state, and $meta$ stores identifiers, announce step, schedule metadata, and free-text glosses for the LLM.
definition

We take the lifecycle alphabet

$$
=\announced,active,fired,completed,canceled,modified\.
$$

Informally: intentions enter as announced when first stated; become active once admitted to the Prospective Intention Store; transition to fired when selected in $D_t$ and to completed when execution is accepted by the environment; move to canceled on cancel events; and to modified (then typically back to active with updated $$) on reschedule/override.

definition[Conditional vs.\ episodic memory]

An *episodic / retrospective* record $e$ is content indexed for retrieval under a query $q$, scoring $sim(e,q)$. A *conditional* record $I$ is content indexed for *trigger evaluation*: at step $t$ one asks whether evidence $e_t=(v_t,r_t)$ satisfies $$, not whether $I$ answers a user question. The two stores may share surface text but differ in API, update rules, and success metric (Set-F1 vs.\ QA accuracy).
definition

proposition[Due set as trigger satisfaction]

Under a perfect monitor and faithful lifecycle, 

$$
D_t = \(I) : I_t, (I)\active,modified\,  e_t(I)\,
$$

where $P_t$ is the set of intentions still stored at $t$. Failures of monitoring ($e_t$ missing channel facts), stale $$, or lure confusion yield $D_t D_t$.
proposition

Proposition [prop:due] isolates why retrospective RAG is insufficient: retrieval may surface the intention text even when $$ is false (false alarm) or fail to re-check channels when $$ would be true (miss). Conditional memory makes $$, $$, and $$ explicit so that monitoring, updating, and scoring can be specialized.

---


# Proposed Method:
 ProMem

ProMem is an inference-time scaffold for LLM agents that implements conditional memory on top of a frozen backbone. It comprises four components: dual memory stores, a lifecycle manager, a proactive trigger monitor, and a due-set scorer, composed under the PM-Bench query-then-act loop (Figure [fig:promem-overview]). The full control flow is given in Appendix [sec:Algorithm].

## Problem Statement

Given trajectory observations $\o_t\$ under the protocol of Section 3, the agent must produce actions $a_t=(c_t,D_t)$ maximizing expected Set-F1 against $\D_t\$, subject to realistic monitoring cost. We decompose the policy as

$$
(a_t,q_t o_t,M_t)
=
_mon(q_t o_t,M_t) 
_due(D_t o_t,r_t,M_t) 
_act(c_t o_t,r_t,M_t),
$$

where $M_t=(E_t,P_t)$ denotes dual memory (episodic bank $E_t$, Prospective Intention Store $P_t$), $r_t$ are channel returns after queries $q_t$, $_mon$ is the trigger monitor, $_due$ the due-set scorer, and $_act$ selects the mandatory ongoing activity. ProMem specifies the structure of $M_t$ and the three factors; each factor may be realized by prompting the same backbone with specialized context, or by lightweight scored rules on top of LLM judgments.

## Dual Memory: Episodic Bank and Prospective Intention Store

**Episodic retrospective bank $E**$.
Narrative vignettes, prior activity choices, and channel returns that are useful for situational awareness or for answering retrospective probes are appended to $E$ as timestamped snippets (optionally summarized). Retrieval over $E$ uses standard similarity or recency and is *not* the primary path for deciding dues.

**Prospective Intention Store (PIS) $P**$.
Whenever the observation stream announces a deferred task---or an update referring to an existing task---ProMem upserts an intention $I=(,,,meta)$ into $P$. Triggers $$ are represented as structured fields plus natural-language glosses, covering the PM-Bench typology:

    
- *Time-based:* $$ references clock predicates (exact time or window).
    
- *Event- / narrative-based:* $$ references cues in $v_t$.
    
- *Channel-based:* $$ references predicates over specific $h$ (email subject, portal slot, ).

Cross-day intentions remain in $P$ with $=active$ from announce until the later cue day; they are never demoted merely because the announce-day ended.

Separation is intentional: mixing intentions into a flat episodic store forces the model to rediscover ``this is a deferred commitment'' on every step, which PM-Bench shows is brittle. PIS instead exposes an explicit inventory of open commitments to $_mon$ and $_due$.

## Lifecycle Manager

The lifecycle manager $$ applies deterministic (or LLM-assisted) updates

$$
(P_t+1,E_t+1)=(P_t,E_t,o_t,r_t,a_t,u_t),
$$

where $u_t$ denotes detected update events (cancel / reschedule / override) in the observation stream.

**Transition sketch.**

    
- announce→active: parse a new intention; insert into PIS.
    
- active→fired: $_t$ under $_due$.
    
- fired→completed: environment acknowledges success (or ProMem marks completion when the protocol treats fire as terminal).
    
- active→canceled: cancel event naming the intention.
    
- active→modified$: reschedule/override rewrites $$ (and possibly $$); previous due windows are invalidated so stale fires count as FP if produced.

Update-sensitive correctness is therefore a first-class state-machine property: after a cancel, $_due$ must assign near-zero score regardless of cue resemblance; after a reschedule, only the new $$ may admit membership in $D_t$. Retrospective-only systems that keep both old and new phrasings in a bag of snippets routinely violate this constraint.

## Proactive Trigger Monitor

Hidden-channel monitoring is the bottleneck reported by PM-Bench [pmbench2026]: narrative-cued tasks are comparatively easier, whereas channel-required hits remain low even when agents issue many queries. ProMem therefore treats monitoring as a deliberate policy $_mon$, not an afterthought.

**Information state.**
At step $t$, let $P_t^open=\I_t:(I)\active,modified\\$. For each open intention, define a dependency set $deps(I)\narrative\$ listing evidence sources that could satisfy $(I)$. The monitor constructs a priority list

$$
s_mon(h t)=_I_t^open w(I) 1[h(I)] (I,t),
$$

where $w(I)$ weights task importance / regularity if available, and $(I,t)$ is a urgency prior (e.g., higher when a time window is approaching, when a cross-day intention's target day has begun, or when recent narrative mentions a related entity).

**Query selection.**
$_mon$ selects a budgeted set

$$
q_t=TopK(\h:s_mon(h t)_mon\, K_t),
$$

optionally refined by an LLM call that may add or drop channels given $(v_t,P_t^open)$. Unlike fixed auto-heartbeats every $30$/$60$ virtual minutes, queries are *intention-conditioned*: channels with no open dependents are not polled, reducing monitoring overhead and lure-driven over-acting. Unlike pure optional heartbeats, the default is proactive whenever $s_mon$ exceeds threshold---addressing under-monitoring of non-clock channels.

**Stopping.**
After returns $r_t$, the monitor may issue a second micro-round only if new evidence raises $s_mon$ for a still-unread channel (e.g., email hints at a portal). Hierarchical union-query baselines often fail by never converting extra reads into correct $D_t$; ProMem feeds $r_t$ directly into the scorer below.

## Due-Set Scorer

Given evidence $e_t=(v_t,r_t)$ and candidate handles $X_t$ (true actions and lures), the scorer $_due$ outputs $D_t X_t$.

**Candidate generation.**
For each $x X_t$, retrieve matching intentions $M(x)_t^open$ by handle identity or fuzzy label match. Lures typically have $M(x)=$ or only weak lexical overlap with inactive/canceled records.

**Scoring.**
For each $x$,

$$
s_due(x e_t)=
_I(x)
(
sat((I),e_t)
-
_life((I))
-
_lure(x)
),
$$

where $sat[0,1]$ is an LLM- or rule-based satisfaction score of trigger $$ under evidence $e_t$; $pen$ heavily penalizes canceled/completed and mildly penalizes stale modified shells; $lure(x)$ is high when $x$ is not grounded in any open $I$. Then

$$
D_t=\x X_t:s_due(x e_t)_due\.
$$

Threshold $_due$ traces a precision--recall curve: lower values raise recall (and FP), higher values favor conservative precision. ProMem tunes $_due$ (and $_mon$) on a small development week when available; otherwise a prompted self-consistency vote approximates the threshold.

**Why this helps Set-F1.**
Auto-heartbeats increase the chance that $sat$ is evaluated with fresh clock evidence, but without PIS grounding they also increase spurious $sat$ on lures. Explicit $pen()$ and $lure(x)$ terms target the FP explosion observed when monitoring is decoupled from intention state [pmbench2026].

## Integration with Ongoing Activity Choice

PM-Bench requires a mandatory ongoing activity $c_t_t$ every step. ProMem does not replace this choice; it conditions it lightly on open intentions:

$$
_act(c_t) LLM(v_t,C_t,brief(P_t^open)),
$$

where $brief()$ lists only time-critical or narrative-linked commitments so the model prefers activities compatible with imminent dues when the vignette allows. The due decision $D_t$ remains separate: agents may (and often must) both progress an unrelated ongoing task and fire a due intention in the same step---matching human PM dual-task structure.

**End-to-end step.**
(1) Update PIS/episodic bank from $o_t$ via $$ (ingest announces/updates). (2) Run $_mon$ to obtain $r_t$. (3) Score dues with $_due$. (4) Choose $c_t$ with $_act$. (5) Commit $a_t$, then finalize lifecycle transitions (fired/completed). Pseudocode appears as Algorithm [alg:promem].

## Design Rationale Relative to PM-Bench Scaffolds

    
- **vs.\ Single:** adds external conditional state so the backbone need not hold all open $$ only in the context window.
    
- **vs.\ Todo-ledger:** ledger text is replaced by typed $(,,)$ records consumed by monitor and scorer APIs, not only by unstructured reading.
    
- **vs.\ Heartbeats:** monitoring is allocated by $deps(I)$ and urgency $$, aiming for higher channel hit per query and fewer FP.
    
- **vs.\ Hierarchical union-query:** a single coordinated PIS avoids fragmented commitments across subagents that PM-Bench found harmful for cross-day hit.

---


# Experiments

We design experiments to test whether conditional memory---as implemented by ProMem---improves prospective competence on PM-Bench and related conditional-instruction settings. Reported cells use ``--'' as placeholders pending final runs; qualitative expectations follow each table.

## Experiment Setup

**Primary benchmark: PM-Bench Virtual Week.**
We evaluate on the released PM-Bench week [pmbench2026]: $7$ days, $T=80$ steps, $81$ scored executable tasks (event- and time-based; regular and non-regular), including channel-triggered, cross-day, and update events, plus lure actions and hidden channels. Agents follow the official query-then-act protocol and replay-based evaluator so that due sets $\D_t\$ and scoring are identical across systems.

**Metrics.**

    
- **Set-F1** (primary), with cumulative TP / FP / FN as in Eqs. (eq:set-f1).
    
- **FP / FN** counts (operating-point diagnostics).
    
- **Channel hit**: hit rate on hidden-channel-required dues.
    
- **Cross-day hit**: hit rate on intentions announced on an earlier day than the cue.
    
- **Update-sensitive hit**: hit rate on tasks affected by cancel / reschedule / override.
    
- **Monitoring overhead**: number of channel queries issued over the week.

We also report narrative-cued and clock-required slices when available for analysis.

**Backbones.**
Following PM-Bench, we plan multiple backbones spanning closed and open models (e.g., GPT-family and open 8B--70B-class models). Each backbone→scaffold pair is a separate run; macro averages mirror the benchmark's reporting style.

**Baselines.**
We compare against the scaffolds studied in PM-Bench [pmbench2026]:

    
- **Single**: one model, no external memory beyond the prompt.
    
- **Todo-ledger**: in-context ledger of pending intentions, cues/times, and completion bits.
    
- **Optional heartbeat**: model may enable periodic self-reminders to re-check channels.
    
- **Auto-heartbeat (60m / 30m)**: fixed periodic wakes.
    
- **Hierarchical union-query**: coordinator with subagents proposing queries; union then final action.

**ProMem** uses dual stores + lifecycle + $_mon$ + $_due$ as in Section [sec:methods].

**Implementation notes.**
Prompts, PIS schemas, and thresholds $(_mon,_due,K_t)$ will be detailed in the appendix upon release. Unless noted, base model weights are frozen; ProMem is an inference-time controller.

## Main Results on PM-Bench

```
table[h]

*Table/Figure: PM-Bench primary results (placeholders). Higher Set-F1 / hits are better; lower FP and monitoring overhead are better when Set-F1 is held fixed. ``--'' = pending.*

3pt

tabularl|ccccccc

**Method** & Set-F1$$ & FP$$ & FN$$ & Chan.\ hit$$ & Cross-day$$ & Update$$ & Queries$$ 

Single & -- & -- & -- & -- & -- & -- & -- 

Todo-ledger & -- & -- & -- & -- & -- & -- & -- 

Optional heartbeat & -- & -- & -- & -- & -- & -- & -- 

Auto-heartbeat 60m & -- & -- & -- & -- & -- & -- & -- 

Auto-heartbeat 30m & -- & -- & -- & -- & -- & -- & -- 

Hierarchical union-query & -- & -- & -- & -- & -- & -- & -- 

ProMem (ours) & -- & -- & -- & -- & -- & -- & -- 

tabular

table
```

**Expected findings.**
We expect ProMem to achieve the best or near-best **Set-F1** by improving the precision--recall operating point relative to auto-heartbeats (which historically raise update hit at the cost of large FP) and hierarchical querying (high query count, weak channel→action conversion). Gains should concentrate on **channel hit** and **cross-day hit**, where intention-conditioned monitoring and persistent PIS state are most relevant, and on **update-sensitive hit**, where lifecycle penalties suppress stale fires after cancel/reschedule. Monitoring overhead should lie below hierarchical union-query and ideally near optional-heartbeat efficiency while exceeding its channel coverage.

## Ablation Study

```
table[h]

*Table/Figure: ProMem ablations on PM-Bench (placeholders). Each row removes one component.*

4pt

tabularl|ccccc

**Variant** & Set-F1 & Chan.\ hit & Cross-day & Update & Queries 

Full ProMem & -- & -- & -- & -- & -- 

  w/o PIS (flat episodic only) & -- & -- & -- & -- & -- 

  w/o proactive monitor & -- & -- & -- & -- & -- 

  w/o lifecycle updates & -- & -- & -- & -- & -- 

  Retrospective-RAG-only & -- & -- & -- & -- & -- 

tabular

table
```

**Ablation definitions.**

    
- **w/o PIS:** intentions written only into the episodic bank; no typed $(,,)$ store.
    
- **w/o proactive monitor:** no $_mon$; channels queried only if the backbone spontaneously requests them (Single-like monitoring).
    
- **w/o lifecycle updates:** cancel/reschedule/override text is stored but $$ / $$ are not rewritten---stressing update-sensitive FP/FN.
    
- **Retrospective-RAG-only:** retrieve top-$k$ episodic snippets each step and ask the model for dues, with no PIS, monitor policy, or lifecycle API.

**Expected findings.**
Removing PIS or using retrospective-RAG-only should hurt cross-day and overall Set-F1 (commitments get buried). Removing the proactive monitor should collapse channel hit. Disabling lifecycle updates should specifically degrade update-sensitive hit and inflate FP after cancels. Full ProMem should dominate all ablations on Set-F1.

## Secondary: Synthetic Conditional Instruction Suite

Beyond Virtual Week, we construct a compact synthetic suite of conditional instructions in tool-using dialogues (e.g., ``when ticket price $<\$X$, buy''; ``if package ships, email me; if canceled, do nothing''). Metrics mirror Set-F1 over discrete decision points, plus false-alarm rate under lure messages.

```
table[h]

*Table/Figure: Synthetic conditional-instruction suite (placeholders).*

4pt

tabularl|cccc

**Method** & Set-F1$$ & FP$$ & FN$$ & False-alarm rate$$ 

Single & -- & -- & -- & -- 

Todo-ledger & -- & -- & -- & -- 

Optional heartbeat & -- & -- & -- & -- 

Retrospective-RAG-only & -- & -- & -- & -- 

ProMem (ours) & -- & -- & -- & -- 

tabular

table
```

**Expected findings.**
ProMem should transfer: higher Set-F1 and lower false alarms than RAG-only and Single, with less over-firing than heartbeat-style rechecks when conditions are unmet.

## Operating-Point Analysis

*[Figure placeholder]*

Spammy monitors can move along a recall-heavy frontier with poor precision. We will plot Set-F1 against FP and against query count. **Expected finding:** ProMem's intention-conditioned $_mon$ and lure-aware $_due$ yield a superior operating point to auto-heartbeat-30m (high update hit, high FP) and to majority-style over-aggregation reported in PM-Bench.

## Discussion of Failure Modes (Anticipated)

We anticipate residual errors when trigger language is ambiguous, when multiple channels interact, or when the backbone mis-parses update referents. Hierarchical fragmentation should be avoided by design, but a single corrupted PIS write could persist; checksum prompts and double-entry of cancel events are mitigations to test.

---


# Conclusion

We argued that LLM agents need *conditional memory*---structured deferred intentions $(,,)$---in addition to retrospective episodic stores optimized for needle retrieval. Anchoring on PM-Bench's prospective Virtual Week evaluation, we proposed **ProMem**: dual stores with a Prospective Intention Store, an explicit lifecycle manager, a proactive trigger monitor for hidden channels, and a due-set scorer integrated with ongoing activity choice. The design directly targets documented failure modes: under-monitoring of channels, weak cross-day commitment, brittle updates, and poor precision--recall under heartbeat spam. Empirically confirming these gains on PM-Bench and synthetic conditional instructions is our immediate next step; broader future work includes learned monitor policies, multi-agent sharing of conditional records, and tighter integration with retrospective memory for mixed query-and-act workloads.

---


# Appendix

.subsection

# A. Algorithm of ProMem

Algorithm [alg:promem] summarizes one Virtual Week episode under the PM-Bench query-then-act protocol (Section [sec:methods]). Dual memory, lifecycle updates, monitoring, and due-set scoring are explicit; the backbone LLM is invoked inside $ParseAnnounce$, $Sat$, $IsLure$, and activity choice as needed.

```
algorithm[h]

*Table/Figure: ProMem on a PM-Bench episode*

**Input**: Episode horizon $T$; channel set $H$; thresholds $_mon,_due$; query budget schedule $\K_t\$; backbone LLM $f$

**Output**: Actions $\a_t=(c_t,D_t)\_t=1^T$; metrics via official evaluator

**Init**: $E_0$, $P_0$

```
algorithmic[1]
$t=1$ to $T$
 Observe $o_t(v_t,C_t,X_t)$ vignette, ongoing menu, action handles
 $(P_t,E_t)(P_t-1,E_t-1,o_t)$ 
 parse new $I=(,,,meta)$; apply cancel/reschedule/override to $,$
 $P_t^open\I_t:(I)\active,modified\\$
$h$
 $s_mon(h)_I_t^open w(I) 1[h(I)] (I,t)$

 $q_t(\h:s_mon(h)_mon\,K_t)$; optionally refine $q_t$ with $f$
 $r_t(q_t)$; $E_t_t(r_t)$
 $e_t(v_t,r_t)$
$x X_t$
 $M(x)(x,P_t^open)$
 $s_due(x)_I(x)(Sat((I),e_t)-_lifePen((I))-_lureIsLure(x))$
 if $M(x)=$, take $s_due(x) -_lureIsLure(x)$

 $D_t\x X_t:s_due(x)_due\$
 $c_t(f;v_t,C_t,Brief(P_t^open))$
 Submit $a_t(c_t,D_t)$
 $P_t(P_t,D_t)$ active→fired/completed as applicable

 **return** $\a_t\$; compute Set-F1, hits, query count with replay evaluator
algorithmic
```

algorithm
```

# B. Additional Formal Notes

## B.1 Trigger satisfaction

For time-based intentions, $Sat(,e_t)=1$ iff the clock channel (if read) or officially exposed step time lies in the target window. For event-based intentions, $Sat$ is an entailment judgment between cue descriptors and $v_t$. For channel-based intentions, $Sat=0$ unless the required $h$ was queried and the return matches $$; this encodes the monitoring bottleneck in the scorer itself.

## B.2 Relation to Set-F1 gradients (informal)

Raising $_due$ decreases expected FP and increases FN; raising monitoring budget $K_t$ increases the chance that channel-based $Sat$ flips from $0$ to $1$, lowering FN at some FP risk if lure handles share lexical features with true tasks. ProMem's $IsLure$ and lifecycle penalties are designed to flatten that FP risk.

# C. Implementation Checklist

**PIS schema fields.** `id`, `trigger_type`, `trigger_spec`, `action_handle`, `state`, `announce_step`, `deps`, `gloss`.

**Update events.** Detect cancel / reschedule / override spans; map references to `id`; rewrite `trigger_spec` or set `state=canceled`.

**Logging.** Record $q_t$, $r_t$, $D_t$, and PIS snapshots for slice metrics (channel / cross-day / update).

**Hyperparameters (defaults TBD).** $_mon$, $_due$, $K_t$, $_life$, $_lure$, urgency schedule $$.

# D. Extended Experimental Placeholders

```
table[h]

*Table/Figure: Per-backbone Set-F1 on PM-Bench (placeholders).*

tabularl|cccc

**Scaffold** & Backbone A & Backbone B & Backbone C & Macro 

Optional heartbeat & -- & -- & -- & -- 

Todo-ledger & -- & -- & -- & -- 

ProMem & -- & -- & -- & -- 

tabular
table
```

 Expected pattern (from PM-Bench): scaffold rank may interact with backbone; ProMem should reduce variance by externalizing $$ and $$ rather than relying on in-context vigilance alone.

---
