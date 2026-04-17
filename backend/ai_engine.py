"""AI engine for SmartSheet — OpenAI-powered spreadsheet assistant."""

import json
import logging
import os
import shutil
import uuid
from datetime import datetime
from pathlib import Path

from openai import AsyncOpenAI

logger = logging.getLogger("smartsheet")

# Supported model shorthand aliases
MODEL_ALIASES = {
    "gpt-4.1": "gpt-4.1",
    "gpt-4.1-mini": "gpt-4.1-mini",
}


class AIEngine:
    def __init__(
        self,
        api_key: str,
        model: str = "gpt-4.1",
        max_context_rows: int = 200,
        base_url: str = "",
    ):
        kwargs: dict = {"api_key": api_key}
        if base_url:
            kwargs["base_url"] = base_url
        self._client = AsyncOpenAI(**kwargs)
        self._model = model
        self._max_context_rows = max_context_rows
        self._pending: dict[str, dict] = {}  # confirm_id -> result data

    # ─── System Prompt ────────────────────────────────────────

    def _build_system_prompt(self) -> str:
        return (
            "You are an AI assistant embedded in a spreadsheet application called SmartSheet. "
            "You help users analyze data, generate formulas, fill columns, and parse unstructured text into rows.\n\n"
            "Guidelines:\n"
            "- When referencing cells, use Excel-style notation (A1, B2, etc.). Row 1 is the header row.\n"
            "- For formulas, use the supported functions: SUM, AVERAGE, COUNT, COUNTA, MIN, MAX, IF, CONCAT.\n"
            "- Keep answers concise and focused on the spreadsheet data.\n"
            "- When generating values for column fill, return ONLY a JSON array of values, one per target row.\n"
            "- When parsing data dumps, return ONLY a JSON object with 'rows' (array of arrays) and "
            "'column_mapping' (object mapping your columns to existing sheet columns by index).\n"
        )

    # ─── Context Building ─────────────────────────────────────

    def _build_sheet_context(self, sheet_data: dict, selection: dict | None = None) -> str:
        headers = sheet_data.get("headers", [])
        rows = sheet_data.get("rows", [])
        row_count = len(rows)
        col_count = len(headers)

        parts = [f"Sheet has {row_count} rows and {col_count} columns."]
        parts.append(f"Headers: {', '.join(headers)}")

        if row_count <= self._max_context_rows:
            parts.append("\nFull data (CSV format):")
            parts.append(",".join(headers))
            for row in rows:
                parts.append(",".join(str(v) for v in row))
        elif row_count <= 2000:
            parts.append(self._build_stats_summary(sheet_data))
            parts.append("\nFirst 50 rows (CSV format):")
            parts.append(",".join(headers))
            for row in rows[:50]:
                parts.append(",".join(str(v) for v in row))
            if selection:
                sel_start = selection.get("start_row", 0)
                sel_end = selection.get("end_row", min(sel_start + 50, row_count))
                if sel_start > 50:
                    parts.append(f"\nSelected range rows {sel_start + 1}-{sel_end + 1}:")
                    for row in rows[sel_start:sel_end]:
                        parts.append(",".join(str(v) for v in row))
        else:
            parts.append(self._build_stats_summary(sheet_data))
            parts.append("\nFirst 20 rows (CSV format):")
            parts.append(",".join(headers))
            for row in rows[:20]:
                parts.append(",".join(str(v) for v in row))

        return "\n".join(parts)

    def _build_stats_summary(self, sheet_data: dict) -> str:
        headers = sheet_data.get("headers", [])
        rows = sheet_data.get("rows", [])
        if not rows:
            return "\nNo data rows."

        parts = ["\nColumn statistics:"]
        for col_idx, header in enumerate(headers):
            values = [row[col_idx] for row in rows if col_idx < len(row)]
            non_empty = [v for v in values if v is not None and str(v).strip() != ""]
            nums = []
            for v in non_empty:
                try:
                    nums.append(float(v))
                except (ValueError, TypeError):
                    pass

            stat = f"  {header}: {len(non_empty)}/{len(values)} non-empty"
            if nums:
                stat += f", numeric, min={min(nums):.2f}, max={max(nums):.2f}, avg={sum(nums)/len(nums):.2f}"
            else:
                unique = list(dict.fromkeys(str(v) for v in non_empty))[:5]
                stat += f", text, sample values: {unique}"
            parts.append(stat)

        return "\n".join(parts)

    def _messages(self, user_content: str) -> list[dict]:
        """Build standard [system, user] message list."""
        return [
            {"role": "system", "content": self._build_system_prompt()},
            {"role": "user", "content": user_content},
        ]

    # ─── Q&A (Streaming) ─────────────────────────────────────

    async def query(self, sheet_data: dict, question: str, selection: dict | None = None):
        """Streaming Q&A — async generator yielding text chunks."""
        context = self._build_sheet_context(sheet_data, selection)
        user_content = f"Here is the current spreadsheet data:\n\n{context}\n\nQuestion: {question}"

        stream = await self._client.chat.completions.create(
            model=self._model,
            max_tokens=2048,
            messages=self._messages(user_content),
            stream=True,
        )
        async for chunk in stream:
            delta = chunk.choices[0].delta
            if delta.content:
                yield delta.content

    # ─── Column Fill ──────────────────────────────────────────

    async def fill_column(
        self,
        sheet_data: dict,
        column_index: int,
        column_name: str,
        instruction: str,
        target_rows: list[int] | None = None,
    ) -> dict:
        context = self._build_sheet_context(sheet_data)
        rows = sheet_data.get("rows", [])

        if target_rows is None:
            target_rows = list(range(len(rows)))

        user_content = (
            f"Here is the current spreadsheet data:\n\n{context}\n\n"
            f"Fill column '{column_name}' (column index {column_index}) for rows "
            f"{[r + 1 for r in target_rows]} (1-indexed, where row 1 is the header).\n"
            f"Instruction: {instruction}\n\n"
            f"Return ONLY a JSON array of {len(target_rows)} string values, one per target row, in order. "
            f"No explanation, no markdown fences, just the JSON array."
        )

        response = await self._client.chat.completions.create(
            model=self._model,
            max_tokens=4096,
            messages=self._messages(user_content),
        )

        text = response.choices[0].message.content.strip()
        values = self._parse_json_array(text)

        if len(values) != len(target_rows):
            raise ValueError(f"AI returned {len(values)} values, expected {len(target_rows)}")

        fills = []
        for i, row_idx in enumerate(target_rows):
            old_value = ""
            if row_idx < len(rows) and column_index < len(rows[row_idx]):
                old_value = str(rows[row_idx][column_index])
            fills.append({
                "row": row_idx,
                "col": column_index,
                "old_value": old_value,
                "new_value": str(values[i]),
            })

        confirm_id = str(uuid.uuid4())
        self._pending[confirm_id] = {
            "type": "fill",
            "fills": fills,
            "column_name": column_name,
        }

        return {
            "confirm_id": confirm_id,
            "column_name": column_name,
            "fills": fills,
        }

    # ─── Data Dump ────────────────────────────────────────────

    async def parse_dump(self, sheet_data: dict, raw_text: str) -> dict:
        context = self._build_sheet_context(sheet_data)

        user_content = (
            f"Here is the current spreadsheet data:\n\n{context}\n\n"
            f"Parse the following raw text into spreadsheet rows that fit this sheet's structure:\n\n"
            f"---\n{raw_text}\n---\n\n"
            f"Return ONLY a JSON object with:\n"
            f"- \"rows\": array of arrays (each inner array = one row of cell values as strings)\n"
            f"- \"column_mapping\": object mapping column index (0-based) to existing header name\n\n"
            f"No explanation, no markdown fences, just the JSON object."
        )

        response = await self._client.chat.completions.create(
            model=self._model,
            max_tokens=4096,
            messages=self._messages(user_content),
        )

        text = response.choices[0].message.content.strip()
        parsed = self._parse_json_object(text)

        rows = parsed.get("rows", [])
        column_mapping = parsed.get("column_mapping", {})

        confirm_id = str(uuid.uuid4())
        self._pending[confirm_id] = {
            "type": "dump",
            "rows": rows,
            "column_mapping": column_mapping,
        }

        return {
            "confirm_id": confirm_id,
            "rows": rows,
            "column_mapping": column_mapping,
        }

    # ─── Formula Generation ───────────────────────────────────

    async def generate_formula(self, sheet_data: dict, description: str, target_cell: str) -> dict:
        context = self._build_sheet_context(sheet_data)

        user_content = (
            f"Here is the current spreadsheet data:\n\n{context}\n\n"
            f"Generate a formula for cell {target_cell}.\n"
            f"Description: {description}\n\n"
            f"Return ONLY a JSON object with:\n"
            f"- \"formula\": the Excel-style formula string (starting with =)\n"
            f"- \"explanation\": brief explanation of what the formula does\n\n"
            f"Supported functions: SUM, AVERAGE, COUNT, COUNTA, MIN, MAX, IF, CONCAT.\n"
            f"No markdown fences, just the JSON object."
        )

        response = await self._client.chat.completions.create(
            model=self._model,
            max_tokens=1024,
            messages=self._messages(user_content),
        )

        text = response.choices[0].message.content.strip()
        parsed = self._parse_json_object(text)

        formula = parsed.get("formula", "")
        explanation = parsed.get("explanation", "")

        confirm_id = str(uuid.uuid4())
        self._pending[confirm_id] = {
            "type": "formula",
            "formula": formula,
            "target_cell": target_cell,
        }

        return {
            "confirm_id": confirm_id,
            "formula": formula,
            "explanation": explanation,
            "target_cell": target_cell,
        }

    # ─── Edit Sheet (tool use) ────────────────────────────────

    async def edit_sheet(self, sheet_data: dict, instruction: str) -> dict:
        """Edit sheet using OpenAI tool use. Returns pending result for confirmation."""
        context = self._build_sheet_context(sheet_data)
        rows = sheet_data.get("rows", [])

        tools = [
            {
                "type": "function",
                "function": {
                    "name": "set_cells",
                    "description": (
                        "Set one or more cell values. Row indices are 0-based data rows "
                        "(row 0 = first data row, NOT the header). Column indices are 0-based."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "changes": {
                                "type": "array",
                                "description": "Cell changes to apply",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "row": {"type": "integer"},
                                        "col": {"type": "integer"},
                                        "value": {"type": "string"},
                                    },
                                    "required": ["row", "col", "value"],
                                },
                            }
                        },
                        "required": ["changes"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "create_sheet",
                    "description": "Create a new spreadsheet sheet with specific column headers.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "headers": {"type": "array", "items": {"type": "string"}},
                            "initial_rows": {
                                "type": "array",
                                "description": "Optional rows of data to pre-populate",
                                "items": {"type": "array", "items": {"type": "string"}},
                            },
                        },
                        "required": ["name", "headers"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "add_rows",
                    "description": "Append new data rows to the current sheet.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "rows": {
                                "type": "array",
                                "description": "Rows to append, each row is an array of cell values in column order",
                                "items": {"type": "array", "items": {"type": "string"}},
                            }
                        },
                        "required": ["rows"],
                    },
                },
            },
        ]

        system_content = (
            self._build_system_prompt() + "\n\n"
            "EDIT MODE: You have tools to modify the spreadsheet.\n"
            "- set_cells: modify existing cells (row/col are 0-based, row 0 = first data row)\n"
            "- create_sheet: create a new sheet with custom headers and optional data\n"
            "- add_rows: append rows to the current sheet\n"
            "Use tools to make the requested changes, then briefly explain what you did.\n"
        )

        messages: list[dict] = [
            {"role": "system", "content": system_content},
            {
                "role": "user",
                "content": f"Current spreadsheet data:\n\n{context}\n\nInstruction: {instruction}",
            },
        ]

        all_cell_changes: list[dict] = []
        new_sheets: list[dict] = []
        new_rows: list[list] = []
        explanation = ""

        for _ in range(5):  # max 5 agentic rounds
            response = await self._client.chat.completions.create(
                model=self._model,
                max_tokens=4096,
                messages=messages,
                tools=tools,
                tool_choice="auto",
            )

            message = response.choices[0].message
            finish_reason = response.choices[0].finish_reason

            # Collect any text content
            if message.content:
                explanation += message.content

            # No tool calls → done
            if not message.tool_calls:
                break

            # Append assistant message with tool calls
            messages.append(message)

            # Process each tool call and collect results
            tool_result_messages = []
            for tc in message.tool_calls:
                try:
                    args = json.loads(tc.function.arguments)
                except json.JSONDecodeError:
                    args = {}
                result_text = self._apply_edit_tool(
                    tc.function.name, args, rows, all_cell_changes, new_sheets, new_rows
                )
                tool_result_messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result_text,
                })

            messages.extend(tool_result_messages)

            if finish_reason == "stop":
                break

        confirm_id = str(uuid.uuid4())
        self._pending[confirm_id] = {
            "type": "edit",
            "cell_changes": all_cell_changes,
            "new_sheets": new_sheets,
            "new_rows": new_rows,
        }

        return {
            "confirm_id": confirm_id,
            "explanation": explanation.strip(),
            "cell_changes": all_cell_changes,
            "new_sheets": new_sheets,
            "new_rows": new_rows,
        }

    def _apply_edit_tool(
        self,
        name: str,
        args: dict,
        rows: list,
        all_cell_changes: list,
        new_sheets: list,
        new_rows: list,
    ) -> str:
        """Process one tool call and accumulate its changes."""
        try:
            if name == "set_cells":
                changes = args.get("changes", [])
                for ch in changes:
                    row, col, value = ch["row"], ch["col"], ch["value"]
                    old_value = ""
                    if row < len(rows) and col < len(rows[row]):
                        old_value = str(rows[row][col])
                    all_cell_changes.append({
                        "row": row, "col": col,
                        "old_value": old_value, "new_value": value,
                    })
                return f"Queued {len(changes)} cell change(s)"

            elif name == "create_sheet":
                new_sheets.append({
                    "name": args["name"],
                    "headers": args.get("headers", []),
                    "initial_rows": args.get("initial_rows", []),
                })
                return f"Queued new sheet '{args['name']}'"

            elif name == "add_rows":
                batch = args.get("rows", [])
                new_rows.extend(batch)
                return f"Queued {len(batch)} row(s) to append"

            return "Unknown tool"
        except Exception as exc:
            return f"Error: {exc}"

    # ─── Confirm / Cancel ─────────────────────────────────────

    def get_pending_result(self, confirm_id: str) -> dict | None:
        return self._pending.get(confirm_id)

    def remove_pending_result(self, confirm_id: str) -> dict | None:
        return self._pending.pop(confirm_id, None)

    # ─── Backup ───────────────────────────────────────────────

    @staticmethod
    def create_backup(data_dir: Path, sheet_name: str) -> str:
        backup_dir = data_dir / ".backups"
        backup_dir.mkdir(exist_ok=True)
        src = data_dir / f"{sheet_name}.csv"
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        dst = backup_dir / f"{sheet_name}_{ts}.bak"
        shutil.copy2(src, dst)
        logger.info(f"[AI] Backup created: {dst}")
        return str(dst)

    # ─── JSON Parsing Helpers ─────────────────────────────────

    @staticmethod
    def _parse_json_array(text: str) -> list:
        """Extract JSON array from AI response, handling markdown fences."""
        text = text.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines).strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            start = text.find("[")
            end = text.rfind("]")
            if start != -1 and end != -1:
                return json.loads(text[start:end + 1])
            raise ValueError(f"Could not parse JSON array from AI response: {text[:200]}")

    @staticmethod
    def _parse_json_object(text: str) -> dict:
        """Extract JSON object from AI response, handling markdown fences."""
        text = text.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines).strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            start = text.find("{")
            end = text.rfind("}")
            if start != -1 and end != -1:
                return json.loads(text[start:end + 1])
            raise ValueError(f"Could not parse JSON object from AI response: {text[:200]}")


# ─── Singleton ────────────────────────────────────────────

_ai_engine: AIEngine | None = None


def init_ai_engine(
    api_key: str,
    model: str = "gpt-4.1",
    max_context_rows: int = 200,
    base_url: str = "",
) -> AIEngine:
    global _ai_engine
    _ai_engine = AIEngine(api_key, model, max_context_rows, base_url)
    return _ai_engine


def get_ai_engine() -> AIEngine | None:
    return _ai_engine
