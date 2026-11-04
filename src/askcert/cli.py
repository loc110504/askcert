"""Command-line interface: ``askcert certify | evaluate | batch | validate`` (also ``python -m askcert``).

Exit codes: 0 success (UNKNOWN is a valid answer, not an error), 2 invalid input or usage,
3 resource limit exceeded. Errors are one JSON object on stderr; expected errors never print a
traceback.
"""

from __future__ import annotations

import argparse
import math
import os
import sys
from collections.abc import Callable, Iterator, Sequence
from typing import Any, NoReturn

from . import __version__
from .api import AskCert
from .exceptions import AskCertError, EvidenceError, ResourceLimitExceeded, RuleError
from .rules import RuleSet
from .serialization import SCHEMA_VERSION, dumps, load_json

EXIT_OK = 0
EXIT_INVALID_INPUT = 2
EXIT_RESOURCE_LIMIT = 3

_EPILOG = """\
exit codes:
  0  success (the status may be TRUE, FALSE or UNKNOWN)
  2  invalid input or usage (bad rules, evidence, JSON, file, or command line)
  3  resource limit exceeded (--max-nodes / --timeout / recursion); no answer was computed

Errors are printed to stderr as {"error": {"type": ..., "message": ...}}.
"""


class _Parser(argparse.ArgumentParser):
    """ArgumentParser whose usage errors are JSON on stderr with exit code 2."""

    def error(self, message: str) -> NoReturn:
        text = f"{message} (see '{self.prog} --help')"
        print(dumps({"error": {"type": "UsageError", "message": text}}), file=sys.stderr)
        self.exit(EXIT_INVALID_INPUT)


def _max_nodes(text: str) -> int:
    try:
        value = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"invalid integer {text!r}") from None
    if value < 2:
        raise argparse.ArgumentTypeError("must be an integer >= 2")
    return value


def _seconds(text: str) -> float:
    try:
        value = float(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"invalid number {text!r}") from None
    if not 0 < value < math.inf:
        raise argparse.ArgumentTypeError("must be a positive, finite number of seconds")
    return value


def _indent(text: str) -> int:
    try:
        value = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"invalid integer {text!r}") from None
    if value < 0:
        raise argparse.ArgumentTypeError("must be >= 0")
    return value


# -- input ----------------------------------------------------------------------------------
def _read_text(path: str, error: type[AskCertError]) -> str:
    """UTF-8 text of a file, or of stdin for ``-``; I/O problems become ``error``."""
    try:
        if path == "-":
            return sys.stdin.buffer.read().decode("utf-8-sig")
        with open(path, "rb") as handle:
            return handle.read().decode("utf-8-sig")
    except (OSError, UnicodeDecodeError) as exc:
        raise error(f"cannot read {'<stdin>' if path == '-' else repr(path)}: {exc}") from exc


def _evidence(text: str) -> dict[str, Any]:
    data = load_json(text, "evidence")
    if not isinstance(data, dict):
        raise EvidenceError("evidence must be a JSON object mapping atoms to true, false or null")
    return data


def _engine(args: argparse.Namespace) -> AskCert:
    rules = RuleSet.from_json(_read_text(args.rules, RuleError))
    return AskCert(rules, max_nodes=args.max_nodes, timeout=args.timeout)


def _load_evidence(args: argparse.Namespace) -> dict[str, Any] | None:
    return None if args.evidence is None else _evidence(_read_text(args.evidence, EvidenceError))


# -- commands -------------------------------------------------------------------------------
def _cmd_certify(args: argparse.Namespace) -> None:
    engine = _engine(args)
    result = engine.certify(args.goal, _load_evidence(args), witnesses=args.witnesses)
    print(dumps(result.to_dict(), indent=args.indent or None))


def _cmd_evaluate(args: argparse.Namespace) -> None:
    engine = _engine(args)
    status = engine.evaluate(args.goal, _load_evidence(args))
    print(dumps({"schema_version": SCHEMA_VERSION, "goal": args.goal, "status": status.value}))


def _cmd_batch(args: argparse.Namespace) -> None:
    engine = _engine(args)
    text = _read_text(args.cases, EvidenceError)
    line_no = 0

    def cases() -> Iterator[dict[str, Any]]:
        nonlocal line_no
        for number, line in enumerate(text.split("\n"), 1):
            line_no = number  # read by the error handler below
            if line.strip():
                yield _evidence(line)

    label = "<stdin>" if args.cases == "-" else args.cases
    try:  # results are collected first so a bad line prints nothing
        results = engine.certify_many(args.goal, cases(), witnesses=args.witnesses)
    except EvidenceError as exc:
        raise EvidenceError(f"{label}, line {line_no}: {exc}") from exc
    for result in results:
        print(dumps(result.to_dict(), separators=(",", ":")))


def _cmd_validate(args: argparse.Namespace) -> None:
    rules = RuleSet.from_json(_read_text(args.rules, RuleError))
    print(
        dumps(
            {
                "valid": True,
                "schema_version": SCHEMA_VERSION,
                "rules": list(rules.rules),
                "atoms": list(rules.atoms),
            }
        )
    )


# -- parser ---------------------------------------------------------------------------------
def _build_parser() -> argparse.ArgumentParser:
    parser = _Parser(
        prog="askcert",
        description="Certifiable Boolean reasoning under incomplete evidence.\n\n"
        "Decide a goal as TRUE, FALSE or UNKNOWN over every completion of the missing\n"
        "facts, with a subset-minimal certificate, the relevant unknowns and witnesses.",
        epilog=_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=f"askcert {__version__}")
    sub = parser.add_subparsers(dest="command", required=True, metavar="COMMAND", parser_class=_Parser)

    def command(
        name: str,
        handler: Callable[[argparse.Namespace], None],
        summary: str,
        *,
        goal: bool = True,
        engine: bool = True,
    ) -> argparse.ArgumentParser:
        p = sub.add_parser(
            name,
            help=summary,
            description=summary,
            epilog=_EPILOG,
            formatter_class=argparse.RawDescriptionHelpFormatter,
        )
        p.set_defaults(handler=handler)
        p.add_argument("--rules", required=True, metavar="RULES.json", help="rule set (JSON file)")
        if goal:
            p.add_argument("--goal", required=True, help="rule name or base atom to decide")
        if engine:
            p.add_argument(
                "--max-nodes",
                type=_max_nodes,
                default=1_000_000,
                metavar="N",
                help="decision-diagram node limit, >= 2 (default: %(default)s)",
            )
            p.add_argument(
                "--timeout",
                type=_seconds,
                default=None,
                metavar="SECONDS",
                help="time limit in seconds per run (default: none)",
            )
        return p

    p = command("certify", _cmd_certify, "Decide one goal and print the full certification result as JSON.")
    p.add_argument(
        "--evidence",
        metavar="EVIDENCE.json",
        help="evidence object atom -> true/false/null ('-' reads stdin; default: no evidence)",
    )
    p.add_argument(
        "--no-witnesses", dest="witnesses", action="store_false", help="omit witness worlds for UNKNOWN goals"
    )
    p.add_argument(
        "--indent",
        type=_indent,
        default=2,
        metavar="N",
        help="JSON indentation; 0 prints one compact line (default: %(default)s)",
    )

    p = command("evaluate", _cmd_evaluate, "Decide one goal and print only its status.")
    p.add_argument(
        "--evidence",
        metavar="EVIDENCE.json",
        help="evidence object atom -> true/false/null ('-' reads stdin; default: no evidence)",
    )

    p = command(
        "batch", _cmd_batch, "Certify one goal for many evidence objects (JSON Lines in, JSON Lines out)."
    )
    p.add_argument(
        "--cases",
        required=True,
        metavar="CASES.jsonl",
        help="one evidence object per line, blank lines skipped ('-' reads stdin)",
    )
    p.add_argument(
        "--no-witnesses", dest="witnesses", action="store_false", help="omit witness worlds for UNKNOWN goals"
    )

    command(
        "validate", _cmd_validate, "Check a rule set and list its rules and atoms.", goal=False, engine=False
    )
    return parser


def _fail(exc: Exception, code: int, **extra: Any) -> int:
    error = {"type": type(exc).__name__, "message": str(exc), **extra}
    print(dumps({"error": error}), file=sys.stderr)
    return code


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI and return the exit code (the console script exits with it)."""
    try:
        args = _build_parser().parse_args(argv)
    except SystemExit as exc:  # --help, --version and usage errors
        return exc.code if isinstance(exc.code, int) else EXIT_OK
    try:
        args.handler(args)
    except ResourceLimitExceeded as exc:
        return _fail(exc, EXIT_RESOURCE_LIMIT, limit=exc.limit, value=exc.value)
    except AskCertError as exc:
        return _fail(exc, EXIT_INVALID_INPUT)
    except BrokenPipeError:
        # The reader closed the pipe early (e.g. `askcert batch ... | head`): not an error.
        # Point stdout at devnull so the interpreter's final flush does not raise again.
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, sys.stdout.fileno())
        return EXIT_OK
    except KeyboardInterrupt:
        return 130
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
