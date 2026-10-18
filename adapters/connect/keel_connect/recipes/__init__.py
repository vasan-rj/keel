from keel_connect.recipes.generic import GenericRecipe
from keel_connect.recipes.claude_code import ClaudeCodeRecipe

REGISTRY = {r.name: r for r in (GenericRecipe(), ClaudeCodeRecipe())}
