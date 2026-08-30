"""Command-line interface for deterministic targeted-resume operations."""
from __future__ import annotations

from contextlib import contextmanager
import argparse
import json
import os
from pathlib import Path
import sys
from typing import Any, Iterator, Sequence, TextIO

from pydantic import ValidationError

from .growth_roadmap import write_growth_roadmap
from .io import jsonable, read_json
from .models import JdInput, OutputMode, RunRequest
from .pipeline import Pipeline, PipelineError, PipelineResult, SelectionRequired


def _path(value: str) -> Path:
    return Path(value).expanduser()

def _add_generation_arguments(
    command: argparse.ArgumentParser,
) -> None:
    command.add_argument(
        "--source",
        type=_path,
        required=True,
        help=(
            "Read-only career source root or a conventional child such as "
            "company-research."
        ),
    )
    command.add_argument("--company", help="Exact company ID or display name.")
    command.add_argument("--role", help="Exact role ID or title.")
    jd = command.add_mutually_exclusive_group()
    jd.add_argument("--jd-text", help="Offline JD text supplied directly.")
    jd.add_argument(
        "--jd-file",
        type=_path,
        help="Offline UTF-8 JD file (maximum 2 MiB).",
    )
    jd.add_argument(
        "--jd-url",
        help="Explicit HTTPS JD URL to fetch with size/time bounds.",
    )
    command.add_argument(
        "--jd-incomplete",
        action="store_true",
        help="Treat supplied JD text, file, or URL as an incomplete excerpt and keep Tier B.",
    )
    command.add_argument(
        "--application-constraints-file",
        type=_path,
        help="Private JSON array of independently assessed application constraints.",
    )
    command.add_argument(
        "--experience-duration-diagnostics-file",
        type=_path,
        help=(
            "Private JSON array binding audited duration diagnostics to "
            "explicit requirement IDs and selected evidence IDs."
        ),
    )
    command.add_argument(
        "--mode",
        choices=[item.value for item in OutputMode],
        default=OutputMode.TARGETED_APPLICATION.value,
        help="Disclosure/output context (default: targeted_application).",
    )
    command.add_argument(
        "--include-extended-profile",
        action="store_true",
        help="Also generate the opt-in extended three-page profile.",
    )
    command.add_argument(
        "--template",
        choices=("adaptive", "ats-simple", "human-readable"),
        default="adaptive",
        help=(
            "Rendering strategy: adaptive uses ATS single-column for 1p and "
            "human-readable single-column for 2p/3p (default: adaptive)."
        ),
    )
    command.add_argument(
        "--output",
        type=_path,
        required=True,
        help="Output root, separate from the source root.",
    )
    command.add_argument(
        "--language",
        default="zh-CN",
        help="Resume locale (default: zh-CN).",
    )
    command.add_argument(
        "--export-roadmap-handoff",
        action="store_true",
        help="Explicitly include the optional roadmap handoff.",
    )


def _add_ir_json_io(parser: argparse.ArgumentParser, *, output: bool = True) -> None:
    parser.add_argument(
        "--input",
        type=_path,
        help="Private JSON input file; omit to read one JSON object from stdin.",
    )
    if output:
        parser.add_argument(
            "--output",
            type=_path,
            help="Private JSON output file; omit to emit JSON on stdout.",
        )



def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="china-targeted-resume",
        description="Build deterministic, evidence-grounded China-targeted resume artifacts.",
    )
    commands = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")

    companies = commands.add_parser("list-companies", help="List company targets discovered in a career source.")
    companies.add_argument("--source", type=_path, required=True, help="Read-only career source root.")

    roles = commands.add_parser("list-roles", help="List roles for one discovered company.")
    roles.add_argument("--source", type=_path, required=True, help="Read-only career source root.")
    roles.add_argument("--company", required=True, help="Exact company ID or display name.")

    generate = commands.add_parser("generate", help="Generate and validate a complete non-overwriting resume run.")
    _add_generation_arguments(generate)

    guided = commands.add_parser(
        "guided-generate",
        help="Select a discovered company and role interactively, then run the complete generation pipeline.",
    )
    _add_generation_arguments(guided)

    analyze = commands.add_parser("analyze-role", help="Analyze a validated RunRequest JSON and create a run-local dossier.")
    analyze.add_argument("--request", type=_path, required=True, help="Path to a RunRequest JSON file.")

    refresh_role = commands.add_parser("refresh-role", help="Refresh role analysis into a new non-overwriting run.")
    refresh_role.add_argument("--role", type=_path, required=True, help="Existing run or role-dossier directory.")

    refresh_match = commands.add_parser("refresh-match", help="Refresh evidence mappings affected by current source hashes.")
    refresh_match.add_argument("--role", type=_path, required=True, help="Existing run or role-dossier directory.")

    export = commands.add_parser("export-roadmap-handoff", help="Explicitly export confirmed gaps for a separate roadmap workflow.")
    export.add_argument("--role", type=_path, required=True, help="Existing run or role-dossier directory.")
    export.add_argument("--severity", default="Critical,Major", help="Comma-separated severities (default: Critical,Major).")
    export.add_argument("--output", type=_path, required=True, help="Destination roadmap-handoff.json.")

    growth = commands.add_parser(
        "write-growth-roadmap",
        help="Validate a handoff-bound growth plan and write private non-overwriting artifacts.",
    )
    growth.add_argument("--source", type=_path, required=True, help="Read-only career source root used only for output-boundary validation.")
    growth.add_argument("--handoff", type=_path, required=True, help="Private roadmap-handoff.json path.")
    growth.add_argument("--plan", type=_path, required=True, help="Private growth-roadmap plan JSON path.")
    growth.add_argument("--output", type=_path, required=True, help="Private output root outside the source root.")

    evidence = commands.add_parser("build-evidence-map", help="Rebuild the deterministic evidence map for an existing run.")
    evidence.add_argument("--run", type=_path, required=True, help="Existing run directory.")

    validate = commands.add_parser("validate-content", help="Run deterministic content audits for an existing run.")
    validate.add_argument("--run", type=_path, required=True, help="Existing run directory.")

    render = commands.add_parser("render", help="Render a ResumeDocument JSON independently to PDF and preview.")
    render.add_argument("--document", type=_path, required=True, help="resume-document.json path.")
    render.add_argument("--output", type=_path, help="PDF output path (default: resume.pdf beside document).")

    inspect = commands.add_parser("inspect-pdf", help="Inspect an existing PDF independently.")
    inspect.add_argument("--pdf", type=_path, required=True, help="PDF path.")
    inspect.add_argument("--max-pages", type=int, default=2, choices=range(1, 7), metavar="1-6", help="Maximum pages to inspect (default: 2).")
    inspect.add_argument("--document", type=_path, help="Optional ResumeDocument JSON for authoritative inspection expectations.")
    inspect.add_argument("--expected-name", default="", help="Optional candidate name expected in extracted PDF text.")
    discover = commands.add_parser(
        "discover-source-structure",
        help="Discover fence-aware source structure and emit a metadata-only source map.",
    )
    discover.add_argument(
        "--source",
        "--source-root",
        dest="source",
        type=_path,
        required=True,
        help="Read-only Markdown source root.",
    )
    discover.add_argument(
        "--output",
        type=_path,
        help="Private source-map JSON output file; otherwise emit JSON on stdout.",
    )

    source_map = commands.add_parser(
        "validate-source-map",
        help="Re-open source and validate source-map identity, spans, quotes, and policy.",
    )
    source_map.add_argument(
        "--source",
        "--source-root",
        dest="source",
        type=_path,
        required=True,
        help="Read-only Markdown source root.",
    )
    _add_ir_json_io(source_map)

    role_input = commands.add_parser(
        "validate-role-input",
        help="Validate normalized role-input IR and role/company/roadmap separation.",
    )
    _add_ir_json_io(role_input)
    role_input.add_argument("--source", "--source-root", dest="source", type=_path, required=True, help="Read-only Markdown source root.")

    evidence_input = commands.add_parser(
        "validate-evidence-input",
        help="Validate normalized evidence-input IR and policy eligibility boundary.",
    )
    _add_ir_json_io(evidence_input)
    evidence_input.add_argument("--source", "--source-root", dest="source", type=_path, required=True, help="Read-only Markdown source root.")

    approve = commands.add_parser(
        "approve-claims",
        help="Aggregate independent reviews and lock approved claim text.",
    )
    _add_ir_json_io(approve)
    approve.add_argument("--source", "--source-root", dest="source", type=_path, required=True, help="Read-only Markdown source root.")

    generate_ir = commands.add_parser(
        "generate-from-ir",
        help="Compose and render variants exclusively from locked approved claims.",
    )
    _add_ir_json_io(generate_ir)
    generate_ir.add_argument(
        "--source",
        "--source-root",
        dest="source",
        type=_path,
        help="Read-only source root when absent from JSON metadata.",
    )
    generate_ir.add_argument(
        "--output-root",
        "--output-dir",
        dest="output_root",
        type=_path,
        help="Private output root when absent from JSON metadata.",
    )
    generate_ir.add_argument(
        "--include-extended-profile",
        action="store_true",
        default=None,
        help="Opt in to the extended three-page profile.",
    )
    return parser
def _input_payload(path: Path | None) -> dict[str, Any]:
    raw: Any = read_json(path) if path is not None else json.load(sys.stdin)
    if not isinstance(raw, dict):
        raise ValueError("JSON input must be an object")
    return raw


def _result_payload(operation: str, result: Any) -> dict[str, Any]:
    if isinstance(result, PipelineResult):
        payload = result.model_dump(mode="json")
        payload.setdefault("operation", operation)
        return payload
    value = jsonable(result)
    if isinstance(value, dict):
        payload = dict(value)
        payload.setdefault("operation", operation)
        return payload
    return {"operation": operation, "result": value}



def _application_constraints(path: Path | None) -> list[dict[str, Any]]:
    if path is None:
        return []
    payload = read_json(path)
    if not isinstance(payload, list) or not all(isinstance(item, dict) for item in payload):
        raise PipelineError("application constraints file must contain one JSON array of objects")
    return [dict(item) for item in payload]

def _experience_duration_diagnostics(
    path: Path | None,
) -> list[dict[str, Any]]:
    if path is None:
        return []
    payload = read_json(path)
    if not isinstance(payload, list) or not all(
        isinstance(item, dict) for item in payload
    ):
        raise PipelineError(
            "experience duration diagnostics file must contain one JSON array of objects"
        )
    return [dict(item) for item in payload]


def _request_from_generate(args: argparse.Namespace) -> RunRequest:
    return RunRequest(
        source_root=args.source,
        company_ref=args.company,
        role_ref=args.role,
        jd=JdInput(
            text=args.jd_text,
            file=args.jd_file,
            url=args.jd_url,
            complete=False if args.jd_incomplete else None,
        ),
        application_constraints=_application_constraints(args.application_constraints_file),
        experience_duration_diagnostics=_experience_duration_diagnostics(
            args.experience_duration_diagnostics_file
        ),
        output_mode=args.mode,
        language=args.language,
        include_extended_profile=args.include_extended_profile,
        template=args.template,
        output_root=args.output,
        export_roadmap_handoff=args.export_roadmap_handoff,
    )

@contextmanager
def _guided_console() -> Iterator[tuple[TextIO, TextIO]]:
    terminal_paths = ["/dev/tty"]
    try:
        for stream in (sys.stdin, sys.stderr, sys.stdout):
            if not stream.isatty():
                continue
            stream_terminal = os.ttyname(stream.fileno())
            if stream_terminal not in terminal_paths:
                terminal_paths.append(stream_terminal)
    except OSError:
        pass
    terminal_input: TextIO | None = None
    terminal_prompt: TextIO | None = None
    last_error: OSError | None = None
    for path in terminal_paths:
        candidate_input: TextIO | None = None
        try:
            candidate_input = open(
                path,
                "r",
                encoding="utf-8",
            )
            candidate_prompt = open(
                path,
                "w",
                encoding="utf-8",
                buffering=1,
            )
            terminal_input = candidate_input
            terminal_prompt = candidate_prompt
            break
        except OSError as error:
            last_error = error
            if candidate_input is not None:
                candidate_input.close()
    if terminal_input is None or terminal_prompt is None:
        raise PipelineError(
            "guided selection requires an interactive TTY; "
            "pass exact --company and --role for non-interactive use"
        ) from last_error
    with terminal_input, terminal_prompt:
        yield terminal_input, terminal_prompt


def _select_guided_choice(
    label: str,
    choices: Sequence[Any],
    *,
    value_key: str,
    display_key: str,
    input_stream: TextIO,
    prompt_stream: TextIO,
) -> str:
    if not choices:
        raise PipelineError(f"no {label} choices were discovered")
    normalized = [jsonable(choice) for choice in choices]
    if len(normalized) == 1:
        selected = str(normalized[0][value_key])
        print(f"Using only discovered {label}: {selected}", file=prompt_stream)
        return selected
    print(f"Available {label} choices:", file=prompt_stream)
    for index, choice in enumerate(normalized, 1):
        print(
            f"  {index}. {choice[display_key]} [{choice[value_key]}]",
            file=prompt_stream,
        )
    print(
        f"Select {label} by number or exact ID: ",
        end="",
        file=prompt_stream,
        flush=True,
    )
    response = input_stream.readline().strip()
    if not response:
        raise PipelineError(f"{label} selection is required")
    if response.isdecimal():
        index = int(response)
        if 1 <= index <= len(normalized):
            return str(normalized[index - 1][value_key])
    for choice in normalized:
        if response in {
            str(choice[value_key]),
            str(choice[display_key]),
        }:
            return str(choice[value_key])
    raise PipelineError(f"invalid {label} selection: {response}")


def _request_from_guided(
    args: argparse.Namespace,
    pipeline: Pipeline,
    *,
    input_stream: TextIO | None = None,
    prompt_stream: TextIO | None = None,
) -> RunRequest:
    request = _request_from_generate(args)
    company = str(request.company_ref or "").strip()
    role = str(request.role_ref or "").strip()
    if company and role:
        return request
    if (input_stream is None) != (prompt_stream is None):
        raise ValueError(
            "guided input and prompt streams must be provided together"
        )
    if input_stream is None or prompt_stream is None:
        with _guided_console() as (
            terminal_input,
            terminal_prompt,
        ):
            return _request_from_guided(
                args,
                pipeline,
                input_stream=terminal_input,
                prompt_stream=terminal_prompt,
            )
    if not company:
        company = _select_guided_choice(
            "company",
            pipeline.list_companies(request.source_root),
            value_key="company_id",
            display_key="display_name",
            input_stream=input_stream,
            prompt_stream=prompt_stream,
        )
    if not role:
        role = _select_guided_choice(
            "role",
            pipeline.list_roles(request.source_root, company),
            value_key="role_id",
            display_key="title",
            input_stream=input_stream,
            prompt_stream=prompt_stream,
        )
    return request.model_copy(
        update={"company_ref": company, "role_ref": role}
    )


def _dispatch(args: argparse.Namespace, pipeline: Pipeline) -> PipelineResult | dict[str, Any]:
    if args.command == "list-companies":
        choices = pipeline.list_companies(args.source)
        return {"operation": args.command, "companies": jsonable(choices), "count": len(choices)}
    if args.command == "list-roles":
        choices = pipeline.list_roles(args.source, args.company)
        return {"operation": args.command, "roles": jsonable(choices), "count": len(choices)}
    if args.command == "generate":
        return pipeline.generate(_request_from_generate(args))
    if args.command == "guided-generate":
        return pipeline.generate(_request_from_guided(args, pipeline))
    if args.command == "analyze-role":
        return pipeline.analyze_role(RunRequest.model_validate(read_json(args.request)))
    if args.command == "refresh-role":
        return pipeline.refresh_role(args.role)
    if args.command == "refresh-match":
        return pipeline.refresh_match(args.role)
    if args.command == "export-roadmap-handoff":
        severities = [value.strip() for value in args.severity.split(",") if value.strip()]
        return pipeline.export_roadmap_handoff(args.role, args.output, severities)
    if args.command == "write-growth-roadmap":
        return write_growth_roadmap(
            source_root=args.source,
            handoff_path=args.handoff,
            plan_path=args.plan,
            output_root=args.output,
        )
    if args.command == "discover-source-structure":
        return pipeline.discover_source_structure(args.source, output=args.output)
    if args.command == "validate-source-map":
        return pipeline.validate_source_map(
            args.source,
            _input_payload(args.input),
            output=args.output,
        )
    if args.command == "validate-role-input":
        return pipeline.validate_role_input(_input_payload(args.input), source=args.source, output=args.output)
    if args.command == "validate-evidence-input":
        return pipeline.validate_evidence_input(_input_payload(args.input), source=args.source, output=args.output)
    if args.command == "approve-claims":
        return pipeline.approve_claims(_input_payload(args.input), source=args.source, output=args.output)
    if args.command == "generate-from-ir":
        payload = _input_payload(args.input)
        output_root = args.output_root
        stage_output = args.output
        # For this command --output is also a convenient output-root spelling.
        # Existing JSON-file use remains available through --output-root plus
        # --output, while a directory-looking path is treated as the root.
        if output_root is None and stage_output is not None:
            if stage_output.exists() and stage_output.is_dir() or stage_output.suffix == "":
                output_root, stage_output = stage_output, None
        return pipeline.generate_from_ir(
            payload,
            source=args.source,
            output_root=output_root,
            output=stage_output,
            include_extended_profile=args.include_extended_profile,
        )
    if args.command == "build-evidence-map":
        return pipeline.build_evidence_map(args.run)
    if args.command == "validate-content":
        return pipeline.validate_content(args.run)
    if args.command == "render":
        return pipeline.render(args.document, args.output)
    if args.command == "inspect-pdf":
        if args.document is not None:
            return pipeline.inspect_pdf(
                args.pdf,
                max_pages=args.max_pages,
                expected_name=args.expected_name,
                document=args.document,
            )
        return pipeline.inspect_pdf(args.pdf, max_pages=args.max_pages, expected_name=args.expected_name)
    raise PipelineError(f"unsupported command: {args.command}")
 
def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    try:
        args = parser.parse_args(argv)
        result = _dispatch(args, Pipeline())
        payload = _result_payload(args.command, result)
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        return 0
    except SelectionRequired as exc:
        print(json.dumps({"error": str(exc), "selection_required": True, "choices": jsonable(exc.choices)}, ensure_ascii=False, sort_keys=True), file=sys.stderr)
        return 2
    except (PipelineError, ValidationError, FileNotFoundError, NotADirectoryError, PermissionError, json.JSONDecodeError, UnicodeError, OSError, ValueError, KeyError) as exc:
        print(json.dumps({"error": str(exc), "type": type(exc).__name__}, ensure_ascii=False, sort_keys=True), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
