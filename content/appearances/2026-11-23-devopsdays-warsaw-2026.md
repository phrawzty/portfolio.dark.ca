+++
title = "Supply Chain Security for DevOps Engineers"
date = 2026-11-23
draft = false
path = "2026-11-23-devopsdays-warsaw-2026"
template = "appearance.html"

[extra]
id = "2026-11-23-devopsdays-warsaw-2026"
talk = "supply-chain-security-for-devops-engineers"
event = "DevOpsDays Warsaw 2026"
event_url = ""
virtual = false
deck = ""
recording_url = ""
place = "warsaw-pl"
+++

You know you depend on open source libraries. You probably even have Dependabot telling you about it loudly and constantly. But your application code is just one layer of a much deeper dependency story. That Terraform module you pulled from the registry? Dependency. The base image your containers run on? Dependency. The GitHub Action that builds and deploys your app? Dependency. The DevOps revolution taught us that everything is code—but we haven't fully reckoned with what that means for security. If everything is code, then everything has dependencies, and every dependency is a link in your supply chain.

This talk will walk through the expanding universe of software supply chain security, from Software Composition Analysis and SBOMs to infrastructure-as-code scanning and build provenance, to show how they're not separate disciplines, but the same set of questions applied at different layers. Where did this come from, what's in it, and can I trust it? The good news: you don't need to become a security expert! Because everything is code, both the patterns and tooling for securing it are converging—you just need to extend the practices you already believe in (version control, automation, policy-as-code, etc).

By looking at security through the lens of engineering workflows, you’ll learn how to shift supply chain defense from a siloed security task into a standard DevOps pipeline feature. Come find out how to secure your ecosystem from commit to production using the principles you already know (bonus: you'll finally learn what all these fancy security acronyms mean, too!).
