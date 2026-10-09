
from dataclasses import dataclass, field
from enum import Enum


class HealthStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    WARN = "WARN"


@dataclass(frozen=True)
class HealthResult:
    component: str
    status: HealthStatus
    message: str
    required: bool = True


@dataclass
class HealthReport:
    results: list[HealthResult] = field(default_factory=list)

    def add(
        self,
        component: str,
        status: HealthStatus,
        message: str,
        required: bool = True,
    ) -> None:
        self.results.append(
            HealthResult(component, status, message, required)
        )

    @property
    def ready(self) -> bool:
        return all(
            result.status != HealthStatus.FAIL
            for result in self.results
            if result.required
        )

    def display(self) -> None:
        print("\nOffline AI Companion - Health Report")
        print("-" * 48)

        for result in self.results:
            print(
                f"[{result.status.value}] "
                f"{result.component}: {result.message}"
            )

        print("-" * 48)
        print(
            "Overall Status: "
            + ("READY" if self.ready else "NOT READY")
        )
