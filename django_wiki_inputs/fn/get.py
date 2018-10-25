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


@database_sync_to_async
def db_get_input_users(article, name, flt):
    if flt == 'all':
        return models.Input.objects.filter(
            article=article,
            name=name).order_by('article', 'name', 'owner', '-created').distinct('article', 'name', 'owner')
    else:
        return models.Input.objects.filter(
            article=article,
            owner__group__name=flt,
            name=name).order_by('article', 'name', 'owner', '-created').distinct('article', 'name', 'owner')



filt_re = re.compile(r"^_(.+)_$")

async def get_users(article, name, flt):
    m = filt_re.match(flt)

    if not m:
        return [await misc.db_get_user(flt)]

    return [x.owner for x in await db_get_input_users(article, name, m.group(1))]


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
        src = [my_stream.read_field(ic, x, field_src) for x in users]
        src += [await my_stream.arg_stream(ic, ic.user, x) for x in args[1:]]

        s = stream.ziplatest(*src)
        async with core.streamcontext(s) as streamer:
            async for i in streamer:
                if None in i[len(users):]:
                    continue

                users_new = set()
                for x in i[len(users):]:
                    if x['type'] != 'str':
                        logger.warning(f"??? {x}")
                        continue

                    for u in await get_users(field_src[0].article, field_src[1], x['val']):
                        if u in users_new:
                            continue
                        if ic.user.pk == field_src[0].article.current_revision.user.pk:
                            users_new.add(u)
                            continue
                        # FIXME: can_read!!!

                if users != users_new:
                    users = users_new
                    break
                
                yield {'type': 'user-list', 'val': dict(zip(users, i[:len(users)]))}

            else:
                return
