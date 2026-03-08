import json
import os
import anthropic


async def diagnose(
    expected_tool: str,
    actual_tool: str,
    prompt: str,
    tools: list[dict],
) -> dict:
    expected_desc = next((t["description"] for t in tools if t["name"] == expected_tool), "(no description)")
    actual_desc = next((t["description"] for t in tools if t["name"] == actual_tool), "(no description)")

    async with anthropic.AsyncAnthropic(api_key=os.environ["ANTHROPIC_API_KEY"]) as client:
        response = await client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=512,
            messages=[{
                "role": "user",
                "content": (
                    f"These two MCP tool descriptions are being confused by an LLM.\n\n"
                    f"Expected tool: {expected_tool}\n"
                    f"Description: {expected_desc}\n\n"
                    f"Tool called instead: {actual_tool}\n"
                    f"Description: {actual_desc}\n\n"
                    f'The prompt that caused confusion: "{prompt}"\n\n'
                    f"Explain in 2-3 sentences why these are being confused, then suggest "
                    f"a concrete change to one or both descriptions to disambiguate them.\n"
                    f'Return as JSON: {{"diagnosis": "...", "suggestion": "..."}}'
                ),
            }],
        )

    text = response.content[0].text
    # strip markdown code fences if present
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    return json.loads(text.strip())
