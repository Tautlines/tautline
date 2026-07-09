# Minervit demo: an agent tries to push before the CI test gate is wired,
# gets blocked by the real pre-push guard, wires the gate, and pushes again
# once it is green. Run from the repository root: vhs docs/assets/demo.tape
# All setup runs the actual minervit-methodology CLI from this checkout
# (bin/minervit-methodology) against a scratch project + local bare remote;
# nothing in this tape is typed fiction.
Output "docs/assets/demo.gif"

Set Shell "bash"
Set FontSize 16
Set Width 848
Set Height 500
Set Padding 10
Set TypingSpeed 30ms
Set Framerate 12

Hide
Type "MM=$(pwd)/bin/minervit-methodology"
Enter
Type "DEMO_DIR=$(mktemp -d)"
Enter
Type "git init -q --bare $DEMO_DIR/origin.git"
Enter
Type "mkdir -p $DEMO_DIR/project/tests && cd $DEMO_DIR/project"
Enter
Type "git init -q -b main"
Enter
Type "git config user.email demo@minervit.com && git config user.name Demo"
Enter
Type "git remote add origin $DEMO_DIR/origin.git"
Enter
Type "printf 'def add(a, b):\n    return a + b\n' > app.py"
Enter
Type "printf 'from app import add\n\ndef test_add():\n    assert add(2, 2) == 4\n' > tests/test_app.py"
Enter
Type "git add -A && git commit -q -m 'Initial commit'"
Enter
Type "$MM init --target . >/dev/null 2>&1"
Enter
Type "perl -pi -e 's/BOOTSTRAP REQUIRED/ready for launch/g' .ai-work/ADAPTER_BOOTSTRAP_INTERVIEW.md"
Enter
Type "$MM init --target . --continue >/dev/null 2>&1"
Enter
Type "git add -A && git commit -q -m 'Add Minervit adapter' >/dev/null"
Enter
Type "printf 'name: tests\non: [push, pull_request]\njobs:\n  test:\n    runs-on: ubuntu-latest\n    steps:\n      - uses: actions/checkout@v4\n      - run: pytest\n' > $DEMO_DIR/tests-workflow-fixture.yml"
Enter
Type "clear"
Enter
Sleep 500ms
Show

Type "echo 'agent: implementation complete, pushing now.'"
Enter
Sleep 700ms

Type "git push origin main"
Enter
Sleep 2.5s

Type "mkdir -p .github/workflows && cp $DEMO_DIR/tests-workflow-fixture.yml .github/workflows/tests.yml"
Enter
Sleep 500ms

Type "git add -A && git commit -q -m 'Wire CI test workflow'"
Enter
Sleep 500ms

Type "git push origin main"
Enter
Sleep 2.5s

Sleep 2s
