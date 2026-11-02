# Coding Standards

Standards for source code in the LimitKit repository.

## Language and style

Module format and style conventions.

### Module format

The package is ESM only (`"type": "module"`). Do not add CommonJS entry points. Source uses tab indentation and is linted with xo.

### Naming of parameters

Function parameters use the long form `function_` and `arguments_` rather than `fn` and `args`, matching the existing source in `index.js`.

## Validation

How inputs are validated.

### Concurrency validation

Concurrency must be an integer of 1 or more, or `Number.POSITIVE_INFINITY`. Invalid values throw a `TypeError` with the message "Expected `concurrency` to be a number from 1 and up".

### Option validation

`rejectOnClear` must be a boolean or the constructor throws `TypeError`. Validation happens once at construction, and again when the `concurrency` setter is used.

## Error handling

How errors from tasks are treated.

### Task errors

Errors thrown by a task are never swallowed. The caller's promise rejects with the original error, and the limiter continues with the next queued task.
