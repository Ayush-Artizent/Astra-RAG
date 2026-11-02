# CLI Help UX Guidelines

Date: 2026-04-22
Owner: Documentation Lead

## Help Layout

Help output shows Usage, then description, Options, and since 8.5.0 a `Positional arguments` section when argument help is available.

## Error Messages

From 8.6.0 errors name an option by its spec, for example `The option '--my-option' is deprecated.`

## Width

Help text wraps at a maximum of 80 columns minus 2, with a floor of 50.
