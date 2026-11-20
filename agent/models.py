"""
agent/models.py
─────────────────────────────────────────────────────────────────────────────
All data structures shared across the agent pipeline.

PageSnapshot  — what the crawler captured from one page
TestStep      — one executable action (goto, fill, click, assert...)
TestCase      — a full AI-generated test (name + steps + expected outcome)
StepResult    — outcome of executing one step
TestResult    — outcome of executing a full TestCase
─────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional


# ─────────────────────────────────────────────────────────────────────────────
# CRAWL MODELS
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class FormField:
    """One input / textarea / select element inside a form."""
    tag: str                            # input, textarea, select
    field_type: str = ""                # text, email, password, checkbox, ...
    name: str = ""
    id: str = ""
    placeholder: str = ""
    label: str = ""
    selector: str = ""                  # best CSS selector for this field
    options: list[str] = field(default_factory=list)   # select options


@dataclass
class PageForm:
    """A <form> element with all its fields."""
    action: str = ""
    method: str = "get"
    fields: list[FormField] = field(default_factory=list)
    submit_text: str = "Submit"


@dataclass
class PageSnapshot:
    """Everything the crawler captured from one URL."""
    url: str
    title: str
    forms: list[PageForm] = field(default_factory=list)
    buttons: list[dict] = field(default_factory=list)   # [{text, selector, type}]
    links: list[dict] = field(default_factory=list)     # [{text, href}]
    headings: list[str] = field(default_factory=list)
    nav_items: list[str] = field(default_factory=list)
    nav_links: list[dict] = field(default_factory=list)   # [{text, href}] with full hrefs
    error: Optional[str] = None

    def as_dict(self) -> dict:
        """Compact dict for sending to Gemini (skip empty fields)."""
        forms_data = []
        for f in self.forms:
            fields_data = []
            for ff in f.fields:
                fd = {
                    "tag":      ff.tag,
                    "type":     ff.field_type,
                    "selector": ff.selector,
                }
                if ff.label:       fd["label"]       = ff.label
                if ff.placeholder: fd["placeholder"]  = ff.placeholder
                if ff.name:        fd["name"]         = ff.name
                if ff.options:     fd["options"]      = ff.options[:8]
                fields_data.append(fd)
            forms_data.append({
                "fields":      fields_data,
                "submit_text": f.submit_text,
            })

        return {
            "url":      self.url,
            "title":    self.title,
            "forms":    forms_data,
            "buttons":  self.buttons[:15],
            "headings": self.headings[:8],
            "nav":      self.nav_items[:10],
            "nav_links": self.nav_links[:20],
            "links":    self.links[:20],
        }


# ─────────────────────────────────────────────────────────────────────────────
# TEST MODELS
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class TestStep:
    """
    One executable step. The 'action' field determines which other fields apply.

    Supported actions:
        goto            url=<full URL>
        fill            selector=<CSS>  value=<text>
        click           selector=<CSS>
        select          selector=<CSS>  value=<option text>
        wait            value=<ms as string>
        wait_visible    selector=<CSS>
        assert_visible      selector=<CSS>
        assert_not_visible  selector=<CSS>
        assert_text         selector=<CSS>  value=<expected text substring>
        assert_url          value=<URL substring>
        screenshot
    """
    action: str
    selector: str = ""
    value: str = ""
    url: str = ""
    description: str = ""

    def as_dict(self) -> dict:
        return {k: v for k, v in vars(self).items() if v}

    @classmethod
    def from_dict(cls, d: dict) -> "TestStep":
        return cls(
            action      = d.get("action", ""),
            selector    = d.get("selector", ""),
            value       = d.get("value", ""),
            url         = d.get("url", ""),
            description = d.get("description", ""),
        )


@dataclass
class TestCase:
    """
    A complete AI-generated test: name, category, steps, expected outcome.
    Created by TestGenerator, consumed by Executor.
    """
    id: str
    name: str
    category: str
    priority: str                               # HIGH | MEDIUM | LOW
    steps: list[TestStep]
    expected_outcome: str
    inputs: dict = field(default_factory=dict)  # human-readable summary of inputs used
    generated_by: str = "gemini"
    source_page: str = ""

    def as_dict(self) -> dict:
        return {
            "id":               self.id,
            "name":             self.name,
            "category":         self.category,
            "priority":         self.priority,
            "expected_outcome": self.expected_outcome,
            "inputs":           self.inputs,
            "steps":            [s.as_dict() for s in self.steps],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "TestCase":
        steps = [TestStep.from_dict(s) for s in d.get("steps", [])]
        return cls(
            id               = d.get("id", "TC-?"),
            name             = d.get("name", "Unnamed test"),
            category         = d.get("category", "General"),
            priority         = d.get("priority", "MEDIUM"),
            steps            = steps,
            expected_outcome = d.get("expected_outcome", ""),
            inputs           = d.get("inputs", {}),
        )


@dataclass
class StepResult:
    """Outcome of executing one TestStep."""
    step: TestStep
    status: str         # PASS | FAIL | ERROR | SKIP
    message: str = ""


@dataclass
class TestResult:
    """Outcome of executing one TestCase."""
    test_case: TestCase
    status: str         # PASS | FAIL | ERROR
    actual_outcome: str
    duration_ms: float
    step_results: list[StepResult] = field(default_factory=list)
    screenshot: str = ""    # file path, set on failure
    error: str = ""

    def as_dict(self) -> dict:
        return {
            "id":               self.test_case.id,
            "name":             self.test_case.name,
            "category":         self.test_case.category,
            "priority":         self.test_case.priority,
            "status":           self.status,
            "actual_outcome":   self.actual_outcome,
            "expected_outcome": self.test_case.expected_outcome,
            "duration_ms":      round(self.duration_ms),
            "inputs":           self.test_case.inputs,
            "screenshot":       self.screenshot,
            "error":            self.error,
            "steps": [
                {"action": sr.step.action, "status": sr.status, "message": sr.message}
                for sr in self.step_results
            ],
        }