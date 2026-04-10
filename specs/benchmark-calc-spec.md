# Spec: Benchmark Task -- Expression Evaluator

## Status

Approved

## Goal

Provide a standardized, non-trivial coding task for benchmarking local Ollama models through the agentic TDD pipeline. This spec is fed to the pipeline as the task that models must implement. It is intentionally harder than the smoke-test spec to differentiate model capability.

## Why This Task

An arithmetic expression evaluator tests multiple skills simultaneously:

- **Multi-layer architecture**: tokenizer, parser, evaluator -- the model must design interacting components.
- **Algorithmic reasoning**: operator precedence and parentheses require recursive or precedence-climbing logic.
- **Error handling**: malformed input, division by zero, unmatched parens.
- **Type design**: custom exception, dataclasses/types for tokens and AST nodes.
- **Objective verification**: every expression has exactly one correct numeric answer.

## Scope

Create a module `src/spec_driven_dev_pipeline/utils/calc.py` with supporting types and functions.

## Requirements

### Types

#### `CalcError(Exception)`

Custom exception for all evaluator errors (invalid input, division by zero, syntax errors).

#### `Token`

A dataclass with two fields:

- `kind: str` -- one of `"NUMBER"`, `"PLUS"`, `"MINUS"`, `"STAR"`, `"SLASH"`, `"LPAREN"`, `"RPAREN"`.
- `value: str` -- the raw text that produced this token (e.g. `"3.14"`, `"+"`, `"("`).

#### `Expr` (base class)

Abstract base for AST nodes. Concrete subclasses:

- `Number(value: float)` -- a numeric literal.
- `BinOp(op: str, left: Expr, right: Expr)` -- binary operation (`+`, `-`, `*`, `/`).
- `UnaryOp(op: str, operand: Expr)` -- unary operation (currently only `-`).

### Functions

#### `tokenize(expression: str) -> list[Token]`

- Splits the expression string into a list of `Token` objects.
- Skips whitespace.
- Recognizes integer and float literals (e.g. `42`, `3.14`, `.5`, `0.0`).
- Recognizes operators: `+`, `-`, `*`, `/`.
- Recognizes parentheses: `(`, `)`.
- Raises `CalcError` if the expression is empty or contains unrecognized characters.

#### `parse(tokens: list[Token]) -> Expr`

- Builds an AST from the token list, respecting operator precedence:
  1. Parentheses (highest)
  2. Unary minus
  3. `*`, `/` (left-associative)
  4. `+`, `-` (left-associative, lowest)
- Raises `CalcError` for syntax errors: unexpected tokens, missing operands, unmatched parentheses.

#### `evaluate(expr: Expr) -> float`

- Recursively evaluates the AST and returns a `float`.
- Raises `CalcError` on division by zero.

#### `calc(expression: str) -> float`

- Convenience function: `tokenize` -> `parse` -> `evaluate`.
- Returns the result as a `float`.
- Any `CalcError` from sub-steps propagates unchanged.

## Acceptance Criteria

### AC-1: Basic arithmetic

- `calc("2 + 3")` returns `5.0`
- `calc("10 - 4")` returns `6.0`
- `calc("6 * 7")` returns `42.0`
- `calc("15 / 4")` returns `3.75`

### AC-2: Operator precedence

- `calc("2 + 3 * 4")` returns `14.0`
- `calc("10 - 2 * 3")` returns `4.0`
- `calc("8 / 4 + 1")` returns `3.0`

### AC-3: Parentheses

- `calc("(2 + 3) * 4")` returns `20.0`
- `calc("10 / (2 + 3)")` returns `2.0`

### AC-4: Nested parentheses

- `calc("((1 + 2) * (3 + 4))")` returns `21.0`
- `calc("(((5)))")` returns `5.0`

### AC-5: Unary minus

- `calc("-5")` returns `-5.0`
- `calc("-(3 + 2)")` returns `-5.0`
- `calc("3 * -2")` returns `-6.0`

### AC-6: Float literals

- `calc("3.14 * 2")` returns `6.28`
- `calc(".5 + .5")` returns `1.0`
- `calc("0.1 + 0.2")` returns approximately `0.3` (float tolerance)

### AC-7: Complex expressions

- `calc("2 + 3 * 4 - 6 / 2")` returns `11.0`
- `calc("(2 + 3) * (4 - 1) / 3")` returns `5.0`

### AC-8: Division by zero

- `calc("1 / 0")` raises `CalcError`
- `calc("5 / (3 - 3)")` raises `CalcError`

### AC-9: Invalid input

- `calc("")` raises `CalcError` (empty expression)
- `calc("2 +")` raises `CalcError` (missing operand)
- `calc("abc")` raises `CalcError` (unrecognized characters)
- `calc("2 3")` raises `CalcError` (missing operator)

### AC-10: Unmatched parentheses

- `calc("(2 + 3")` raises `CalcError`
- `calc("2 + 3)")` raises `CalcError`
- `calc(")(")` raises `CalcError`

## Comparison to Smoke Test

| Dimension | Smoke Test | This Benchmark |
|-----------|-----------|----------------|
| Functions | 2 | 4 + 3 types |
| Acceptance criteria | 4 | 10 |
| Logic depth | Trivial (stdlib wrappers) | Multi-pass (tokenize/parse/evaluate) |
| Error cases | 1 (negative seed) | 3 categories (div-zero, syntax, invalid) |
| Abstraction layers | 1 file, flat | 1 file, layered (types + functions) |

## Package Layout

```
src/spec_driven_dev_pipeline/
  utils/
    __init__.py
    calc.py          # CalcError, Token, Expr, Number, BinOp, UnaryOp,
                     # tokenize, parse, evaluate, calc
```
