# Example / community stack packs

The skills in this `examples/` directory are **stack-specific and product-specific recipes**, not part of the generic, portable methodology core. They are kept here as worked examples of how to encode a particular technology stack's or product's delivery knowledge as a Claude/Codex skill — and as the seed of a future community/marketplace "stack pack" tier.

## Why these are separate from the core skills

The skills in the parent `skills/` directory (framework-intake, lane-lifecycle, review-before-push, goal-orchestration, and the rest) are **runtime- and stack-neutral**: they enforce the methodology regardless of what you are building. They are the product.

The skills below are **opinionated about a specific stack or app**. A different adopter building on a different stack would replace them, not inherit them:

| Skill | What it is | Why it is not core |
|---|---|---|
| `example-service-preflight/` | Preflight checks tuned to one example app's behavior-spec / build conventions | Encodes one project's preflight expectations, not a generic gate |

## Status and stability

- These are **examples**, not supported core surface. They may change shape or move into a separate community/stack-pack distribution.
- Do not depend on them as part of the stable methodology contract.
- They still load via normal skill discovery (the plugin manifests reference the `skills/` directory, and discovery walks subdirectories), so existing invocations keep working from this new location.

## Adding your own stack pack

To add a stack-specific recipe, create a new subdirectory here with its own `SKILL.md`. Keep core, stack-neutral enforcement in the parent `skills/` directory; keep anything that bakes in a particular stack, vendor, or app under `examples/`.
