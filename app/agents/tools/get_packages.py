"""``get_packages`` — lists the currently-sold packages with live prices.

The Worker resolves the active catalog from D1 (packages joined to their
categories, panels and the live price list) and computes a per-package minimum
price (base + all mandatory location extras), so the agent never has to
reconstruct the pricing formula and can quote exact figures. The catalog is
global, but the factory still takes a ``ToolContext`` for uniformity with the
other tools and to keep ``build_tools`` signature-stable as they grow.
"""

import json

from langchain.tools import tool


def get_packages_tool(ctx):
    """Build the catalog tool. ``ctx`` carries the WorkerClient."""

    @tool
    async def get_packages() -> str:
        """List the packages currently on sale, with live prices and limits.

        Returns a JSON document with, per package: title, description,
        category, panel name, data quota (GB), validity days, base price,
        minimum price (base + all mandatory locations), and every active
        location with its extra price and a ``mandatory`` flag. Use this for
        any question about what is sold, how much it costs, or what each
        package includes — never guess prices or limits.
        """
        result = await ctx.worker.get_packages()
        return json.dumps(result, ensure_ascii=False)

    return get_packages
