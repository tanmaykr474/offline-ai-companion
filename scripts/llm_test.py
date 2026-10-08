
from offline_ai_companion.llm.ollama import OllamaLLM


def main() -> None:
    llm = OllamaLLM()

    print("Local AI Companion")
    print("Type 'exit' to quit.\n")

    while True:
        prompt = input("You: ").strip()

        if prompt.lower() in {"exit", "quit"}:
            break

        if not prompt:
            continue

        try:
            response = llm.generate(prompt)
            print(f"\nAssistant: {response}\n")
        except RuntimeError as exc:
            print(f"\nError: {exc}\n")


if __name__ == "__main__":
    main()
