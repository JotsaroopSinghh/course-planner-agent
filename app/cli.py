import argparse

from app.agent import ask
from app.profile import StudentProfile, load_student_profile


def build_parser():
    # Keep the CLI thin: it only collects user input and passes
    # structured state into the agent.
    parser = argparse.ArgumentParser(
        description=(
            "Ask course-planning questions against a structured "
            "prerequisite dataset."
        )
    )

    parser.add_argument(
        "--dataset",
        help=(
            "Path to a compatible course dataset JSON file. "
            "Defaults to the bundled UAlberta example."
        ),
    )

    parser.add_argument(
        "--profile",
        help=(
            "Path to a student profile JSON file containing "
            "completed_courses and current_courses."
        ),
    )

    parser.add_argument(
        "--completed",
        default="",
        help=(
            "Comma-separated completed courses. Used when "
            "--profile is not provided."
        ),
    )

    parser.add_argument(
        "--current",
        default="",
        help=(
            "Comma-separated current courses. Used when "
            "--profile is not provided."
        ),
    )

    parser.add_argument(
        "--question",
        help=(
            "Run one question and exit. "
            "Omit this flag for interactive mode."
        ),
    )

    parser.add_argument(
        "--trace",
        action="store_true",
        help=(
            "Print Gemini function calls and deterministic tool results."
        ),
    )

    return parser


def build_profile(args) -> StudentProfile:
    # A profile file takes priority over courses entered directly
    # on the command line.
    if args.profile:
        return load_student_profile(args.profile)

    return StudentProfile.from_dict({
        "completed_courses": args.completed,
        "current_courses": args.current,
    })


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)

    # argparse already handles normal CLI errors, so convert profile
    # validation failures into the same readable command-line format.
    try:
        profile = build_profile(args)
    except (TypeError, ValueError) as exc:
        parser.error(str(exc))

    # --question is useful for scripts, demos and quick one-off checks.
    if args.question:
        print(
            ask(
                args.question,
                profile,
                dataset_path=args.dataset,
                trace=args.trace,
            )
        )
        return

    # Without --question, keep the same profile and dataset loaded
    # conceptually across an interactive conversation.
    print("Course Planner Agent")
    print("Type 'exit' or 'quit' to stop.\n")

    while True:
        try:
            question = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if question.lower() in {"exit", "quit"}:
            break

        if not question:
            continue

        answer = ask(
            question,
            profile,
            dataset_path=args.dataset,
            trace=args.trace,
        )

        print(f"Assistant: {answer}\n")


if __name__ == "__main__":
    main()