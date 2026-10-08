from offline_ai_companion.config import (
    APP_NAME,
    APP_ENV,
)


def main() -> None:
    print(f"{APP_NAME} starting...")
    print(f"Environment: {APP_ENV}")


if __name__ == "__main__":
    main()