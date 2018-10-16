from aiostream import core
from django.template.loader import render_to_string
import ipdb  # NOQA

from .. import stream


@core.operator
async def pprint(ic, args):
    source = stream.args_stream(ic, args)

    async with core.streamcontext(source) as streamer:
        async for item in streamer:
            out = list()

            for i in item['args']:
                if type(i) in [int, str, float]:
                    val = {'type': type(i), 'val': i}

                elif type(i) is dict and 'type' in i:
                    val = i

                else:
                    val = {'type': type(i), 'val': i}

                out.append(render_to_string(f"wiki/plugins/inputs/pprint.html", context=val))

            if len(out) == 0:
                yield None
            elif len(out) == 1:
                yield out[0]
            else:
                yield "<table><tr><td>" + "</td><td>".join(out) + "</td></tr></table>"
