# Developer Experience Notes

Date: 2026-03-15
Owner: Documentation Lead

## Readme structure

The readme order is Install, Usage, API, Recipes, FAQ, Related. The first usage sample uses `pLimit(1)` with `Promise.all`.

## Error messages

Messages are written for developers and name the offending option in backticks, for example the rejectOnClear boolean check.

## TypeScript

Type definitions ship in `index.d.ts` and are verified with `tsd` in `index.test-d.ts`.

## Open

Open: add a recipe for using `limit.map` with a Set input. To decide with the Tech Lead.
