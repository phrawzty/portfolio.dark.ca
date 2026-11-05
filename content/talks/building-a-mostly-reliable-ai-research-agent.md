+++
title = "Building a (mostly) reliable AI research agent"
template = "talk.html"
draft = false
+++

<p>This talk is a technical field report from building a multi-model security research agent for scattered public evidence: documentation, blogs, RFCs, source repositories, changelogs, and policy pages. The agent has to produce answers a human reviewer can trust, not just well-formed output. That requirement exposes a useful distinction: whereas operational reliability handles broken runs, malformed JSON, retries, and recovery, epistemic reliability asks whether a model’s claim is actually supported by evidence. I will walk through the controls that work: source scoping, deterministic tooling, citation discipline, runtime evidence trails, repeated-run comparison, task-specific model choice, durable human review, and deliberate sandbox constraints. Non-determinism is treated honestly, as both antagonist and superpower: something to constrain for reproducible results, measure when answers vary, and leverage for truly exploratory research. Attendees will leave with practical patterns for building and evaluating production research agents as evidence systems, not just stochastic answer machines.</p>
