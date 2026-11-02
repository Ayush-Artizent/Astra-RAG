# Prompts and Color UX

Date: 2026-04-22
Owner: Documentation Lead

## Prompts

`click.prompt` and `click.confirm` strip ANSI styles from the prompt when the output stream does not support them.

## Color Arguments

`click.style` and `click.secho` accept the 256-color index 0 (black). Invalid colors raise `ValueError`.

## Open Items

Open: a high-contrast palette guideline is to decide.
