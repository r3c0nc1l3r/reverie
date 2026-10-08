"""Live smoke test for the hosted Jev decision engine. Opt-in: it calls OpenRouter and costs about $0.001.

    REVERIE_LIVE_JEV=1 uv run pytest tests/test_jev_live.py -s

It reads OPENROUTER_API_KEY from the environment or Reverie's .env files and is skipped without one.
"""

import os

import pytest

from reverie import model
from reverie.control.server import load_environment

pytestmark = pytest.mark.skipif(os.environ.get("REVERIE_LIVE_JEV") != "1", reason="set REVERIE_LIVE_JEV=1 to run")


@pytest.fixture(scope="module", autouse=True)
def key():
    load_environment()
    try:
        model.openrouter_key()
    except ValueError:
        pytest.skip("no OpenRouter key (OPENROUTER_API_KEY)")


def state():
    return {
        "url": "https://shop.example/checkout", "title": "Checkout", "text": "Checkout\nShipping speed\nPromo code",
        "actions": [
            {"id": "e1", "node": 1, "kind": "fill", "label": "Promo code", "role": "textbox", "value": ""},
            {"id": "e2", "node": 2, "kind": "select", "label": "Shipping speed → Standard", "value": "standard",
             "role": "combobox", "current_value": "standard"},
            {"id": "e3", "node": 2, "kind": "select", "label": "Shipping speed → Express", "value": "express",
             "role": "combobox", "current_value": "standard"},
            {"id": "e4", "node": 3, "kind": "click", "label": "Place order", "role": "button"},
            {"id": "e5", "node": 4, "kind": "click", "label": "Back to cart", "role": "link"},
        ],
    }


@pytest.mark.parametrize("goal, choice", [
    ("Type 'SPRING' into the Promo code field", "e1"),
    ("Choose Express in Shipping speed", "e3"),
    ("Click Place order", "e4"),
    ("Go back to the cart", "e5"),
])
def test_jev_makes_the_expected_decision(goal, choice):
    decision = model.choose(state(), goal, [])
    cost = decision["usage"].get("cost")
    print(f"\n{goal!r}: {decision['choice']} ({decision['operation']}) conf={decision['confidence']:.2f} "
          f"{decision['latency_ms']}ms cost=${cost} model={decision['model']}")
    assert decision["choice"] == choice
