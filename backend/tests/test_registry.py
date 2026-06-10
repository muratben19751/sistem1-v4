"""app/engines/registry.py — motor secimi."""
from app.engines.bybit_engine import bybit_engine, demo_engine
from app.engines.paper_engine import paper_engine
from app.engines.registry import get_engine


class TestGetEngine:
    def test_bybit(self):
        assert get_engine("bybit") is bybit_engine

    def test_demo(self):
        assert get_engine("demo") is demo_engine

    def test_paper_explicit(self):
        assert get_engine("paper") is paper_engine

    def test_none_defaults_to_paper(self):
        assert get_engine(None) is paper_engine

    def test_unknown_defaults_to_paper(self):
        assert get_engine("whatever") is paper_engine

    def test_engine_names(self):
        assert paper_engine.name == "paper"
