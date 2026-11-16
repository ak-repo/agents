"""Terminal chat. Run: python main.py [--verbose]"""
import sys

import agent
import db
import tools


def confirm_cli(name: str, args: dict) -> str:
    answer = input(f"\n  ! {tools.describe_action(name, args)}\n  Proceed? [y/N] ").strip().lower()
    return "approved" if answer in ("y", "yes") else "declined"


def main() -> None:
    try:
        agent.check_config()
    except RuntimeError as e:
        sys.exit(str(e))

    db.init_db()
    verbose = "--verbose" in sys.argv
    messages = agent.new_session()  # created ONCE: this list is the conversation memory

    print(f"Expense agent ({agent.MODEL}). Commands: /reset  /quit")
    while True:
        try:
            user = input("\nyou> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not user:
            continue
        if user in ("/quit", "/exit"):
            break
        if user == "/reset":
            messages = agent.new_session()
            print("history cleared")
            continue

        checkpoint = len(messages)
        messages.append({"role": "user", "content": user})
        try:
            result = agent.run_agent(messages, confirm=confirm_cli, verbose=verbose)
        except Exception as e:  # auth, network, model errors
            del messages[checkpoint:]  # drop the half-finished turn so history stays valid
            print(f"error: {e}")
            continue
        print(f"\nagent> {result.text}")


if __name__ == "__main__":
    main()
