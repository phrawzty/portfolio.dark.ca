+++
title = "Building a (mostly) reliable AI research agent"
date = 2026-09-14T08:00:00+02:00
draft = false
path = "O4crob"
template = "appearance.html"
aliases = ["O4crob/building-a-mostly-reliable-ai-research-agent"]

[extra]
id = "O4crob"
talk = "building-a-mostly-reliable-ai-research-agent"
event = "Infobip Shift"
event_url = ""
location = "Zadar, Croatia"
timezone = "Europe/Zagreb"
virtual = false
deck = "a6882b4fc8de41530d31f8f917a3b58cf5de801eac22aafdb2ac36c14554b1cb"
recording_url = "https://www.youtube.com/live/1afMu66Eik0?si=kGdGa-OPaDXLl4DY&t=8625"
source_url = "https://speaking.dark.ca/O4crob/building-a-mostly-reliable-ai-research-agent"
source_event_id = "ev_xqB8GA"
source_published_on = "2026-05-15 14:55:00"
resources = []
feedback = []
latitude = 44.119371
longitude = 15.231365
+++

<p>This talk is a technical field report from building a multi-model security research agent for scattered public evidence: documentation, blogs, RFCs, source repositories, changelogs, and policy pages. The agent has to produce answers a human reviewer can trust, not just well-formed output. That requirement exposes a useful distinction: whereas operational reliability handles broken runs, malformed JSON, retries, and recovery, epistemic reliability asks whether a model’s claim is actually supported by evidence. I will walk through the controls that work: source scoping, deterministic tooling, citation discipline, runtime evidence trails, repeated-run comparison, task-specific model choice, durable human review, and deliberate sandbox constraints. Non-determinism is treated honestly, as both antagonist and superpower: something to constrain for reproducible results, measure when answers vary, and leverage for truly exploratory research. Attendees will leave with practical patterns for building and evaluating production research agents as evidence systems, not just stochastic answer machines.</p>
