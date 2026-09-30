# 1. Record architecture decisions

- Status: Accepted
- Date: 2026-09-30

## Context

DataPilot makes decisions whose reasons are not visible in the code: why pagination uses keysets instead of offsets, why AI-generated SQL runs under a separate database role, why tokens are split between the response body and a cookie. Without a record, the reasoning is lost, reviewers have to guess at intent, and settled questions get reopened.

## Decision

We record every significant architecture decision as an Architecture Decision Record (ADR), following the lightweight format described by Michael Nygard.

- ADRs live in `docs/adr/` as Markdown files named `NNNN-short-title.md`, numbered sequentially.
- Each ADR has a status (Proposed, Accepted, Superseded by ADR N, Deprecated), a date, and three sections: Context, Decision and Consequences.
- An ADR is written in the same pull request as the change it describes.
- Accepted ADRs are not rewritten. A changed decision gets a new ADR that supersedes the old one, and the old one's status is updated to point to it.

A decision is significant when it is hard to reverse, affects several parts of the system, or involves a trade-off a reviewer might question.

## Consequences

- The reasoning behind the design is available to reviewers and future maintainers next to the code.
- Writing the context and consequences down forces alternatives to be considered before committing to one.
- There is a small, ongoing cost: each significant change needs a short document, and superseded decisions must be linked.
