"""The map page.

The script and the style are inlined into the HTML. With debug mode off, Django does not
serve static files, and this page has to work from the one response.
"""

from pathlib import Path

from django.views.generic import TemplateView

_PAGE_DIR = Path(__file__).resolve().parent / "static" / "trips"


class MapView(TemplateView):
    """Click a start and a finish, then see the road, the fuel stops and the cost."""

    template_name = "trips/map.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Read on each request so editing the page shows up without a restart.
        context["map_style"] = (_PAGE_DIR / "map.css").read_text()
        context["map_script"] = (_PAGE_DIR / "map.mjs").read_text()
        return context
