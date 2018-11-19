from django.contrib.auth.models import User
from aiostream import core, stream
from django.template.loader import render_to_string
import logging
from channels.db import database_sync_to_async
import ipdb  # NOQA

from .. import stream as my_stream
from .. import models

logger = logging.getLogger(__name__)


@database_sync_to_async
def get_history(pk):
    try:
        i = models.Input.objects.get(pk=pk)
    except models.Input.DoesNotExist:
        logger.debug(f"pk={pk}")
        return ""

    out = ""
    for v in models.Input.objects.filter(article=i.article, name=i.name, owner=i.owner):
        val = my_stream.input_to_dict(v)
        html = render_to_string(f"wiki/plugins/inputs/pprint.html", context=val)
        out += f"<li>{v.name} {v.created} {v.author} ({v.pk}): {html}</li>"

    return f"<ul>{out}</ul>" if len(out) else ""


@core.operator  # NOQA
async def pprint(ic, args):
    a = [await my_stream.arg_stream(ic, ic.user, arg) for arg in args]
    source = stream.ziplatest(*a, partial=False)

    async with core.streamcontext(source) as streamer:
        async for item in streamer:
            keys = list()
            vals = dict()
            info = list()

            for i, val in enumerate(item):
                if val is None:
                    continue

                if val.get('pk') is not None:
                    info.append(await get_history(val['pk']))

                if val['type'] is None:
                    pass

                elif val['type'] in ['html']:
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

            html = render_to_string("wiki/plugins/inputs/pprint_full.html", context={'html': html, 'info': "".join(info)})

            yield {'type': 'html', 'val': html}
