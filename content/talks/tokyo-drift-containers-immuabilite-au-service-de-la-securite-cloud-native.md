+++
title = "Tokyo Drift Containers : Immuabilité au service de la sécurité Cloud Native"
template = "talk.html"
draft = false
+++

<p>L’immuabilité est souvent présentée comme un pilier de la sécurité Cloud Native. Pourtant, dans tout environnement Cloud Native (qu’il s’agisse de Kubernetes ou autre), la dérive de conteneur reste fréquente : sidecar mal configuré, debug à chaud, intrusion… Cette dérive silencieuse crée un écart critique entre l’intention et la réalité du runtime.</p>
<p>Ce talk technique explore l’immuabilité non pas comme un principe théorique, mais comme une stratégie opérationnelle applicable à tous les runtimes conformes OCI. Nous verrons comment transformer la gestion des images en une première ligne de défense : multi-stage builds, images Distroless, réduction de surface d’attaque et approche Shift Left.
Nous aborderons ensuite la détection de drift en runtime à l’aide des outils d’observabilité et de sécurité. Enfin, nous présenterons l’approche du « immutable rollback » : remplacer un conteneur compromis par une instance propre plutôt que tenter de le réparer.</p>
<p>Les participants repartiront avec des pratiques concrètes et immédiatement applicables pour renforcer la sécurité de leurs workloads Cloud Native grâce à une stratégie d’immuabilité réellement opérationnelle.</p>
