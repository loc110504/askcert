# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-11-04

### Added

- Three-valued completion-semantics certification with outcomes TRUE, FALSE, and UNKNOWN.
- Subset-minimal supporting certificates for each conclusion.
- Decision-relevant unknowns: identification of the missing evidence that could change the outcome.
- Opposite-outcome witnesses for certified conclusions.
- Nested JSON rule format with the operators `all`, `any`, `not`, `xor`, `implies`, `unless`, and constants.
- Flat list rule format.
- `AskCert` engine, `compile_rules` for reusable compiled rule sets, and batch `certify_many`.
- Stable JSON result schema, version 1.
- Resource limits `max_nodes` and `timeout`, which raise `ResourceLimitExceeded` when exceeded.
- Command-line interface.
- Backward-compatible `Reasoner` and `Rule` session API.

### Changed (vs. the unpublished research prototype)

- Invalid fact values raise `EvidenceError` (a subclass of `ValueError`) instead of `TypeError`.
- Node-limit overflow raises `ResourceLimitExceeded` instead of `MemoryError`.
- Distribution renamed from the provisional `askcert-reasoner` to `askcert`.
- Minimum supported Python version is 3.11.
