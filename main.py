"""Command Line Interface (CLI) entry point for the AI API Testing Agent."""

import argparse
import sys
from config.settings import get_settings
from core.loop_orchestrator import IterativeQAOrchestrator
from models.schemas import IterationResult


def parse_arguments():
    settings = get_settings()
    parser = argparse.ArgumentParser(
        description="AI API Testing & Iterative Self-Improving QA Agent (Reflection Design Pattern)"
    )
    parser.add_argument(
        "--spec",
        default=settings.OPENAPI_SPEC_PATH,
        help="Path or URL to OpenAPI specification (JSON/YAML)",
    )
    parser.add_argument(
        "--url",
        default=settings.TARGET_API_BASE_URL,
        help="Base URL of the target API under test",
    )
    parser.add_argument(
        "--max-iterations",
        type=int,
        default=settings.MAX_REFLECTION_ITERATIONS,
        help="Maximum reflection & refinement iterations to perform",
    )
    parser.add_argument(
        "--target-coverage",
        type=float,
        default=settings.TARGET_COVERAGE_PERCENT,
        help="Target scenario coverage percentage to achieve",
    )
    parser.add_argument(
        "--target-quality",
        type=float,
        default=settings.TARGET_QUALITY_SCORE,
        help="Target quality score (0.0 to 1.0) to achieve",
    )
    parser.add_argument(
        "--sandbox",
        action="store_true",
        default=settings.ENABLE_DOCKER_SANDBOX,
        help="Execute test runs in isolated Docker container",
    )
    return parser.parse_args()


def cli_callback(event: str, data: any):
    """Render real-time CLI event feedback."""
    if event == "spec_parsing":
        print(f"\n[*] Parsing OpenAPI specification: {data['spec_path']}")
    elif event == "spec_parsed":
        print(f"[+] Loaded API: {data.title} (v{data.version}) | Found {len(data.endpoints)} endpoints")
    elif event == "v1_generation_start":
        print("\n[*] Synthesizing baseline test suite (V1)...")
    elif event == "v1_generated":
        print(f"[+] Baseline suite generated with {len(data.test_cases)} tests across diverse scenarios.")
    elif event == "iteration_start":
        print(f"\n{'=' * 65}")
        print(f"[*] Cycle {data['iteration']}: Suite {data['suite_version']}")
        print(f"{'=' * 65}")
    elif event == "execution_start":
        print(f"[*] Executing {data['tests_count']} test cases against target API...")
    elif event == "execution_completed":
        res: IterationResult = data
        print(f"[+] Execution completed in {res.execution_time_seconds:.2f}s")
        print(f"    Passed: {res.passed_count} | Failed: {res.failed_count} | Errors: {res.error_count}")
        print(f"    Scenario Coverage: {res.coverage_percentage:.1f}% | Edge Cases: {res.edge_cases_count}")
    elif event == "reflection_completed":
        ref = data
        print(f"\n[*] Reflection Feedback (Quality Score: {ref.quality_score:.2f}/1.00):")
        if ref.missing_scenarios:
            print(f"    Missing Scenarios ({len(ref.missing_scenarios)}):")
            for ms in ref.missing_scenarios[:4]:
                print(f"      - {ms}")
            if len(ref.missing_scenarios) > 4:
                print(f"      ... and {len(ref.missing_scenarios) - 4} more")
        if ref.identified_issues:
            print(f"    Actionable Issues ({len(ref.identified_issues)}):")
            for issue in ref.identified_issues[:3]:
                print(f"      - [{issue.category}] {issue.observation}")
    elif event == "iteration_halted":
        print(f"\n[!] Stopping condition triggered: {data['reason']}")
    elif event == "improvement_completed":
        print(f"[+] Generated improved suite {data.suite_version} ({len(data.test_cases)} tests) with new edge cases.")


def main():
    args = parse_arguments()
    print("=" * 65)
    print("AI API Testing & Iterative Self-Improving QA Agent")
    print("Core Concept: Execution-Grounded Reflection Design Pattern")
    print("=" * 65)

    orchestrator = IterativeQAOrchestrator(
        enable_sandbox=args.sandbox,
    )

    try:
        spec, history, comparison = orchestrator.run(
            spec_path=args.spec,
            target_url=args.url,
            max_iterations=args.max_iterations,
            target_coverage=args.target_coverage,
            target_quality=args.target_quality,
            callback=cli_callback,
        )

        print("\n" + "=" * 65)
        print("=== Iterative QA Lifecycle Final Evaluation ===")
        print("=" * 65)
        print(comparison.summary)
        print(f"\nBaseline (V1) Tests:  {comparison.v1_total} (Coverage: {comparison.v1_coverage_percent:.1f}%)")
        print(f"Final Suite Tests:     {comparison.v2_total} (Coverage: {comparison.v2_coverage_percent:.1f}%)")
        print(f"Net Edge Cases Added:  +{comparison.new_edge_cases_count}")
        print(f"Defects Surfaced:      {comparison.defects_detected_delta}")
        if comparison.stopping_reason:
            print(f"Halt Condition:        {comparison.stopping_reason.value}")
        print("=" * 65)

    except Exception as e:
        print(f"\n[ERROR] Pipeline encountered an exception: {e}", file=sys.stderr)
        raise e


if __name__ == "__main__":
    main()
