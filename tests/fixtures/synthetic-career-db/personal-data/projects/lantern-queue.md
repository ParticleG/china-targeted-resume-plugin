# Lantern Queue

## Overview

A fictional internal workload queue built at Orbit Orchard Systems. F1, P0.

## Time and role

2024-02 to 2025-01; contributor in a three-person project team.

## Background and goal

Provide bounded retries and visible delivery state for synthetic batch jobs.

## Personal work

Avery designed the retry state transitions, implemented Python API handlers, and contributed operational dashboards. Other team members owned storage and deployment.

## System architecture

HTTP intake, PostgreSQL state, worker leases, bounded retry queues, and metrics. This architecture is evidence of transferable distributed-systems experience, not robotics experience.

## Engineering and verification

Added deterministic state-transition tests, failure injection for expired leases, and Linux service runbooks.

## Results and metrics

During the beta stage, the team processed approximately 1.8–2.2 million synthetic jobs per month and reduced duplicate execution by roughly 31%. These are approximate team metrics and must not be presented as Avery's sole result.

## Technology stack

Python, PostgreSQL, Linux, Docker, HTTP, Prometheus-compatible metrics.

## Public links

- [Active fictional project page](https://lantern-queue.career-fixture.invalid/project)

## Pending confirmation

Whether the beta metric included replay traffic is F4 and should become a question, not a claim.
