# Meeting Notes: rejectOnClear design review

Date: 2026-02-17
Owner: LimitKit Tech Lead
Attendees: LimitKit Product Owner, LimitKit Tech Lead, QA Lead, Payments Platform Lead

## Discussion

The group reviewed CR-101. The option is accepted as a boolean validated at construction. A non-boolean value throws TypeError with the text "Expected rejectOnClear to be a boolean".

## Decisions

The rejection reason is the abort reason produced by `AbortSignal.abort().reason`, so callers can detect it as an AbortError. Default stays `false`.

## Actions

QA Lead writes the test for clearQueue with rejection. Open: whether to document the deadlock warning for nested use of the same limiter in the readme.
