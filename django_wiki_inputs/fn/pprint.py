from django.contrib.auth.models import User
from aiostream import core, stream
from django.template.loader import render_to_string
import logging
import ipdb  # NOQA

from .. import stream as my_stream

logger = logging.getLogger(__name__)


@core.operator  # NOQA
async def pprint(ic, args):
    a = [await my_stream.arg_stream(ic, ic.user.username, arg) for arg in args]
    source = stream.ziplatest(*a, partial=False)

    async with core.streamcontext(source) as streamer:
        async for item in streamer:
            keys = list()
            vals = dict()

            for i, val in enumerate(item):
                if val is None or val['type'] is None:
                    continue

                if val['type'] in ['html']:
                    if None not in keys:
                        keys.insert(0, None)
                        vals[None] = [None] * len(item)

                    vals[None][i] = val['val']

                elif val['type'] in ['int', 'float', 'str', 'text', 'textarea', 'files', 'stdout', 'error']:
                    if None not in keys:
                        keys.insert(0, None)
                        vals[None] = [None] * len(item)

                    vals[None][i] = render_to_string(f"wiki/plugins/inputs/pprint.html", context=val)

                elif val['type'] == 'user-list':
                    for u, v in val['val'].items():
                        if u not in keys:
                            keys.append(u)
                            vals[u] = [None] * len(item)

                        vals[u][i] = render_to_string(f"wiki/plugins/inputs/pprint.html", context=v)

                else:
                    logger.error(val)


            if len(keys) == 0:
                yield None
                continue

            if len(keys) == 1 and keys[0] is None:
                html = " ".join(vals[keys[0]])

            else:
                html = "<table>"

                for k in keys:
                    html += "<tr><th>"
                    if k is None:
                        html += "&nbsp;"
                    elif isinstance(k, User):
                        html += f"{k.first_name} {k.last_name}"
                    else:
                        html += str(k)
                    html += "</th>"

                    for v in vals[k]:
                        html += f"<td>{v!s}</td>"

                    html += "</tr>"
                html += "</table>"

            yield {'type': 'html', 'val': html}
