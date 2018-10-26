from aiostream import stream, core
import logging
from channels.db import database_sync_to_async
import re
import pathlib
from .. import stream as my_stream
from .. import misc
from .. import models
import ipdb  # NOQA

logger = logging.getLogger(__name__)


filt_re = re.compile(r"^_(.+)_$")

@database_sync_to_async
def db_get_input_users(article, name, flt):
    q = models.Input.objects.filter(article=article, name=name)
    if flt == '_all_':
        pass
    else:
        m = filt_re.match(flt)
        if m:
            q = q.filter(owner__group__name=m.group(1))
        else:
            q = q.filter(owner__username=flt).first()

    return q.order_by('article', 'name', 'owner', '-created').distinct('article', 'name', 'owner')


@core.operator
async def get(ic, args):
    if len(args) < 2:
        yield {'type':'error', 'val':"⚠ get() requires at least 2 arguments ⚠"}
        return

    if not isinstance(args[0], pathlib.Path):
        yield {'type':'error', 'val':"⚠ get() first argument must be input ⚠"}
        return

    field_src = await my_stream.field_src(ic, args[0])
    if field_src is None:
        yield {'type':'error', 'val':"⚠ get() first argument must be existing input ⚠"}
        return

    users = set()

    while True:
        logger.er
        src = [my_stream.read_field(ic, x, field_src) for x in users]
        src += [await my_stream.arg_stream(ic, ic.user, x) for x in args[1:]]

        s = stream.ziplatest(*src, partial=False)
        async with core.streamcontext(s) as streamer:
            async for i in streamer:
                if None in i[len(users):]:
                    continue

                users_new = set()
                for x in i[len(users):]:
                    if x['type'] != 'str':
                        logger.warning(f"??? {x}")
                        continue

                    for u in await db_get_input_users(field_src[0].article, field_src[1], x['val']):
                        if u.owner in users_new:
                            continue
                        if ic.user.pk == field_src[0].article.current_revision.user.pk:
                            users_new.add(u.owner)
                            continue
                        # FIXME: can_read!!!

                if users != users_new:
                    users = users_new
                    break

                yield {'type': 'user-list', 'val': dict(zip(users, i[:len(users)]))}

            else:
                return
