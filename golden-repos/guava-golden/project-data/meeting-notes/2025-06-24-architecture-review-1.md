# Meeting Notes: Architecture review 1

Date: 2025-06-24
Owner: Platform Architect
Attendees: Platform Architect; Core Collections Lead; Security Architect; Data Platform Lead

## Topics

Review of package layout, the CacheFactory wrapper over CacheBuilder and LoadingCache, and the hashing facade over Hashing.

## Decisions

ADR-014 accepted: default maximumSize 10,000. ADR-015 accepted: all platform executors expose ListeningExecutorService via MoreExecutors.

## Open items

Open: whether to expose Striped locks in the public facade. Open: the event bus choice between EventBus and an internal broker.
