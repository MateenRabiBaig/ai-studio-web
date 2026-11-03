
import os

import os
from pathlib import Path

from dotenv import load_dotenv
from pydantic_ai import Agent
from pydantic_ai.models.google import GoogleModel
from pydantic_ai.providers.google import GoogleProvider

load_dotenv(Path(__file__).with_name(".env"))

api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")

if not api_key:
    raise RuntimeError(
        "Add GEMINI_API_KEY or GOOGLE_API_KEY to backend/.env"
    )

model = GoogleModel(
    "gemini-3.8-flash",
    provider=GoogleProvider(api_key=api_key),
)


agent = Agent(
    model,
    instructions="""
        You are the AI Studio recipe assistant.

        Help users create useful, delicious, practical recipes.

        The user may provide structured preferences:
        - dietaryPreference
        - maxCookTimeMinutes
        - servings

        Honor these preferences when generating recipes:
        - Vegetarian means no meat or fish.
        - Vegan means no animal-derived ingredients.
        - High protein means prioritize protein-rich ingredients.
        - No restrictions means follow the user's request without a dietary restriction.

        Keep the total preparation and cooking time within the requested limit
        when reasonably possible. Scale ingredient quantities to the requested
        number of servings.

        When creating a recipe, use clean Markdown with:
        1. A descriptive title
        2. Preparation time, cooking time, and servings
        3. A clearly organized ingredients list
        4. Numbered preparation steps
        5. Useful substitutions when appropriate

        Be friendly, concise, and practical.
    """
)
