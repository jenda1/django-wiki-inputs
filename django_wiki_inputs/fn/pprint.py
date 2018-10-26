from django.contrib.auth.models import User, Group
from aiostream import core
from collections import defaultdict
from django.template.loader import render_to_string
import logging
import ipdb  # NOQA

from .. import stream

logger = logging.getLogger(__name__)


@core.operator
async def pprint(ic, args):
    source = stream.args_stream(ic, args)

    async with core.streamcontext(source) as streamer:
        async for item in streamer:
            data = item['args']

            keys = list()
            vals = dict()

            for i,val in enumerate(data):
                if val is None:
                    continue

                if val['type'] in ['html']:
                    if None not in keys:
                        keys.insert(0, None)
                        vals[None] = [None] * len(data)

                    vals[None][i] = val['val']

                elif val['type'] in ['int', 'str', 'float', 'files']:
                    if None not in keys:
                        keys.insert(0, None)
                        vals[None] = [None] * len(data)

                    vals[None][i] = render_to_string(f"wiki/plugins/inputs/pprint.html", context=val)

                elif val['type'] == 'user-list':
                    for u,v in val['val'].items():
                        if u not in keys:
                            keys.append(u)
                            vals[u] = [None] * len(data)

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
