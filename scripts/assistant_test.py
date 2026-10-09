
from offline_ai_companion.core.assistant import Assistant


def main() -> None:
    assistant = Assistant()

    print("=" * 50)
    print("OFFLINE AI COMPANION")
    print("Persistent Memory + Ollama")
    print("=" * 50)

    print("\nCommands:")
    print("  My name is Kevin")
    print("  What is my name?")
    print("  What do people call me?")
    print("  Remember that my project uses Raspberry Pi 5")
    print("  Show my notes")
    print("  Add a task to finish testing")
    print("  Show my pending tasks")
    print("  Type 'exit' to quit.\n")

    while True:
        try:
            query = input("You: ").strip()

            if query.lower() in {"exit", "quit"}:
                print("Assistant stopped.")
                break

            if not query:
                continue

            response = assistant.process(query)

            print(f"\nAssistant: {response}\n")

        except KeyboardInterrupt:
            print("\nAssistant stopped.")
            break

        except (
            ValueError,
            RuntimeError,
            FileNotFoundError,
        ) as exc:
            print(f"\nError: {type(exc).__name__}\n")


if __name__ == "__main__":
    main()
