import os
from pydantic import BaseModel, Field
from typing import Dict, Any
from pydantic_ai import Agent
import json

class ApplicationFormMapping(BaseModel):
    """Pydantic model defining the expected output from the LLM."""
    mappings: Dict[str, str] = Field(
        description="A dictionary mapping exact Playwright/CSS locators to the actual text string value from the user profile that should be entered in that field."
    )

def _get_agent() -> Agent:
    return Agent(
        model='gemini-1.5-flash',
        result_type=ApplicationFormMapping,
        system_prompt=(
            "You are an expert ATS automation bot parser. "
            "You will receive a raw HTML snippet of an application form and a JSON representation of a user's profile. "
            "Your critical task is to return a dictionary mapping the exact, precise CSS locators for the input fields "
            "to the correct string value from the user profile that should be entered in that field. "
            "Only map fields where you are highly confident. "
            "Ignore hidden inputs, non-interactive text, or fields not requested in the profile data. "
            "Use precise locators (like 'input[name=\"firstName\"]' or '#email')."
        ),
    )

async def extract_fields(html_blob: str, user_profile: Dict[str, Any]) -> ApplicationFormMapping:
    """
    Uses the Gemini Agent to map profile data against dynamic HTML locators.
    """
    if not os.environ.get("GEMINI_API_KEY"):
        raise ValueError("GEMINI_API_KEY environment variable is missing. The Pydantic LLM mapper cannot run.")
        
    profile_json = json.dumps(user_profile, indent=2)
    prompt = f"USER PROFILE:\n{profile_json}\n\nHTML BLOB:\n{html_blob}"
    
    agent = _get_agent()
    # Execute the agent asynchronously; Pydantic AI handles the structured retry validation
    result = await agent.run(prompt)
    return result.data
