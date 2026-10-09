
from offline_ai_companion.health.checks import HealthChecker


def main() -> int:
    checker = HealthChecker()
    report = checker.run()
    report.display()

    return 0 if report.ready else 1


if __name__ == "__main__":
    raise SystemExit(main())
